#!/bin/bash
# Script de despliegue automatizado para sistema multi-zona
# Grupo Marna - El Tunal

set -e  # Salir si hay error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Función para imprimir mensajes
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_header() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}\n"
}

# Verificar que estamos en el directorio correcto
if [ ! -f "vsi_advanced_manager_cos.py" ]; then
    print_error "No se encuentra vsi_advanced_manager_cos.py. Ejecuta este script desde el directorio del proyecto."
    exit 1
fi

# Variables de configuración
# Usar variable de entorno si está definida, sino usar valor por defecto
PROJECT_NAME="${CE_PROJECT_NAME:-tunal-automation}"
NAMESPACE="${CE_PROJECT_NAME:-tunal-automation}"
IMAGE_NAME="vsi-manager"

# Nombres de recursos de Code Engine (usar variables de entorno si están definidas)
SECRET_NAME="${CE_SECRET_NAME:-tunal-credentials}"
CONFIGMAP_NAME="${CE_CONFIGMAP_NAME:-tunal-config}"
JOB_START_NAME="${CE_JOB_START_NAME:-tunal-smart-start}"
JOB_STOP_NAME="${CE_JOB_STOP_NAME:-tunal-stop}"
JOB_STATUS_NAME="${CE_JOB_STATUS_NAME:-tunal-status}"
CRON_START_NAME="${CE_CRON_START_NAME:-tunal-start-schedule}"
CRON_STOP_NAME="${CE_CRON_STOP_NAME:-tunal-stop-schedule}"

# Variables de recursos activos (actualizadas por el job START al finalizar)
# Se configuran manualmente la primera vez y el job las mantiene actualizadas
INSTANCE_ID="${INSTANCE_ID:-}"
BOOT_VOLUME_ID="${BOOT_VOLUME_ID:-}"
DATA_VOLUME_ID="${DATA_VOLUME_ID:-}"

# Container Registry: región para 'ibmcloud cr region-set' vs hostname
# Para Dallas: región="us-south", hostname="us.icr.io"
CR_REGION="${IBM_CR_REGION:-us-south}"
CR_HOSTNAME="${IBM_CR_HOSTNAME:-us.icr.io}"
CE_REGION="${IBM_CE_REGION:-us-east}"

print_header "Despliegue Sistema Multi-Zona - Grupo Marna El Tunal"

# Paso 1: Verificar IBM Cloud CLI
print_info "Verificando IBM Cloud CLI..."
if ! command -v ibmcloud &> /dev/null; then
    print_error "IBM Cloud CLI no está instalado"
    print_info "Instalar con: curl -fsSL https://clis.cloud.ibm.com/install/linux | sh"
    exit 1
fi
print_success "IBM Cloud CLI encontrado"

# Paso 2: Verificar plugins
print_info "Verificando plugins necesarios..."
PLUGINS_NEEDED=("vpc-infrastructure" "code-engine" "container-registry")
for plugin in "${PLUGINS_NEEDED[@]}"; do
    if ! ibmcloud plugin list | grep -q "$plugin"; then
        print_warning "Plugin $plugin no encontrado. Instalando..."
        ibmcloud plugin install "$plugin" -f
    else
        print_success "Plugin $plugin instalado"
    fi
done

# Paso 3: Verificar login
print_info "Verificando sesión de IBM Cloud..."
if ! ibmcloud target &> /dev/null; then
    print_error "No has iniciado sesión en IBM Cloud"
    print_info "Ejecuta: ibmcloud login --sso"
    exit 1
fi
print_success "Sesión activa"

# Paso 4: Verificar config.json
print_info "Verificando config.json..."
if [ ! -f "config.json" ]; then
    print_error "No se encuentra config.json"
    print_info "Copia config.json.example y configúralo con tus valores"
    exit 1
fi

# Validar que config.json tiene los campos necesarios
if ! grep -q "vpc" config.json || ! grep -q "zones" config.json; then
    print_error "config.json no tiene la estructura correcta"
    exit 1
fi
print_success "config.json válido"

