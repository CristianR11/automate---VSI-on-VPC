#!/usr/bin/env python3
"""
IBM Cloud VPC VSI Manager — Automatización Start/Stop con Schematics failover
Grupo Marna · El Tunal

Operaciones:
  start   Enciende la instancia existente. Si falla, la recrea en otra zona
          usando IBM Schematics (Terraform).
  stop    Valida snapshots del día y detiene la instancia.
  status  Consulta el estado actual sin modificar nada.
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ibm_vpc import VpcV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core import ApiException

# Módulos del proyecto
try:
    from cos_storage import COSStorage
    COS_AVAILABLE = True
except ImportError:
    COS_AVAILABLE = False
    logging.warning("cos_storage no disponible — usando almacenamiento local")

try:
    from schematics_client import SchematicsClient
    SCHEMATICS_AVAILABLE = True
except ImportError:
    SCHEMATICS_AVAILABLE = False
    logging.warning("schematics_client no disponible — failover de recreación deshabilitado")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

TZ_BOGOTA = ZoneInfo("America/Bogota")


# ─── Clase principal ─────────────────────────────────────────────────────────

class VSIManager:
    """
    Gestiona el ciclo de vida de la VSI GPU de El Tunal:
      - Encendido inteligente con failover multi-zona vía Schematics
      - Apagado con validación estricta de snapshots pre-shutdown
    """

    def __init__(self, config_file: str = "config.json"):
        self.api_key = os.environ.get("IBM_CLOUD_API_KEY")
        if not self.api_key:
            raise ValueError("IBM_CLOUD_API_KEY no está configurada")

        self.region = os.environ.get("IBM_CLOUD_REGION", "us-east")

        # ── Cargar config ────────────────────────────────────────────────────
        with open(config_file, "r") as f:
            self.config = json.load(f)

        # ── Variables explícitas de recursos activos (desde env del job) ────
        # El job STOP las usa para saber exactamente qué validar.
        # El job START las actualiza en el Secret de Code Engine al terminar.
        self.instance_id   = os.environ.get("INSTANCE_ID")
        self.boot_vol_id   = os.environ.get("BOOT_VOLUME_ID")
        self.data_vol_id   = os.environ.get("DATA_VOLUME_ID")
        self.backup_policy = os.environ.get("BACKUP_POLICY_ID",
                                            self.config.get("backup_policy_id"))

        # IDs de snapshots para recreación (cuando no hay instancia)
        self.boot_snapshot_id = os.environ.get("BOOT_VOLUME_SNAPSHOT_ID")
        self.data_snapshot_id = os.environ.get("DATA_VOLUME_SNAPSHOT_ID")

        # Ventana de validación de snapshot (minutos)
        self.snapshot_max_age_min = int(
            os.environ.get("SNAPSHOT_MAX_AGE_MINUTES",
                           self.config.get("snapshot_max_age_minutes", 60))
        )

        # Tiempo máximo esperando que el servidor arranque (minutos)
        self.max_start_wait_min = int(
            os.environ.get("MAX_START_WAIT_MINUTES",
                           self.config.get("max_start_wait_minutes", 20))
        )

        # ── Autenticación VPC ────────────────────────────────────────────────
        auth = IAMAuthenticator(self.api_key)
        self.vpc = VpcV1(authenticator=auth)
        self.vpc.set_service_url(f"https://{self.region}.iaas.cloud.ibm.com/v1")

        # ── COS ──────────────────────────────────────────────────────────────
        self.cos: Optional[COSStorage] = None
        if COS_AVAILABLE:
            try:
                self.cos = COSStorage()
                logger.info("COS inicializado correctamente")
            except Exception as e:
                logger.warning(f"No se pudo inicializar COS: {e}")

        # ── Schematics ───────────────────────────────────────────────────────
        self.schematics: Optional[SchematicsClient] = None
        if SCHEMATICS_AVAILABLE:
            try:
                self.schematics = SchematicsClient()
                logger.info("SchematicsClient inicializado correctamente")
            except Exception as e:
                logger.warning(f"No se pudo inicializar SchematicsClient: {e}")

        self.state_file = self.config.get("state_file", "vsi_state.json")

        logger.info(f"VSIManager inicializado — región={self.region} "
                    f"COS={'OK' if self.cos else 'NO'} "
                    f"Schematics={'OK' if self.schematics else 'NO'}")

    # ─── Estado ───────────────────────────────────────────────────────────────

    def load_state(self) -> Dict:
        if self.cos:
            try:
                state = self.cos.load_state()
                if state:
                    logger.info("Estado cargado desde COS")
                    return state
            except Exception as e:
                logger.warning(f"Error al cargar estado desde COS: {e}")

        if os.path.exists(self.state_file):
            with open(self.state_file, "r") as f:
                logger.info("Estado cargado desde archivo local")
                return json.load(f)

        logger.info("Sin estado previo — empezando con estado vacío")
        return {}

    def save_state(self, state: Dict):
        if self.cos:
            try:
                self.cos.save_state(state)
            except Exception as e:
                logger.error(f"Error guardando estado en COS: {e}")

        try:
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Error guardando estado local: {e}")

    def save_execution_log(self, log: Dict):
        if self.cos:
            try:
                self.cos.save_execution_log(log)
            except Exception as e:
                logger.error(f"Error guardando log de ejecución: {e}")

    # ─── VPC helpers ──────────────────────────────────────────────────────────

    def get_instance_status(self, instance_id: str) -> Tuple[str, bool]:
        """
        Retorna (status, is_error).
        is_error=True cuando el status es un estado terminal de fallo.
        """
        try:
            resp = self.vpc.get_instance(id=instance_id)
            status = resp.get_result().get("status", "unknown")
            is_error = status in ("failed", "deleting", "deleted")
            return status, is_error
        except ApiException as e:
            if e.code == 404:
                return "not_found", True
            logger.error(f"Error consultando instancia {instance_id}: {e}")
            return "error", True

    def wait_for_instance_running(self, instance_id: str) -> bool:
        """
        Espera hasta que la instancia esté en estado 'running'.
        Retorna True si llegó a running, False si hubo error o timeout.
        """
        max_seconds = self.max_start_wait_min * 60
        check_interval = self.config.get("check_interval_seconds", 30)
        start = time.time()

        logger.info(f"Esperando que instancia {instance_id} quede running "
                    f"(max {self.max_start_wait_min} min)...")

        while time.time() - start < max_seconds:
            status, is_error = self.get_instance_status(instance_id)

            if status == "running":
                logger.info(f"Instancia {instance_id} está running")
                return True

            if is_error:
                logger.error(f"Instancia {instance_id} en estado de error: {status}")
                return False

            elapsed = int(time.time() - start)
            logger.info(f"  Estado actual: {status} — {elapsed}s transcurridos")
            time.sleep(check_interval)

        logger.error(f"Timeout ({self.max_start_wait_min} min) esperando instancia {instance_id}")
        return False

    def get_instance_volumes(self, instance_id: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Retorna (boot_volume_id, data_volume_id) de la instancia.
        data_volume_id puede ser None si no tiene volumen de datos.
        """
        try:
            resp = self.vpc.get_instance(id=instance_id)
            inst = resp.get_result()

            boot_vol = inst.get("boot_volume_attachment", {}).get("volume", {}).get("id")

            data_vol = None
            for att in inst.get("volume_attachments", []):
                vol_id = att.get("volume", {}).get("id")
                if vol_id and vol_id != boot_vol:
                    data_vol = vol_id
                    break

            logger.info(f"Volúmenes instancia {instance_id}: boot={boot_vol} data={data_vol}")
            return boot_vol, data_vol

        except ApiException as e:
            logger.error(f"Error obteniendo volúmenes de {instance_id}: {e}")
            return None, None

    def get_data_volume_attachment_status(self, instance_id: str, volume_id: str) -> str:
        """Retorna el status del attachment de un volumen específico."""
        try:
            resp = self.vpc.list_instance_volume_attachments(instance_id=instance_id)
            for att in resp.get_result().get("volume_attachments", []):
                if att.get("volume", {}).get("id") == volume_id:
                    return att.get("status", "unknown")
            return "not_found"
        except ApiException as e:
            logger.error(f"Error obteniendo attachment status: {e}")
            return "error"

    def get_latest_snapshot_for_volume(self, volume_id: str) -> Optional[Dict]:
        """Retorna el snapshot más reciente (cualquier estado) de un volumen."""
        try:
            resp = self.vpc.list_snapshots()
            snaps = [
                s for s in resp.get_result().get("snapshots", [])
                if s.get("source_volume", {}).get("id") == volume_id
            ]
            if not snaps:
                return None
            snaps.sort(key=lambda s: s.get("created_at", ""), reverse=True)
            return snaps[0]
        except ApiException as e:
            logger.error(f"Error buscando snapshots del volumen {volume_id}: {e}")
            return None

    def cleanup_zone_resources(
        self,
        zone_name: str,
        instance_id: Optional[str],
        subnet_id: Optional[str],
        prefix_id: Optional[str],
    ):
        """Elimina recursos de una zona en el orden correcto: instancia → subnet → prefix."""
        logger.warning(f"Limpiando recursos de zona {zone_name}...")

        if instance_id:
            try:
                self.vpc.delete_instance(id=instance_id)
                logger.info(f"  Instancia {instance_id} eliminada — esperando 30s")
                time.sleep(30)
            except ApiException as e:
                logger.error(f"  Error eliminando instancia: {e}")

        if subnet_id:
            try:
                self.vpc.delete_subnet(id=subnet_id)
                logger.info(f"  Subnet {subnet_id} eliminada")
                time.sleep(5)
            except ApiException as e:
                logger.error(f"  Error eliminando subnet: {e}")

        if prefix_id:
            try:
                vpc_id = self.config["vpc"]["id"]
                self.vpc.delete_vpc_address_prefix(vpc_id=vpc_id, id=prefix_id)
                logger.info(f"  Address prefix {prefix_id} eliminado")
                time.sleep(2)
            except ApiException as e:
                logger.error(f"  Error eliminando address prefix: {e}")

        logger.info(f"Limpieza de zona {zone_name} completada")

    # ─── STOP ─────────────────────────────────────────────────────────────────

    def _validate_snapshot(self, volume_id: str, label: str) -> Tuple[bool, str]:
        """
        Valida que exista un snapshot del día de hoy (America/Bogota) para el volumen.

        Reglas:
          1. Debe existir al menos un snapshot con created_at = hoy en Bogotá (bloqueo duro).
          2. Si el snapshot más reciente del día tiene más de snapshot_max_age_min minutos
             de antigüedad → advertencia en log, pero NO bloquea.
          3. El snapshot debe estar en estado 'stable'.

        Retorna:
            (ok: bool, mensaje: str)
        """
        now_bogota = datetime.now(TZ_BOGOTA)
        today_bogota = now_bogota.date()
        now_utc = datetime.now(timezone.utc)

        logger.info(f"Validando snapshot de {label} (volumen {volume_id})...")
        logger.info(f"  Fecha hoy (Bogotá): {today_bogota}  Hora: {now_bogota.strftime('%H:%M')}")

        snapshot = self.get_latest_snapshot_for_volume(volume_id)

        if snapshot is None:
            msg = f"No se encontró ningún snapshot para el volumen {label} ({volume_id})"
            logger.error(f"  BLOQUEO: {msg}")
            return False, msg

        snap_id = snapshot["id"]
        snap_state = snapshot.get("lifecycle_state", "unknown")
        created_raw = snapshot.get("created_at", "")

        # Parsear fecha de creación del snapshot
        try:
            created_utc = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            created_bogota = created_utc.astimezone(TZ_BOGOTA)
        except ValueError:
            msg = f"No se pudo parsear created_at='{created_raw}' del snapshot {snap_id}"
            logger.error(f"  BLOQUEO: {msg}")
            return False, msg

        logger.info(f"  Snapshot más reciente: {snap_id}  estado={snap_state}  creado={created_bogota.strftime('%Y-%m-%d %H:%M %Z')}")

        # ── Regla 1: debe ser del día de hoy ─────────────────────────────────
        if created_bogota.date() != today_bogota:
            msg = (
                f"El snapshot más reciente del volumen {label} es del "
                f"{created_bogota.date()} pero hoy es {today_bogota} (Bogotá). "
                f"La backup policy no generó snapshot hoy."
            )
            logger.error(f"  BLOQUEO: {msg}")
            return False, msg

        # ── Regla 2: estado del snapshot ─────────────────────────────────────
        if snap_state == "pending":
            # Esperar hasta 3 reintentos de 5 minutos
            for attempt in range(1, 4):
                logger.warning(f"  Snapshot {snap_id} en estado 'pending' — esperando 5min (intento {attempt}/3)")
                time.sleep(300)
                snap_refreshed = self.get_latest_snapshot_for_volume(volume_id)
                if snap_refreshed:
                    snap_state = snap_refreshed.get("lifecycle_state", "unknown")
                    if snap_state == "stable":
                        break
            if snap_state != "stable":
                msg = f"Snapshot {snap_id} de {label} sigue en estado '{snap_state}' después de esperar 15min"
                logger.error(f"  BLOQUEO: {msg}")
                return False, msg

        if snap_state == "failed":
            msg = f"Snapshot {snap_id} de {label} está en estado 'failed'"
            logger.error(f"  BLOQUEO: {msg}")
            return False, msg

        if snap_state != "stable":
            msg = f"Snapshot {snap_id} de {label} en estado inesperado: '{snap_state}'"
            logger.error(f"  BLOQUEO: {msg}")
            return False, msg

        # ── Regla 3: ventana de antigüedad ───────────────────────────────────
        age_minutes = (now_utc - created_utc).total_seconds() / 60
        if age_minutes > self.snapshot_max_age_min:
            logger.warning(
                f"  ADVERTENCIA: snapshot {snap_id} de {label} tiene "
                f"{age_minutes:.0f} min de antigüedad (umbral: {self.snapshot_max_age_min} min). "
                f"La backup policy puede haber corrido temprano. Continuando."
            )
        else:
            logger.info(f"  OK: snapshot {snap_id} tiene {age_minutes:.0f} min — dentro de ventana")

        return True, f"snapshot {snap_id} válido (estado={snap_state}, antigüedad={age_minutes:.0f}min)"

    def stop_instance(self, force: bool = False) -> Dict:
        """
        Detiene la instancia activa.

        Flujo:
          F1 — Validar variables del job
          F2 — Verificar estado de la instancia en VPC
          F3 — Validar volúmenes atachados
          F4 — Validar snapshots del día (bloqueo duro)
          F5 — Ejecutar stop
          F6 — Persistir estado en COS

        Args:
            force: Si True omite F4 (validación de snapshots) con advertencia en log.
        """
        start_time = datetime.now()
        exec_log = {
            "action": "stop",
            "start_time": start_time.isoformat(),
            "region": self.region,
            "force": force,
        }

        try:
            # ── F1: Variables del job ─────────────────────────────────────────
            instance_id = self.instance_id
            boot_vol_id = self.boot_vol_id
            data_vol_id = self.data_vol_id

            # Fallback: leer del estado en COS si las variables no están
            if not instance_id or not boot_vol_id:
                logger.warning("INSTANCE_ID o BOOT_VOLUME_ID no configurados en el job — leyendo desde estado COS")
                state = self.load_state()
                instance_id = instance_id or state.get("active_instance_id")
                boot_vol_id = boot_vol_id or state.get("boot_volume_id")
                data_vol_id = data_vol_id or state.get("data_volume_id") or state.get("volume_ids", [None, None])[1] if state.get("volume_ids") and len(state.get("volume_ids", [])) > 1 else data_vol_id

            if not instance_id:
                return self._stop_error(exec_log, "INSTANCE_ID no configurado y no hay estado en COS")
            if not boot_vol_id:
                return self._stop_error(exec_log, "BOOT_VOLUME_ID no configurado y no hay estado en COS")

            exec_log["instance_id"] = instance_id
            exec_log["boot_volume_id"] = boot_vol_id
            exec_log["data_volume_id"] = data_vol_id

            # ── F2: Estado de la instancia ────────────────────────────────────
            status, is_error = self.get_instance_status(instance_id)

            if status == "not_found":
                exec_log["status"] = "ok"
                exec_log["result"] = "instance_not_found"
                exec_log["end_time"] = datetime.now().isoformat()
                self.save_execution_log(exec_log)
                logger.info(f"Instancia {instance_id} no encontrada en VPC — nada que detener")
                return {"status": "ok", "message": "Instancia no encontrada"}

            if status == "stopped":
                exec_log["status"] = "ok"
                exec_log["result"] = "already_stopped"
                exec_log["end_time"] = datetime.now().isoformat()
                self.save_execution_log(exec_log)
                logger.info("Instancia ya está detenida")
                return {"status": "ok", "message": "Instancia ya está detenida"}

            if is_error:
                return self._stop_error(exec_log, f"Instancia en estado de error: {status}")

            if status != "running":
                return self._stop_error(exec_log, f"Estado inesperado de la instancia: {status}")

            # ── F3: Validar volúmenes atachados ───────────────────────────────
            actual_boot, actual_data = self.get_instance_volumes(instance_id)

            if actual_boot and actual_boot != boot_vol_id:
                logger.warning(
                    f"ADVERTENCIA: boot volume esperado={boot_vol_id} "
                    f"vs actual={actual_boot}. Continuando con el actual."
                )
                boot_vol_id = actual_boot

            if data_vol_id and actual_data and actual_data != data_vol_id:
                logger.warning(
                    f"ADVERTENCIA: data volume esperado={data_vol_id} "
                    f"vs actual={actual_data}. Continuando con el actual."
                )
                data_vol_id = actual_data
            elif not data_vol_id and actual_data:
                data_vol_id = actual_data

            # ── F4: Validar snapshots ─────────────────────────────────────────
            snapshot_results = {}

            if force:
                logger.warning("--force activo: omitiendo validación de snapshots")
                exec_log["snapshot_validation"] = "skipped_force"
            else:
                boot_ok, boot_msg = self._validate_snapshot(boot_vol_id, "boot")
                snapshot_results["boot"] = {"ok": boot_ok, "msg": boot_msg}

                data_ok = True
                data_msg = "no data volume"
                if data_vol_id:
                    data_ok, data_msg = self._validate_snapshot(data_vol_id, "data")
                    snapshot_results["data"] = {"ok": data_ok, "msg": data_msg}

                exec_log["snapshot_validation"] = snapshot_results

                if not boot_ok or not data_ok:
                    failed = []
                    if not boot_ok:
                        failed.append(f"boot: {boot_msg}")
                    if not data_ok:
                        failed.append(f"data: {data_msg}")

                    error_msg = (
                        "Apagado BLOQUEADO por validación de snapshots. "
                        "Usa --force para ignorar. Detalle: " + " | ".join(failed)
                    )
                    return self._stop_error(exec_log, error_msg)

                logger.info("Validación de snapshots OK — procediendo con el apagado")

            # ── F5: Ejecutar stop ─────────────────────────────────────────────
            logger.info(f"Enviando acción STOP a instancia {instance_id}...")
            for attempt in range(1, 3):
                try:
                    self.vpc.create_instance_action(instance_id=instance_id, type="stop")
                    break
                except ApiException as e:
                    if attempt == 2:
                        return self._stop_error(exec_log, f"Error enviando STOP (intento 2/2): {e}")
                    logger.warning(f"Error enviando STOP (intento {attempt}), reintentando en 2min: {e}")
                    time.sleep(120)

            # Esperar a que quede detenida
            max_wait = 5 * 60
            interval = 30
            elapsed = 0
            while elapsed < max_wait:
                time.sleep(interval)
                elapsed += interval
                status, _ = self.get_instance_status(instance_id)
                if status == "stopped":
                    break
                logger.info(f"  Esperando stop... estado={status} ({elapsed}s)")

            if status != "stopped":
                return self._stop_error(
                    exec_log,
                    f"La instancia no llegó a 'stopped' en {max_wait}s — estado final: {status}"
                )

            # ── F6: Persistir estado ──────────────────────────────────────────
            state = self.load_state()
            state["last_stop"] = datetime.now().isoformat()
            state["snapshot_validated_at"] = datetime.now().isoformat()
            state["snapshot_results"] = snapshot_results
            self.save_state(state)

            exec_log["status"] = "success"
            exec_log["result"] = "stopped"
            exec_log["end_time"] = datetime.now().isoformat()
            self.save_execution_log(exec_log)

            logger.info(f"Instancia {instance_id} detenida exitosamente")
            return {
                "status": "success",
                "message": "Instancia detenida",
                "instance_id": instance_id,
                "snapshot_validation": snapshot_results,
            }

        except Exception as e:
            logger.exception(f"Error inesperado en stop_instance: {e}")
            return self._stop_error(exec_log, str(e))

    def _stop_error(self, exec_log: Dict, msg: str) -> Dict:
        logger.error(msg)
        exec_log["status"] = "error"
        exec_log["error"] = msg
        exec_log["end_time"] = datetime.now().isoformat()
        self.save_execution_log(exec_log)
        return {"status": "error", "message": msg}

    # ─── START ────────────────────────────────────────────────────────────────

    def smart_start(self) -> Dict:
        """
        Enciende la instancia existente o la recrea en otra zona con Schematics.

        Flujo:
          F1 — Cargar estado desde COS
          F2 — Intentar encender instancia existente
          F3 — Validar servidor operativo (running + data volume attached)
          F4 — Recrear con Schematics si F2 falló
          F5 — Post-start: actualizar estado COS + Secret CE
        """
        start_time = datetime.now()
        exec_log = {
            "action": "smart_start",
            "start_time": start_time.isoformat(),
            "region": self.region,
            "steps": [],
        }

        try:
            # ── F1: Estado ───────────────────────────────────────────────────
            state = self.load_state()
            instance_id  = state.get("active_instance_id")
            current_zone = state.get("zone")
            subnet_id    = state.get("subnet_id")
            prefix_id    = state.get("prefix_id")
            zone_failed  = None  # Zona que debe excluirse en el failover

            exec_log["steps"].append({"step": "load_state", "instance_id": instance_id,
                                      "zone": current_zone, "ts": datetime.now().isoformat()})

            # ── F2: Encender instancia existente ─────────────────────────────
            if instance_id:
                logger.info(f"Instancia existente: {instance_id} en zona {current_zone}")
                status, is_error = self.get_instance_status(instance_id)

                if status == "not_found":
                    logger.warning(f"Instancia {instance_id} no encontrada — limpiar estado")
                    state = {}
                    self.save_state(state)
                    instance_id = None

                elif status == "running":
                    logger.info("Instancia ya está running — validando operatividad")
                    return self._validate_and_finish_start(
                        exec_log, state, instance_id, current_zone, start_time
                    )

                elif status == "stopped":
                    logger.info(f"Instancia {instance_id} detenida — enviando START")
                    try:
                        self.vpc.create_instance_action(instance_id=instance_id, type="start")
                    except ApiException as e:
                        logger.error(f"Error enviando START: {e}")
                        is_error = True

                    if not is_error:
                        # Espera inicial de 2 min antes del primer check (GPU tarda en arrancar)
                        logger.info("Esperando 2 min antes del primer check de estado...")
                        time.sleep(120)
                        if self.wait_for_instance_running(instance_id):
                            return self._validate_and_finish_start(
                                exec_log, state, instance_id, current_zone, start_time
                            )
                        else:
                            # No llegó a running: registrar y continuar a recreación
                            status, is_error = self.get_instance_status(instance_id)
                            logger.warning(f"Instancia no llegó a running — estado final: {status}")

                if is_error or status not in ("running", "stopped"):
                    logger.warning(
                        f"Instancia {instance_id} en estado problemático ({status}) — "
                        f"iniciando limpieza y recreación"
                    )
                    zone_failed = current_zone
                    exec_log["steps"].append({
                        "step": "instance_failed",
                        "instance_id": instance_id,
                        "zone": current_zone,
                        "status": status,
                        "ts": datetime.now().isoformat(),
                    })

                    # Obtener snapshots frescos de la instancia antes de eliminarla
                    actual_boot, actual_data = self.get_instance_volumes(instance_id)
                    if actual_boot:
                        fresh_boot = self.get_latest_snapshot_for_volume(actual_boot)
                        if fresh_boot and fresh_boot.get("lifecycle_state") == "stable":
                            self.boot_snapshot_id = fresh_boot["id"]
                            logger.info(f"Usando snapshot boot actualizado: {self.boot_snapshot_id}")
                    if actual_data:
                        fresh_data = self.get_latest_snapshot_for_volume(actual_data)
                        if fresh_data and fresh_data.get("lifecycle_state") == "stable":
                            self.data_snapshot_id = fresh_data["id"]
                            logger.info(f"Usando snapshot data actualizado: {self.data_snapshot_id}")

                    # Limpiar recursos de la zona fallida
                    logger.info("Esperando 30s antes de limpiar recursos...")
                    time.sleep(30)
                    self.cleanup_zone_resources(current_zone, instance_id, subnet_id, prefix_id)

                    exec_log["steps"].append({
                        "step": "cleaned_zone",
                        "zone": current_zone,
                        "ts": datetime.now().isoformat(),
                    })

            # ── F4: Recrear con Schematics ────────────────────────────────────
            if not SCHEMATICS_AVAILABLE or not self.schematics:
                return self._start_error(
                    exec_log,
                    "Schematics no disponible y no hay instancia activa que encender"
                )

            # Validar snapshots antes de intentar
            boot_snap = self.boot_snapshot_id
            data_snap = self.data_snapshot_id

            if not boot_snap:
                return self._start_error(exec_log, "BOOT_VOLUME_SNAPSHOT_ID no configurado")
            if not data_snap:
                return self._start_error(exec_log, "DATA_VOLUME_SNAPSHOT_ID no configurado")

            # Verificar que los snapshots estén en estado stable
            for snap_id, label in [(boot_snap, "boot"), (data_snap, "data")]:
                try:
                    resp = self.vpc.get_snapshot(id=snap_id)
                    snap = resp.get_result()
                    state_snap = snap.get("lifecycle_state", "unknown")
                    if state_snap != "stable":
                        return self._start_error(
                            exec_log,
                            f"Snapshot {label} ({snap_id}) no está en estado 'stable': {state_snap}"
                        )
                    logger.info(f"Snapshot {label} verificado: {snap_id} estado={state_snap}")
                except ApiException as e:
                    return self._start_error(exec_log, f"Error verificando snapshot {label} ({snap_id}): {e}")

            # Determinar zonas a intentar (excluyendo la que falló)
            zones = sorted(self.config["zones"], key=lambda z: z["priority"])
            if zone_failed:
                zones = [z for z in zones if z["name"] != zone_failed]
                logger.info(f"Zonas disponibles (excluyendo {zone_failed}): {[z['name'] for z in zones]}")

            # Recuperar workspace IDs de Schematics por zona
            schematics_cfg = self.config.get("schematics", {})
            workspace_ids = schematics_cfg.get("workspace_ids", {})

            for zone_cfg in zones:
                zone_name = zone_cfg["name"]
                workspace_id = workspace_ids.get(zone_name)

                if not workspace_id:
                    logger.warning(f"No hay workspace_id configurado para zona {zone_name} — saltando")
                    continue

                logger.info(f"Intentando crear instancia en zona {zone_name} via Schematics...")
                exec_log["steps"].append({
                    "step": "try_schematics_zone",
                    "zone": zone_name,
                    "workspace_id": workspace_id,
                    "ts": datetime.now().isoformat(),
                })

                # Construir variables de zona
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                zone_variables = SchematicsClient.build_zone_variables(
                    zone_name=zone_name,
                    boot_snapshot_id=boot_snap,
                    data_snapshot_id=data_snap,
                    vpc_id=self.config["vpc"]["id"],
                    resource_group_id=self.config["resource_group_id"],
                    ssh_key_ids=self.config.get("ssh_key_ids", []),
                    security_group_ids=self.config.get("security_group_ids", []),
                    ibmcloud_api_key=self.api_key,
                    region=self.region,
                    vsi_profile=self.config.get("vsi_profile", "gx3-48x240x2l40s"),
                    vsi_ip=self.config.get("vsi_ip", "10.10.10.20"),
                    address_prefix_cidr=self.config.get("address_prefix_cidr", "10.10.10.16/28"),
                    subnet_cidr=self.config.get("subnet_cidr", "10.10.10.16/28"),
                    subnet_name=self.config.get("subnet_name", "subnet-app-tunal"),
                    instance_name=f"tunal-gpu-{zone_name}-{ts}",
                )

                apply_ok, outputs = self.schematics.apply_zone(workspace_id, zone_variables)

                if not apply_ok:
                    logger.warning(f"Schematics apply falló en zona {zone_name} — limpiando y probando siguiente")
                    self.schematics.destroy_zone(workspace_id)
                    exec_log["steps"].append({
                        "step": "zone_failed",
                        "zone": zone_name,
                        "reason": "schematics_apply_failed",
                        "ts": datetime.now().isoformat(),
                    })
                    continue

                # Apply exitoso — leer IDs de outputs
                new_instance_id = outputs.get("instance_id")
                new_subnet_id   = outputs.get("subnet_id")
                new_prefix_id   = outputs.get("address_prefix_id")
                new_boot_vol    = outputs.get("boot_volume_id")
                new_data_vol    = outputs.get("data_volume_id")

                if not new_instance_id:
                    logger.error(f"Schematics apply completó pero no retornó instance_id en zona {zone_name}")
                    self.schematics.destroy_zone(workspace_id)
                    continue

                # Esperar que quede running (el apply puede terminar con status=starting)
                logger.info(f"Schematics apply OK en {zone_name} — esperando que instancia quede running...")
                if not self.wait_for_instance_running(new_instance_id):
                    logger.warning(f"Instancia {new_instance_id} no llegó a running en {zone_name} — destruyendo")
                    self.schematics.destroy_zone(workspace_id)
                    exec_log["steps"].append({
                        "step": "zone_failed",
                        "zone": zone_name,
                        "reason": "instance_not_running",
                        "ts": datetime.now().isoformat(),
                    })
                    continue

                # ── F5: Post-start ────────────────────────────────────────────
                return self._validate_and_finish_start(
                    exec_log,
                    {
                        "active_instance_id": new_instance_id,
                        "instance_name": zone_variables["instance_name"],
                        "zone": zone_name,
                        "subnet_id": new_subnet_id,
                        "prefix_id": new_prefix_id,
                        "boot_volume_id": new_boot_vol,
                        "data_volume_id": new_data_vol,
                        "volume_ids": [new_boot_vol, new_data_vol],
                        "created_at": datetime.now().isoformat(),
                    },
                    new_instance_id,
                    zone_name,
                    start_time,
                    new_creation=True,
                )

            # Fallaron todas las zonas
            return self._start_error(exec_log, "No se pudo crear instancia en ninguna zona disponible")

        except Exception as e:
            logger.exception(f"Error inesperado en smart_start: {e}")
            return self._start_error(exec_log, str(e))

    def _validate_and_finish_start(
        self,
        exec_log: Dict,
        state: Dict,
        instance_id: str,
        zone: str,
        start_time: datetime,
        new_creation: bool = False,
    ) -> Dict:
        """
        Valida operatividad post-start (data volume attached) y persiste estado.
        Llamado tanto cuando se enciende la instancia existente como al crearla nueva.
        """
        # Esperar 5 minutos para que el boot GPU complete
        wait_s = 300
        logger.info(f"Esperando {wait_s}s para que el boot GPU complete...")
        time.sleep(wait_s)

        # Verificar data volume attached
        _, data_vol = self.get_instance_volumes(instance_id)
        if data_vol:
            att_status = self.get_data_volume_attachment_status(instance_id, data_vol)
            if att_status != "attached":
                logger.warning(
                    f"ADVERTENCIA: data volume {data_vol} no está en estado 'attached' "
                    f"(actual: {att_status}). El servidor puede no ver el disco de datos."
                )
            else:
                logger.info(f"Data volume {data_vol} atachado correctamente")
        else:
            logger.warning("No se detectó volumen de datos en la instancia")

        # Actualizar estado
        state["active_instance_id"] = instance_id
        state["zone"] = zone
        state["last_start"] = datetime.now().isoformat()
        if data_vol and not state.get("data_volume_id"):
            state["data_volume_id"] = data_vol

        self.save_state(state)

        # Log de ejecución
        action = "created_new" if new_creation else "started_existing"
        exec_log["status"] = "success"
        exec_log["result"] = action
        exec_log["instance_id"] = instance_id
        exec_log["zone"] = zone
        exec_log["end_time"] = datetime.now().isoformat()
        self.save_execution_log(exec_log)

        logger.info(f"START completado exitosamente: {action} instancia={instance_id} zona={zone}")
        return {
            "status": "success",
            "action": action,
            "instance_id": instance_id,
            "zone": zone,
        }

    def _start_error(self, exec_log: Dict, msg: str) -> Dict:
        logger.error(msg)
        exec_log["status"] = "error"
        exec_log["error"] = msg
        exec_log["end_time"] = datetime.now().isoformat()
        self.save_execution_log(exec_log)
        return {"status": "error", "message": msg}

    # ─── STATUS ───────────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Consulta el estado actual del sistema sin modificar nada."""
        state = self.load_state()
        instance_id = state.get("active_instance_id")

        if not instance_id:
            return {
                "status": "no_instance",
                "message": "No hay instancia registrada en el estado",
                "cos_available": bool(self.cos),
            }

        status, is_error = self.get_instance_status(instance_id)
        boot_vol, data_vol = self.get_instance_volumes(instance_id)

        return {
            "instance_id": instance_id,
            "instance_name": state.get("instance_name"),
            "zone": state.get("zone"),
            "status": status,
            "is_error": is_error,
            "boot_volume_id": boot_vol or state.get("boot_volume_id"),
            "data_volume_id": data_vol or state.get("data_volume_id"),
            "created_at": state.get("created_at"),
            "last_start": state.get("last_start"),
            "last_stop": state.get("last_stop"),
            "cos_available": bool(self.cos),
            "schematics_available": bool(self.schematics),
        }


# ─── Punto de entrada ─────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python vsi_advanced_manager_cos.py [start|stop|status] [--force]")
        sys.exit(1)

    action = sys.argv[1].lower()
    force  = "--force" in sys.argv

    try:
        manager = VSIManager()

        if action == "start":
            result = manager.smart_start()
        elif action == "stop":
            result = manager.stop_instance(force=force)
        elif action == "status":
            result = manager.get_status()
        else:
            print(f"Acción no reconocida: {action}. Válidas: start | stop | status")
            sys.exit(1)

        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("status") in ("success", "ok", "no_instance") else 1)

    except Exception as e:
        logger.exception(f"Error fatal: {e}")
        print(json.dumps({"status": "error", "message": str(e)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()

# Made with Bob
