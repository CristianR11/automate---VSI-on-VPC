#!/usr/bin/env python3
"""
IBM Cloud Schematics Client
Orquesta workspaces de Schematics para crear/destruir infraestructura por zona.
El job Python invoca este cliente cuando necesita recrear el servidor en una zona.
"""

import os
import time
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core import ApiException

logger = logging.getLogger(__name__)

# Tiempo máximo esperando un job de Schematics (apply / destroy)
SCHEMATICS_JOB_TIMEOUT_SECONDS = 1200   # 20 minutos
SCHEMATICS_POLL_INTERVAL_SECONDS = 30


class SchematicsClient:
    """
    Wrapper sobre la API REST de IBM Schematics.
    Gestiona el ciclo de vida de workspaces Terraform por zona:
      - apply  → crea la infraestructura en la zona
      - destroy → destruye la infraestructura de la zona
      - outputs → lee los IDs de los recursos creados
    """

    BASE_URL = "https://schematics.cloud.ibm.com"

    def __init__(self):
        self.api_key = os.environ.get("IBM_CLOUD_API_KEY")
        if not self.api_key:
            raise ValueError("IBM_CLOUD_API_KEY no está configurada")

        self.region = os.environ.get("IBM_CLOUD_REGION", "us-east")

        # Obtener token IAM
        self._iam_token: Optional[str] = None
        self._token_expiry: float = 0.0

        logger.info("SchematicsClient inicializado")

    # ─── Autenticación ────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Devuelve el token IAM vigente, renovándolo si expiró."""
        now = time.time()
        if self._iam_token and now < self._token_expiry - 60:
            return self._iam_token

        authenticator = IAMAuthenticator(self.api_key)
        token_manager = authenticator.token_manager
        token_manager.request_token()
        self._iam_token = token_manager.get_token()
        # Los tokens IAM duran 1 hora; renovar a los 50 minutos
        self._token_expiry = now + 3000
        return self._iam_token

    def _headers(self) -> Dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.BASE_URL}{path}"
        resp = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        if not resp.ok:
            logger.error(f"Schematics API error {resp.status_code}: {resp.text[:400]}")
            resp.raise_for_status()
        return resp

    # ─── Workspaces ───────────────────────────────────────────────────────────

    def get_workspace(self, workspace_id: str) -> Dict:
        """Retorna los detalles de un workspace."""
        resp = self._request("GET", f"/v1/workspaces/{workspace_id}")
        return resp.json()

    def list_workspaces(self) -> List[Dict]:
        """Lista todos los workspaces de la cuenta."""
        resp = self._request("GET", "/v1/workspaces")
        return resp.json().get("workspaces", [])

    def find_workspace_by_name(self, name: str) -> Optional[Dict]:
        """Busca un workspace por nombre exacto."""
        for ws in self.list_workspaces():
            if ws.get("name") == name:
                return ws
        return None

    def update_workspace_variables(self, workspace_id: str, variables: Dict[str, str]) -> bool:
        """
        Actualiza variables de un workspace existente.
        variables: dict {nombre_variable: valor}
        """
        # Primero leer las variables actuales para mantener las que no cambian
        ws = self.get_workspace(workspace_id)
        template_id = ws["template_data"][0]["id"]

        # Construir payload de variables
        var_list = []
        existing_vars = {v["name"]: v for v in ws["template_data"][0].get("values_metadata", [])}

        for name, value in variables.items():
            entry = {"name": name, "value": str(value)}
            if name in existing_vars:
                entry["type"] = existing_vars[name].get("type", "string")
            entry["secure"] = name.lower() in ("ibmcloud_api_key", "api_key")
            var_list.append(entry)

        payload = {"variablestore": var_list}
        self._request(
            "PUT",
            f"/v1/workspaces/{workspace_id}/template_data/{template_id}/values",
            json=payload,
        )
        logger.info(f"Variables actualizadas en workspace {workspace_id}")
        return True

    # ─── Jobs Schematics ──────────────────────────────────────────────────────

    def _submit_job(self, workspace_id: str, action: str) -> str:
        """
        Envía un job de Schematics (plan / apply / destroy).
        Retorna el activity_id del job.
        """
        payload = {"action": action}
        if action == "apply":
            resp = self._request("PUT", f"/v1/workspaces/{workspace_id}/apply", json=payload)
        elif action == "destroy":
            resp = self._request("PUT", f"/v1/workspaces/{workspace_id}/destroy", json=payload)
        elif action == "plan":
            resp = self._request("POST", f"/v1/workspaces/{workspace_id}/plan")
        else:
            raise ValueError(f"Acción no soportada: {action}")

        activity_id = resp.json().get("activityid", "")
        logger.info(f"Job Schematics {action} enviado. activity_id={activity_id}")
        return activity_id

    def _wait_for_job(self, workspace_id: str, activity_id: str,
                      timeout: int = SCHEMATICS_JOB_TIMEOUT_SECONDS) -> Tuple[bool, str]:
        """
        Espera a que un job de Schematics complete.

        Retorna:
            (success: bool, status: str)
        """
        start = time.time()
        logger.info(f"Esperando job Schematics {activity_id} (max {timeout}s)...")

        while time.time() - start < timeout:
            resp = self._request(
                "GET",
                f"/v1/workspaces/{workspace_id}/actions/{activity_id}",
            )
            data = resp.json()
            status = data.get("status", "")
            message = data.get("message", "")

            logger.info(f"  Job {activity_id}: status={status} — {message}")

            # Estados terminales de Schematics
            if status in ("COMPLETED", "FAILED", "CANCELLED", "STOPPED"):
                success = status == "COMPLETED"
                if not success:
                    logger.error(f"Job Schematics terminó con status={status}: {message}")
                return success, status

            time.sleep(SCHEMATICS_POLL_INTERVAL_SECONDS)

        logger.error(f"Timeout esperando job Schematics {activity_id} después de {timeout}s")
        return False, "TIMEOUT"

    # ─── Operaciones principales ──────────────────────────────────────────────

    def apply_zone(
        self,
        workspace_id: str,
        zone_variables: Dict[str, str],
    ) -> Tuple[bool, Dict]:
        """
        Actualiza las variables de zona en el workspace y ejecuta apply.

        Args:
            workspace_id:   ID del workspace Schematics de la zona
            zone_variables: Variables a inyectar (zone_name, boot_snapshot_id, etc.)

        Returns:
            (success, outputs_dict)
            outputs_dict contiene: instance_id, subnet_id, address_prefix_id,
                                   boot_volume_id, data_volume_id, zone
        """
        logger.info(f"Iniciando Schematics apply en workspace {workspace_id}")
        logger.info(f"Variables de zona: {json.dumps({k: v for k, v in zone_variables.items() if 'key' not in k.lower()}, indent=2)}")

        try:
            # 1. Actualizar variables
            self.update_workspace_variables(workspace_id, zone_variables)

            # 2. Ejecutar plan
            logger.info("Ejecutando terraform plan...")
            plan_id = self._submit_job(workspace_id, "plan")
            plan_ok, plan_status = self._wait_for_job(workspace_id, plan_id, timeout=300)
            if not plan_ok:
                logger.error(f"Plan falló con status={plan_status}")
                return False, {}

            # 3. Ejecutar apply
            logger.info("Ejecutando terraform apply...")
            apply_id = self._submit_job(workspace_id, "apply")
            apply_ok, apply_status = self._wait_for_job(workspace_id, apply_id)

            if not apply_ok:
                logger.error(f"Apply falló con status={apply_status}")
                return False, {}

            # 4. Leer outputs
            outputs = self.get_outputs(workspace_id)
            logger.info(f"Apply exitoso. Outputs: {json.dumps(outputs, indent=2)}")
            return True, outputs

        except Exception as e:
            logger.error(f"Error en apply_zone para workspace {workspace_id}: {e}")
            return False, {}

    def destroy_zone(self, workspace_id: str) -> bool:
        """
        Ejecuta terraform destroy en el workspace de la zona.
        Limpia todos los recursos creados por el apply anterior.

        Returns:
            True si el destroy completó exitosamente.
        """
        logger.warning(f"Iniciando Schematics destroy en workspace {workspace_id}")

        try:
            destroy_id = self._submit_job(workspace_id, "destroy")
            success, status = self._wait_for_job(workspace_id, destroy_id)

            if success:
                logger.info(f"Destroy completado exitosamente en workspace {workspace_id}")
            else:
                logger.error(f"Destroy falló con status={status}. Puede requerir limpieza manual.")

            return success

        except Exception as e:
            logger.error(f"Error en destroy_zone para workspace {workspace_id}: {e}")
            return False

    def get_outputs(self, workspace_id: str) -> Dict:
        """
        Lee los outputs de Terraform del workspace.

        Retorna dict con:
            instance_id, instance_name, instance_status, instance_ip,
            subnet_id, address_prefix_id, boot_volume_id, data_volume_id, zone
        """
        try:
            resp = self._request("GET", f"/v1/workspaces/{workspace_id}/output_values")
            raw = resp.json()

            # La API devuelve una lista de templates con sus outputs
            outputs = {}
            for template in raw:
                for output_key, output_val in template.get("output_values", {}).items():
                    # output_val puede ser {"value": "...", "type": "string"}
                    if isinstance(output_val, dict):
                        outputs[output_key] = output_val.get("value", "")
                    else:
                        outputs[output_key] = output_val

            return outputs

        except Exception as e:
            logger.error(f"Error leyendo outputs del workspace {workspace_id}: {e}")
            return {}

    def get_workspace_status(self, workspace_id: str) -> str:
        """Retorna el estado actual del workspace (ACTIVE, INACTIVE, FAILED, etc.)."""
        try:
            ws = self.get_workspace(workspace_id)
            return ws.get("status", "UNKNOWN")
        except Exception:
            return "UNKNOWN"

    # ─── Helpers de configuración ─────────────────────────────────────────────

    @staticmethod
    def build_zone_variables(
        zone_name: str,
        boot_snapshot_id: str,
        data_snapshot_id: str,
        vpc_id: str,
        resource_group_id: str,
        ssh_key_ids: List[str],
        security_group_ids: List[str],
        ibmcloud_api_key: str,
        region: str = "us-east",
        vsi_profile: str = "gx3-48x240x2l40s",
        vsi_ip: str = "10.10.10.20",
        address_prefix_cidr: str = "10.10.10.16/28",
        subnet_cidr: str = "10.10.10.16/28",
        subnet_name: str = "subnet-app-tunal",
        instance_name: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Construye el diccionario de variables para inyectar al workspace.
        Centraliza la conversión de listas a formato que Terraform acepta.
        """
        if not instance_name:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            instance_name = f"tunal-gpu-{zone_name}-{ts}"

        # Terraform espera listas como JSON string para variables de tipo list
        return {
            "ibmcloud_api_key":    ibmcloud_api_key,
            "region":              region,
            "zone_name":           zone_name,
            "boot_snapshot_id":    boot_snapshot_id,
            "data_snapshot_id":    data_snapshot_id,
            "vpc_id":              vpc_id,
            "resource_group_id":   resource_group_id,
            "vsi_profile":         vsi_profile,
            "vsi_ip":              vsi_ip,
            "address_prefix_cidr": address_prefix_cidr,
            "subnet_cidr":         subnet_cidr,
            "subnet_name":         subnet_name,
            "instance_name":       instance_name,
            "ssh_key_ids":         json.dumps(ssh_key_ids),
            "security_group_ids":  json.dumps(security_group_ids),
        }


# ─── Función de conveniencia para uso en tests ───────────────────────────────

def get_schematics_client() -> SchematicsClient:
    return SchematicsClient()

# Made with Bob