# Paso 5: Verificar Docker o Podman
print_info "Verificando Docker/Podman..."
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
    print_success "Podman encontrado"
    
    # Verificar si Podman machine está corriendo (necesario en Mac)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        print_info "Verificando Podman machine (Mac)..."
        if ! podman machine list 2>/dev/null | grep -q "Currently running"; then
            print_warning "Podman machine no está corriendo. Iniciando..."
            
            # Verificar si existe una máquina
            if ! podman machine list 2>/dev/null | grep -q "podman-machine"; then
                print_info "Creando Podman machine..."
                podman machine init
            fi
            
            print_info "Iniciando Podman machine..."
            podman machine start
            
            # Esperar a que esté lista
            sleep 5
            print_success "Podman machine iniciada"
        else
            print_success "Podman machine está corriendo"
        fi
    fi
    
    # Verificar conexión a Podman
    if ! podman info &> /dev/null; then
        print_error "No se puede conectar a Podman"
        print_info "Intenta: podman machine start"
        exit 1
    fi
    print_success "Conexión a Podman verificada"
    
elif command -v docker &> /dev/null; then
    CONTAINER_CMD="docker"
    print_success "Docker encontrado"
    
    # Verificar que Docker está corriendo
    if ! docker info &> /dev/null; then
        print_error "Docker no está corriendo"
        print_info "Inicia Docker Desktop o el daemon de Docker"
        exit 1
    fi
    print_success "Docker está corriendo"
else
    print_error "Ni Docker ni Podman están instalados"
    print_info "Instala Podman: brew install podman (Mac) o dnf install podman (Linux)"
    exit 1
fi

# Paso 6: Configurar Container Registry
print_header "Configurando Container Registry"
print_info "Configurando región Container Registry: $CR_REGION"
ibmcloud cr region-set "$CR_REGION"

print_info "Verificando namespace..."
if ! ibmcloud cr namespace-list | grep -q "$NAMESPACE"; then
    print_warning "Namespace no existe. Creando..."
    ibmcloud cr namespace-add "$NAMESPACE"
    print_success "Namespace creado: $NAMESPACE"
else
    print_success "Namespace existe: $NAMESPACE"
fi

print_info "Iniciando sesión en Container Registry..."
ibmcloud cr login

# Paso 6.5: Detectar y configurar Cloud Object Storage
print_header "Configurando Cloud Object Storage"

# Obtener bucket name de config.json
BUCKET_NAME=$(jq -r '.cos.bucket_name // "tunal-automation"' config.json)
COS_REGION="us-east"

print_info "Bucket configurado en config.json: $BUCKET_NAME"

# Detectar instancia COS automáticamente si no está configurada
if [ -z "$COS_INSTANCE_ID" ]; then
    print_info "Detectando instancia de Cloud Object Storage..."
    
    # Buscar instancia COS en la cuenta
    COS_INSTANCE_ID=$(ibmcloud resource service-instances --service-name cloud-object-storage --output json 2>/dev/null | \
        jq -r '.[0].guid // empty' 2>/dev/null)
    
    if [ -n "$COS_INSTANCE_ID" ]; then
        COS_INSTANCE_NAME=$(ibmcloud resource service-instances --service-name cloud-object-storage --output json 2>/dev/null | \
            jq -r '.[0].name // "N/A"' 2>/dev/null)
        print_success "Instancia COS detectada: $COS_INSTANCE_NAME"
        print_info "Instance ID: $COS_INSTANCE_ID"
        
        # Configurar COS CLI con el CRN
        COS_CRN=$(ibmcloud resource service-instances --service-name cloud-object-storage --output json 2>/dev/null | \
            jq -r '.[0].crn // empty' 2>/dev/null)
        
        if [ -n "$COS_CRN" ]; then
            print_info "Configurando COS CLI..."
            ibmcloud cos config crn --crn "$COS_CRN" --force 2>/dev/null || true
        fi
    else
        print_warning "No se detectó instancia COS automáticamente"
        print_info "Puedes configurarla manualmente con: export COS_INSTANCE_ID=<tu-instance-id>"
    fi
fi

