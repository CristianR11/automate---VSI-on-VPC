# 🚀 Guía de Despliegue Paso a Paso

## ✅ Pre-requisitos Completados

- [x] Sesión iniciada en IBM Cloud CLI
- [x] Región configurada (us-east)
- [x] Grupo de recursos seleccionado

## 📋 Paso 1: Verificar Configuración Actual

```bash
# Verificar sesión y configuración
ibmcloud target

# Deberías ver:
# - Account: Tu cuenta
# - Resource group: Tu grupo de recursos
# - Region: us-east
```

## 📋 Paso 2: Obtener IDs de Recursos Necesarios

### 2.1 Obtener VPC ID

```bash
# Listar VPCs
ibmcloud is vpcs

# Copiar el ID de tu VPC
# Formato: r006-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### 2.2 Obtener Security Group IDs

```bash
# Listar security groups
ibmcloud is security-groups

# Copiar el ID del security group que usarás
```

### 2.3 Obtener SSH Key IDs

```bash
# Listar SSH keys
ibmcloud is keys

# Copiar el ID de tu SSH key
```

### 2.4 Obtener Resource Group ID

```bash
# Listar resource groups
ibmcloud resource groups --output json | jq '.[] | {name: .name, id: .id}'

# Copiar el ID de tu resource group
```

### 2.5 Obtener Boot Volume ID (si ya tienes una instancia)

```bash
# Listar instancias
ibmcloud is instances

# Ver detalles de tu instancia
ibmcloud is instance <INSTANCE_ID> --output json | jq '.boot_volume_attachment.volume.id'

# Copiar el boot_volume_id
```

## 📋 Paso 3: Crear Instancia de Cloud Object Storage

```bash
# Crear instancia de COS
ibmcloud resource service-instance-create tunal-cos \
  cloud-object-storage \
  standard \
  global

# Esperar a que se cree (puede tomar 1-2 minutos)
echo "Esperando creación de COS..."
sleep 30

# Obtener COS Instance ID
export COS_INSTANCE_ID=$(ibmcloud resource service-instance tunal-cos --output json | jq -r '.[0].guid')

echo "COS Instance ID: $COS_INSTANCE_ID"
```

## 📋 Paso 4: Crear API Key

```bash
# Crear API Key para la automatización
ibmcloud iam api-key-create tunal-automation-key \
  -d "API Key para automatización VSI Tunal" \
  --file ~/tunal-api-key.json

# Exportar API Key
export IBM_CLOUD_API_KEY=$(cat ~/tunal-api-key.json | jq -r '.apikey')

echo "API Key configurada"
```

## 📋 Paso 5: Configurar config.json

```bash
# Editar config.json con tus valores
nano config.json
```

Reemplazar estos valores:

```json
{
  "vpc": {
    "id": "TU_VPC_ID_AQUI",
    "name": "tunal-vpc"
  },
  "vsi_profile": "gx3-48x240x2l40s",
  "resource_group_id": "TU_RESOURCE_GROUP_ID",
  "ssh_key_ids": ["TU_SSH_KEY_ID"],
  "security_group_ids": ["TU_SECURITY_GROUP_ID"],
  "backup_policy_id": "TU_BACKUP_POLICY_ID_O_DEJALO_VACIO"
}
```

## 📋 Paso 6: Crear Estado Inicial (si ya tienes una instancia)

Si ya tienes una instancia corriendo:

```bash
# Crear vsi_state.json con datos de tu instancia actual
cat > vsi_state.json << EOF
{
  "active_instance_id": "TU_INSTANCE_ID",
  "instance_name": "nombre-de-tu-instancia",
  "zone": "us-east-1",
  "boot_volume_id": "TU_BOOT_VOLUME_ID",
  "volume_ids": ["TU_BOOT_VOLUME_ID"],
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%S.%6N)",
  "last_start": "$(date -u +%Y-%m-%dT%H:%M:%S.%6N)",
  "last_stop": ""
}
EOF
```

Si NO tienes instancia, crear estado vacío:

```bash
echo '{}' > vsi_state.json
```

## 📋 Paso 7: Exportar Variables de Entorno

```bash
# Exportar todas las variables necesarias
export IBM_CLOUD_REGION="us-east"
export COS_INSTANCE_ID="<tu-cos-instance-id-del-paso-3>"
export IBM_CLOUD_API_KEY="<tu-api-key-del-paso-4>"

# Verificar que están configuradas
echo "Region: $IBM_CLOUD_REGION"
echo "COS Instance ID: $COS_INSTANCE_ID"
echo "API Key configurada: $([ -n "$IBM_CLOUD_API_KEY" ] && echo 'SI' || echo 'NO')"
```

## 📋 Paso 8: Ejecutar Despliegue

```bash
# Hacer el script ejecutable
chmod +x deploy_advanced.sh

