# IBM Cloud VPC GPU Instance Manager — Automatización Start/Stop

Sistema de gestión automatizada de VSI GPU para Grupo Marna (El Tunal) en IBM Cloud VPC con failover multi-zona vía IBM Schematics, validación estricta de snapshots pre-apagado y optimización de costos.

[![IBM Cloud](https://img.shields.io/badge/IBM%20Cloud-VPC-blue)](https://cloud.ibm.com/vpc-ext)
[![Python](https://img.shields.io/badge/Python-3.11-green)](https://www.python.org/)
[![Terraform](https://img.shields.io/badge/Terraform-1.5+-purple)](https://www.terraform.io/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────────┐
│                 IBM Cloud Code Engine (us-east)                      │
│                                                                       │
│   Cron 7:00 AM ──► Job START ──┐                                     │
│   Cron 7:00 PM ──► Job STOP   │                                     │
└───────────────────────────────┼────────────────────────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                   │
              ▼                 ▼                   ▼
    ┌──────────────┐  ┌──────────────────┐  ┌────────────────┐
    │  VPC us-east │  │  IBM Schematics  │  │  Cloud Object  │
    │              │  │  (failover IaC)  │  │  Storage (COS) │
    │  GPU VSI     │  │  - workspace z1  │  │  - state/      │
    │  10.10.10.20 │  │  - workspace z2  │  │  - logs/       │
    │              │  │  - workspace z3  │  └────────────────┘
    └──────────────┘  └──────────────────┘
```

### Red

| Subnet | CIDR | Zona | Propósito |
|---|---|---|---|
| VPN Gateway (PROTEGIDA) | `10.10.10.0/28` | us-east-1 (fija) | VPN Site-to-Site — NUNCA se borra |
| Compute (dinámica) | `10.10.10.16/28` | cualquier zona | Servidor GPU — se recrea en failover |

**VSI IP fija**: `10.10.10.20` — consistente en todas las zonas para no romper rutas VPN.

### Mejora futura propuesta: Hub + Spoke con Transit Gateway

```
VPC HUB (vpc-eltunal)          VPC SPOKE (nueva)
├── Subnet VPN 10.10.10.0/28   └── Subnet Compute 10.10.10.16/28
│   └── VPN Gateway                  └── GPU VSI 10.10.10.20
└── Transit Gateway attachment ─────► Transit Gateway ◄─── attachment
```

Al separar las VPCs, las rutas se propagan automáticamente por TGW y el failover de zona no requiere actualizar rutas VPN on-premise.

---

## Flujos de operación

### Job START (7:00 AM, lunes a viernes)

1. **Cargar estado** desde COS (`state/vsi_state.json`)
2. **Si hay instancia registrada:**
   - Consultar estado en VPC API
   - Si `stopped` → enviar START → esperar `running` (max 20 min)
   - Si `running` → validar data volume attached → registrar éxito
   - Si `failed` / timeout → obtener snapshots frescos → limpiar zona → **failover**
3. **Failover (IBM Schematics):**
   - Verificar que snapshots boot y data estén en estado `stable`
   - Para cada zona disponible (excluyendo la que falló):
     - Ejecutar `terraform apply` en el workspace Schematics de la zona
     - Esperar `running` en VPC API (max 20 min)
     - Si falla → `terraform destroy` + siguiente zona
4. **Post-start:** guardar estado en COS con `instance_id`, `zone`, `boot_volume_id`, `data_volume_id`

### Job STOP (7:00 PM, lunes a viernes)

1. **Validar instancia** en VPC API (usando `INSTANCE_ID` del Secret)
2. **Validar volúmenes** — verificar que boot y data coincidan con `BOOT_VOLUME_ID` / `DATA_VOLUME_ID`
3. **Validar snapshots (BLOQUEO DURO):**
   - El snapshot más reciente de cada volumen debe ser del **mismo día** (zona America/Bogota)
   - El snapshot debe estar en estado `stable`
   - Si está `pending` → esperar hasta 15 min (3 reintentos de 5 min)
   - Si tiene más de 60 min de antigüedad → **advertencia** (no bloquea)
   - Usa `--force` para omitir esta validación en emergencias
4. **Ejecutar stop** → esperar `stopped` (max 5 min)
5. **Persistir estado** en COS

---

## Estructura del proyecto

```
.
├── vsi_advanced_manager_cos.py    # Orquestador principal (start / stop / status)
├── cos_storage.py                  # Cliente IBM Cloud Object Storage
├── schematics_client.py            # Cliente IBM Schematics (orquesta Terraform por zona)
├── terraform/
│   ├── main.tf                     # Recursos: address_prefix, subnet, instance, data_volume
│   ├── variables.tf                # Variables de la plantilla (zona, snapshots, VPC, etc.)
│   ├── outputs.tf                  # Outputs: instance_id, subnet_id, volume_ids
│   └── versions.tf                 # Provider IBM, versión Terraform requerida
├── deploy_advanced.sh              # Script de despliegue a Code Engine
├── setup_snapshots.sh              # Script interactivo para actualizar snapshot IDs
├── cleanup_resources.sh            # Limpieza manual de recursos compute
├── config.json                     # Configuración del entorno
├── Dockerfile                      # Imagen del contenedor
├── requirements.txt                # Dependencias Python
└── GUIA_DESPLIEGUE_PASO_A_PASO.md # Guía de despliegue
```

---

## Configuración

### Prerequisitos

- IBM Cloud CLI con plugins: `vpc-infrastructure`, `code-engine`, `container-registry`
- Docker o Podman
- Python 3.11+
- 3 workspaces de IBM Schematics creados (uno por zona), apuntando al directorio `terraform/`

### 1. Variables de entorno necesarias

```bash
export IBM_CLOUD_API_KEY="tu-api-key"
export COS_INSTANCE_ID="tu-cos-instance-id"          # opcional pero recomendado
export BOOT_VOLUME_SNAPSHOT_ID="r014-xxxx"            # snapshot boot para recreación
export DATA_VOLUME_SNAPSHOT_ID="r014-xxxx"            # snapshot data para recreación

# IDs de recursos activos (para el job STOP — actualizar la primera vez)
export INSTANCE_ID="0767_xxxx"
export BOOT_VOLUME_ID="r014-xxxx"
export DATA_VOLUME_ID="r014-xxxx"
export BACKUP_POLICY_ID="r014-dab7a8b6-4343-4f22-873c-1111d88099d8"
```

### 2. config.json — campos clave

```json
{
  "schematics": {
    "workspace_ids": {
      "us-east-1": "ID_WORKSPACE_ZONA_1",
      "us-east-2": "ID_WORKSPACE_ZONA_2",
      "us-east-3": "ID_WORKSPACE_ZONA_3"
    }
  },
  "snapshot_max_age_minutes": 60,
  "max_start_wait_minutes": 20
}
```

### 3. Crear workspaces Schematics

```bash
# Crear un workspace por zona apuntando al directorio terraform/
# desde la consola de IBM Cloud → Schematics → Workspaces → Create
# o vía CLI:
ibmcloud schematics workspace new \
  --name tunal-zone-us-east-1 \
  --location us-east \
  --template-type terraform_v1.5
```

Actualizar los IDs en `config.json` → sección `schematics.workspace_ids`.

### 4. Desplegar

```bash
chmod +x deploy_advanced.sh
./deploy_advanced.sh
```

---

## Monitoreo

```bash
# Ver últimas ejecuciones
ibmcloud ce jobrun list --job tunal-smart-start
ibmcloud ce jobrun list --job tunal-stop

# Ver logs de una ejecución
ibmcloud ce jobrun logs --name <jobrun-name>

# Ejecutar manualmente
ibmcloud ce jobrun submit --job tunal-smart-start --name manual-start
ibmcloud ce jobrun submit --job tunal-stop --name manual-stop
ibmcloud ce jobrun submit --job tunal-status --name check-status

# Forzar apagado sin validar snapshots (emergencia)
ibmcloud ce jobrun submit --job tunal-stop --name emergency-stop \
  --env OVERRIDE_CMD="python vsi_advanced_manager_cos.py stop --force"
```

---

## Comportamiento ante fallos

| Evento | Respuesta del sistema |
|---|---|
| Instancia no arranca en zona X | Limpia zona X → crea en siguiente zona via Schematics |
| Falta capacidad GPU en zona | Schematics destroy → siguiente zona |
| Snapshot no existe hoy | Job STOP se bloquea — no apaga el servidor |
| Snapshot en estado `pending` | Espera hasta 15 min — si sigue pending, bloquea |
| Snapshot en estado `failed` | Bloqueo duro — requiere `--force` |
| COS no disponible | Fallback a `vsi_state.json` local |
| Todas las zonas fallan | Alerta crítica — NO reintentar automáticamente |
| Data volume no atachado al boot | Advertencia en log — el servidor arranca igual |

---

## Seguridad

- API Keys en Code Engine Secrets (nunca en código fuente ni `config.json`)
- `config.json` está en `.gitignore`
- Bucket COS privado con acceso restringido
- VPN Site-to-Site para conectividad on-premise

---

## Costos estimados

- **Ahorro**: ~50% vs operación 24/7
- **Horas activas**: 12 h/día × 5 días (7 AM – 7 PM, L–V)
- **Code Engine**: pay-per-use (segundos de ejecución)
- **Schematics**: gratuito (cobro solo por recursos creados)

---

## Versiones

- **v2.0** (Junio 2026): Integración Schematics, validación de snapshots estricta, variables explícitas en jobs
- **v1.0** (Junio 2026): Versión inicial con failover por Python SDK

**Estado**: Production Ready ✅

---

**Licencia**: Apache License 2.0 — ver [LICENSE](LICENSE)