# Verificar/Crear bucket si tenemos instance ID
if [ -n "$COS_INSTANCE_ID" ]; then
    print_info "Verificando bucket COS: $BUCKET_NAME"
    
    # Verificar si el bucket existe (con timeout)
    if timeout 5 ibmcloud cos bucket-head --bucket "$BUCKET_NAME" --region "$COS_REGION" &> /dev/null; then
        print_success "Bucket COS existe: $BUCKET_NAME"
    else
        print_warning "No se pudo verificar bucket (puede no existir o timeout)"
        print_info "Intentando crear bucket..."
        
        # Intentar crear bucket con clase de almacenamiento Smart Tier
        if timeout 10 ibmcloud cos bucket-create \
            --bucket "$BUCKET_NAME" \
            --ibm-service-instance-id "$COS_INSTANCE_ID" \
            --region "$COS_REGION" \
            --class Smart 2>/dev/null; then
            print_success "Bucket creado: $BUCKET_NAME"
        else
            print_warning "No se pudo crear bucket (puede ya existir)"
            print_info "El sistema intentará usar el bucket configurado"
        fi
    fi
else
    print_warning "COS_INSTANCE_ID no disponible"
    print_info "El sistema funcionará sin persistencia de estado en COS"
    print_info "Para habilitar COS, configura: export COS_INSTANCE_ID=<tu-instance-id>"
fi
print_success "Sesión iniciada en Container Registry"

# Paso 7: Construir imagen Docker
print_header "Construyendo Imagen Docker"
IMAGE_TAG="$CR_HOSTNAME/$NAMESPACE/$IMAGE_NAME:latest"
print_info "Construyendo imagen: $IMAGE_TAG"
print_info "Registry hostname: $CR_HOSTNAME"

# Construir para arquitectura AMD64/x86_64 (requerida por Code Engine)
# Esto es importante en Mac M1/M2 que usan ARM64
print_info "Construyendo para plataforma linux/amd64..."
$CONTAINER_CMD build --platform linux/amd64 -t "$IMAGE_TAG" .
print_success "Imagen construida exitosamente"

print_info "Subiendo imagen a Container Registry..."
$CONTAINER_CMD push "$IMAGE_TAG"
print_success "Imagen subida exitosamente"

# Paso 8: Configurar Code Engine
print_header "Configurando Code Engine"

print_info "Verificando proyecto Code Engine..."
if ! ibmcloud ce project list | grep -q "$PROJECT_NAME"; then
    print_warning "Proyecto no existe. Creando..."
    ibmcloud ce project create --name "$PROJECT_NAME"
    print_success "Proyecto creado: $PROJECT_NAME"
else
    print_success "Proyecto existe: $PROJECT_NAME"
fi

print_info "Seleccionando proyecto..."
ibmcloud ce project select --name "$PROJECT_NAME"
print_success "Proyecto seleccionado"

# Paso 9: Crear/Actualizar secretos
print_header "Configurando Secretos"

# Verificar que tenemos API Key
if [ -z "$IBM_CLOUD_API_KEY" ]; then
    print_error "Variable IBM_CLOUD_API_KEY no está configurada"
    print_info "Exporta tu API Key: export IBM_CLOUD_API_KEY='tu-api-key'"
    exit 1
fi

# Verificar COS Instance ID (opcional pero recomendado)
if [ -z "$COS_INSTANCE_ID" ]; then
    print_warning "Variable COS_INSTANCE_ID no está configurada"
    print_info "El sistema funcionará sin COS (usando almacenamiento local)"
    print_info "Para habilitar COS: export COS_INSTANCE_ID='tu-cos-instance-id'"
fi

print_info "Creando/actualizando secreto de credenciales..."

# Construir los literales comunes del secret
SECRET_LITERALS=(
    --from-literal IBM_CLOUD_API_KEY="$IBM_CLOUD_API_KEY"
    --from-literal IBM_CLOUD_REGION="$CE_REGION"
    --from-literal BOOT_VOLUME_SNAPSHOT_ID="${BOOT_VOLUME_SNAPSHOT_ID:-}"
    --from-literal DATA_VOLUME_SNAPSHOT_ID="${DATA_VOLUME_SNAPSHOT_ID:-}"
    # IDs de recursos activos (job START los actualiza tras cada ejecución exitosa)
    --from-literal INSTANCE_ID="$INSTANCE_ID"
    --from-literal BOOT_VOLUME_ID="$BOOT_VOLUME_ID"
    --from-literal DATA_VOLUME_ID="$DATA_VOLUME_ID"
    --from-literal BACKUP_POLICY_ID="${BACKUP_POLICY_ID:-r014-dab7a8b6-4343-4f22-873c-1111d88099d8}"
)