# Ejecutar despliegue
./deploy_advanced.sh
```

El script automáticamente:
1. ✅ Verifica herramientas y plugins
2. ✅ Construye imagen Docker
3. ✅ Sube a Container Registry
4. ✅ Crea proyecto Code Engine
5. ✅ Configura secretos (incluyendo COS)
6. ✅ Crea jobs (start, stop, status)
7. ✅ Programa cron subscriptions (7 AM / 7 PM)

## 📋 Paso 9: Verificar Despliegue

```bash
# Verificar que el proyecto existe
ibmcloud ce project list | grep tunal-automation

# Seleccionar proyecto
ibmcloud ce project select --name tunal-automation

# Verificar jobs creados
ibmcloud ce job list

# Deberías ver:
# - tunal-smart-start
# - tunal-stop
# - tunal-status

# Verificar cron subscriptions
ibmcloud ce subscription cron list

# Deberías ver:
# - tunal-start-schedule (7:00 AM)
# - tunal-stop-schedule (7:00 PM)
```

## 📋 Paso 10: Prueba Manual

```bash
# Ejecutar job de status manualmente
ibmcloud ce jobrun submit --job tunal-status --name test-status-$(date +%s)

# Esperar unos segundos
sleep 10

# Ver logs
LAST_RUN=$(ibmcloud ce jobrun list --job tunal-status --output json | jq -r '.items[0].metadata.name')
ibmcloud ce jobrun logs --name $LAST_RUN
```

## 🎉 ¡Despliegue Completado!

Tu sistema está ahora operativo y:
- ✅ Se encenderá automáticamente a las 7:00 AM (L-V)
- ✅ Se apagará automáticamente a las 7:00 PM (L-V)
- ✅ Guardará estado en Cloud Object Storage
- ✅ Registrará logs de cada ejecución
- ✅ Implementará failover multi-zona automático

## 📊 Monitoreo Diario

```bash
# Ver últimas ejecuciones
ibmcloud ce jobrun list --job tunal-smart-start | head -5
ibmcloud ce jobrun list --job tunal-stop | head -5

# Ver logs de última ejecución de start
LAST_START=$(ibmcloud ce jobrun list --job tunal-smart-start --output json | jq -r '.items[0].metadata.name')
ibmcloud ce jobrun logs --name $LAST_START

# Ver logs de última ejecución de stop
LAST_STOP=$(ibmcloud ce jobrun list --job tunal-stop --output json | jq -r '.items[0].metadata.name')
ibmcloud ce jobrun logs --name $LAST_STOP
```

## 🔧 Comandos Útiles

```bash
# Ejecutar start manualmente
ibmcloud ce jobrun submit --job tunal-smart-start --name manual-start

# Ejecutar stop manualmente
ibmcloud ce jobrun submit --job tunal-stop --name manual-stop

# Ver estado actual
ibmcloud ce jobrun submit --job tunal-status --name check-status

# Cambiar horario de encendido (ejemplo: 6:00 AM)
ibmcloud ce subscription cron update --name tunal-start-schedule \
  --schedule "0 6 * * 1-5"

# Cambiar horario de apagado (ejemplo: 8:00 PM)
ibmcloud ce subscription cron update --name tunal-stop-schedule \
  --schedule "0 20 * * 1-5"
```

## 🚨 Troubleshooting

### Problema: Error al construir imagen Docker

```bash
# Verificar que Docker está corriendo
docker ps

# Si no está corriendo, iniciarlo
# En Mac: Abrir Docker Desktop
# En Linux: sudo systemctl start docker
```

### Problema: Error al subir imagen a Container Registry

```bash
# Verificar login en Container Registry
ibmcloud cr login

# Verificar namespace
ibmcloud cr namespace-list

# Si no existe, crearlo
ibmcloud cr namespace-add tunal-automation
```

### Problema: Job falla al ejecutar

```bash
# Ver logs detallados del job
ibmcloud ce jobrun logs --name <jobrun-name>

# Verificar secretos
ibmcloud ce secret get --name tunal-credentials

# Verificar configmap
ibmcloud ce configmap get --name tunal-config
```

## 📞 Siguiente Paso

Después del despliegue exitoso:
1. Monitorear la primera ejecución automática (mañana a las 7:00 AM)
2. Verificar logs en COS
3. Ajustar horarios si es necesario
4. Configurar alertas (opcional)

---

**¡Listo para producción!** 🚀