if [ -n "$COS_INSTANCE_ID" ]; then
    SECRET_LITERALS+=(
        --from-literal COS_API_KEY="${COS_API_KEY:-}"
        --from-literal COS_INSTANCE_ID="$COS_INSTANCE_ID"
        --from-literal COS_ENDPOINT="https://s3.$CE_REGION.cloud-object-storage.appdomain.cloud"
        --from-literal COS_BUCKET_NAME="${COS_BUCKET_NAME:-tunal-automation}"
    )
fi

if ibmcloud ce secret get --name $SECRET_NAME &> /dev/null; then
    ibmcloud ce secret update --name $SECRET_NAME "${SECRET_LITERALS[@]}"
    print_success "Secreto actualizado"
else
    ibmcloud ce secret create --name $SECRET_NAME "${SECRET_LITERALS[@]}"
    print_success "Secreto creado"
fi

# Paso 10: Crear/Actualizar registry access
print_info "Configurando acceso a Container Registry..."
if ibmcloud ce registry get --name registry-access &> /dev/null; then
    print_warning "Registry access ya existe, omitiendo..."
else
    ibmcloud ce registry create --name registry-access \
        --server "$CR_HOSTNAME" \
        --username iamapikey \
        --password "$IBM_CLOUD_API_KEY"
    print_success "Registry access creado"
fi

# Paso 11: Crear/Actualizar configmap
print_info "Creando/actualizando configmap con config.json..."
if ibmcloud ce configmap get --name $CONFIGMAP_NAME &> /dev/null; then
    ibmcloud ce configmap update --name $CONFIGMAP_NAME \
        --from-file config.json
    print_success "ConfigMap actualizado"
else
    ibmcloud ce configmap create --name $CONFIGMAP_NAME \
        --from-file config.json
    print_success "ConfigMap creado"
fi

# Paso 12: Crear/Actualizar Jobs
print_header "Configurando Jobs"

# Job Smart Start
# maxexecutiontime=1800 (30 min) para cubrir: verificar estado + esperar Schematics apply
# en hasta 3 zonas + esperar boot GPU (20 min por zona)
print_info "Configurando job: $JOB_START_NAME..."
if ibmcloud ce job get --name $JOB_START_NAME &> /dev/null; then
    ibmcloud ce job update --name $JOB_START_NAME \
        --image "$IMAGE_TAG" \
        --maxexecutiontime 1800
    print_success "Job $JOB_START_NAME actualizado"
else
    ibmcloud ce job create --name $JOB_START_NAME \
        --image "$IMAGE_TAG" \
        --registry-secret registry-access \
        --env-from-secret $SECRET_NAME \
        --env-from-configmap $CONFIGMAP_NAME \
        --cpu 0.5 \
        --memory 1G \
        --maxexecutiontime 1800 \
        --retrylimit 0 \
        --cmd python \
        --arg vsi_advanced_manager_cos.py \
        --arg start
    print_success "Job $JOB_START_NAME creado"
fi

# Job Stop
# maxexecutiontime=2700 (45 min) para cubrir: validar estado + esperar snapshots pending
# (hasta 3 reintentos de 5 min = 15 min) + ejecutar stop
print_info "Configurando job: $JOB_STOP_NAME..."
if ibmcloud ce job get --name $JOB_STOP_NAME &> /dev/null; then
    ibmcloud ce job update --name $JOB_STOP_NAME \
        --image "$IMAGE_TAG" \
        --maxexecutiontime 2700
    print_success "Job $JOB_STOP_NAME actualizado"
else
    ibmcloud ce job create --name $JOB_STOP_NAME \
        --image "$IMAGE_TAG" \
        --registry-secret registry-access \
        --env-from-secret $SECRET_NAME \
        --env-from-configmap $CONFIGMAP_NAME \
        --cpu 0.25 \
        --memory 0.5G \
        --maxexecutiontime 2700 \
        --retrylimit 0 \
        --cmd python \
        --arg vsi_advanced_manager_cos.py \
        --arg stop
    print_success "Job $JOB_STOP_NAME creado"
fi

# Job Status (consulta sin modificar estado)
print_info "Configurando job: $JOB_STATUS_NAME..."
if ibmcloud ce job get --name $JOB_STATUS_NAME &> /dev/null; then
    ibmcloud ce job update --name $JOB_STATUS_NAME \
        --image "$IMAGE_TAG"
    print_success "Job $JOB_STATUS_NAME actualizado"
else
    ibmcloud ce job create --name $JOB_STATUS_NAME \
        --image "$IMAGE_TAG" \
        --registry-secret registry-access \
        --env-from-secret $SECRET_NAME \
        --env-from-configmap $CONFIGMAP_NAME \
        --cpu 0.25 \
        --memory 0.5G \
        --maxexecutiontime 300 \
        --retrylimit 0 \
        --cmd python \
        --arg vsi_advanced_manager_cos.py \
        --arg status
    print_success "Job $JOB_STATUS_NAME creado"
fi

# Paso 13: Configurar Cron Subscriptions
print_header "Configurando Programación (Cron)"

# Cron Start - 7:00 AM Lunes a Viernes
print_info "Configurando programación de encendido (7:00 AM L-V)..."
if ibmcloud ce subscription cron get --name $CRON_START_NAME &> /dev/null; then
    print_warning "Subscription de start ya existe, omitiendo..."
else
    ibmcloud ce subscription cron create --name $CRON_START_NAME \
        --destination-type job \
        --destination $JOB_START_NAME \
        --schedule "0 7 * * 1-5" \
        --time-zone "America/Bogota" \
        --data '{"action":"start"}'
    print_success "Programación de encendido configurada"
fi

# Cron Stop - 7:00 PM Lunes a Viernes
print_info "Configurando programación de apagado (7:00 PM L-V)..."
if ibmcloud ce subscription cron get --name $JOB_STOP_NAME-schedule &> /dev/null; then
    print_warning "Subscription de stop ya existe, omitiendo..."
else
    ibmcloud ce subscription cron create --name $JOB_STOP_NAME-schedule \
        --destination-type job \
        --destination $JOB_STOP_NAME \
        --schedule "0 19 * * 1-5" \
        --time-zone "America/Bogota" \
        --data '{"action":"stop"}'
    print_success "Programación de apagado configurada"
fi

# Paso 14: Prueba
print_header "Ejecutando Prueba"

print_info "¿Deseas ejecutar una prueba del job de status? (s/n)"
read -r response
if [[ "$response" =~ ^[Ss]$ ]]; then
    print_info "Ejecutando job de status..."
    JOBRUN_NAME="test-status-$(date +%s)"
    ibmcloud ce jobrun submit --job $JOB_STATUS_NAME --name "$JOBRUN_NAME"
    
    print_info "Esperando resultado..."
    sleep 10
    
    print_info "Logs del job:"
    ibmcloud ce jobrun logs --name "$JOBRUN_NAME" || true
fi

# Resumen final
print_header "Despliegue Completado"

print_success "Sistema multi-zona desplegado exitosamente!"
echo ""
print_info "Recursos creados:"
echo "  • Proyecto Code Engine: $PROJECT_NAME"
echo "  • Imagen Docker: $IMAGE_TAG"
echo "  • Job Smart Start: $JOB_START_NAME"
echo "  • Job Stop: $JOB_STOP_NAME"
echo "  • Job Status: $JOB_STATUS_NAME"
echo "  • Programación Start: 7:00 AM (L-V)"
echo "  • Programación Stop: 7:00 PM (L-V)"
echo ""
print_info "Comandos útiles:"
echo "  • Ver jobs: ibmcloud ce job list"
echo "  • Ver ejecuciones: ibmcloud ce jobrun list"
echo "  • Ver logs: ibmcloud ce jobrun logs --name <jobrun-name>"
echo "  • Ejecutar manualmente: ibmcloud ce jobrun submit --job $JOB_START_NAME"
echo "  • Ver programación: ibmcloud ce subscription cron list"
echo ""
print_success "¡Todo listo! El sistema comenzará a operar según la programación configurada."

# Made with Bob
