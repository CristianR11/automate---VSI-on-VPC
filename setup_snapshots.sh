#!/bin/bash
# Script interactivo para configurar snapshots de volúmenes
# Recopila IDs de snapshots y los configura en Code Engine

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_error() { echo -e "${RED}❌ $1${NC}"; }
print_header() {
    echo -e "\n${CYAN}═══════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}\n"
}

print_header "Configuración de Snapshots - Grupo Marna El Tunal"

# Verificar que estamos logueados
if ! ibmcloud target &> /dev/null; then
    print_error "No estás logueado en IBM Cloud"
    print_info "Ejecuta: ibmcloud login --sso"
    exit 1
fi

print_success "Sesión de IBM Cloud activa"
echo ""
ibmcloud target
echo ""

# Variables
PROJECT_NAME="tunal-automation"

print_header "Paso 1: Listar Snapshots Disponibles"

print_info "Obteniendo lista de snapshots..."
echo ""

# Listar snapshots con formato legible
ibmcloud is snapshots --output json | jq -r '
.[] | 
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📸 Snapshot: \(.name)
   ID: \(.id)
   Volumen: \(.source_volume.name // "N/A")
   Tamaño: \(.size // 0) GB
   Creado: \(.created_at)
   Estado: \(.lifecycle_state)
"
'

echo ""
print_warning "Identifica los snapshots de:"
echo "  1. 📀 Volumen de BOOT (sistema operativo)"
echo "  2. 💾 Volumen de DATOS (almacenamiento adicional)"
echo ""

print_header "Paso 2: Configurar Snapshot de Boot Volume"

read -p "Ingresa el ID del snapshot del BOOT volume: " BOOT_SNAPSHOT_ID

if [ -z "$BOOT_SNAPSHOT_ID" ]; then
    print_error "El ID del boot snapshot es obligatorio"
    exit 1
fi

# Verificar que el snapshot existe
print_info "Verificando snapshot de boot..."
if ibmcloud is snapshot "$BOOT_SNAPSHOT_ID" &> /dev/null; then
    BOOT_SNAPSHOT_NAME=$(ibmcloud is snapshot "$BOOT_SNAPSHOT_ID" --output json | jq -r '.name')
    BOOT_SNAPSHOT_SIZE=$(ibmcloud is snapshot "$BOOT_SNAPSHOT_ID" --output json | jq -r '.size')
    print_success "Snapshot encontrado: $BOOT_SNAPSHOT_NAME ($BOOT_SNAPSHOT_SIZE GB)"
else
    print_error "No se pudo encontrar el snapshot con ID: $BOOT_SNAPSHOT_ID"
    exit 1
fi

print_header "Paso 3: Configurar Snapshot de Data Volume"

read -p "Ingresa el ID del snapshot del DATA volume: " DATA_SNAPSHOT_ID

if [ -z "$DATA_SNAPSHOT_ID" ]; then
    print_error "El ID del data snapshot es obligatorio"
    exit 1
fi

# Verificar que el snapshot existe
print_info "Verificando snapshot de datos..."
if ibmcloud is snapshot "$DATA_SNAPSHOT_ID" &> /dev/null; then
    DATA_SNAPSHOT_NAME=$(ibmcloud is snapshot "$DATA_SNAPSHOT_ID" --output json | jq -r '.name')
    DATA_SNAPSHOT_SIZE=$(ibmcloud is snapshot "$DATA_SNAPSHOT_ID" --output json | jq -r '.size')
    print_success "Snapshot encontrado: $DATA_SNAPSHOT_NAME ($DATA_SNAPSHOT_SIZE GB)"
else
    print_error "No se pudo encontrar el snapshot con ID: $DATA_SNAPSHOT_ID"
    exit 1
fi

print_header "Paso 4: Resumen de Configuración"

echo -e "${CYAN}Snapshots configurados:${NC}"
echo ""
echo -e "  📀 ${GREEN}Boot Volume:${NC}"
echo -e "     Nombre: $BOOT_SNAPSHOT_NAME"
echo -e "     ID: $BOOT_SNAPSHOT_ID"
echo -e "     Tamaño: $BOOT_SNAPSHOT_SIZE GB"
echo ""
echo -e "  💾 ${GREEN}Data Volume:${NC}"
echo -e "     Nombre: $DATA_SNAPSHOT_NAME"
echo -e "     ID: $DATA_SNAPSHOT_ID"
echo -e "     Tamaño: $DATA_SNAPSHOT_SIZE GB"
echo ""

read -p "¿Es correcta esta configuración? (s/n): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Ss]$ ]]; then
    print_warning "Configuración cancelada"
    exit 0
fi

print_header "Paso 5: Actualizar Code Engine Secret"

print_info "Seleccionando proyecto Code Engine..."
if ! ibmcloud ce project select --name "$PROJECT_NAME" &> /dev/null; then
    print_error "No se pudo seleccionar el proyecto: $PROJECT_NAME"
    print_info "Asegúrate de que el proyecto existe"
    exit 1
fi
print_success "Proyecto seleccionado: $PROJECT_NAME"

# Verificar si necesitamos API Key y COS Instance ID
if [ -z "$IBM_CLOUD_API_KEY" ]; then
    print_warning "Variable IBM_CLOUD_API_KEY no está configurada"
    read -sp "Ingresa tu IBM Cloud API Key: " IBM_CLOUD_API_KEY
    echo ""
fi

if [ -z "$COS_INSTANCE_ID" ]; then
    print_warning "Variable COS_INSTANCE_ID no está configurada"
    read -p "Ingresa tu COS Instance ID (o presiona Enter para omitir): " COS_INSTANCE_ID
fi

print_info "Actualizando secret con snapshots..."

# Eliminar secret existente si existe
if ibmcloud ce secret get --name tunal-credentials &> /dev/null; then
    print_info "Eliminando secret existente..."
    ibmcloud ce secret delete --name tunal-credentials -f
fi

# Crear nuevo secret con todos los valores
if [ -n "$COS_INSTANCE_ID" ]; then
    print_info "Creando secret con COS habilitado..."
    ibmcloud ce secret create --name tunal-credentials \
        --from-literal IBM_CLOUD_API_KEY="$IBM_CLOUD_API_KEY" \
        --from-literal IBM_CLOUD_REGION="us-east" \
        --from-literal COS_INSTANCE_ID="$COS_INSTANCE_ID" \
        --from-literal COS_ENDPOINT="https://s3.us-east.cloud-object-storage.appdomain.cloud" \
        --from-literal COS_BUCKET_NAME="tunal-automation" \
        --from-literal BOOT_VOLUME_SNAPSHOT_ID="$BOOT_SNAPSHOT_ID" \
        --from-literal DATA_VOLUME_SNAPSHOT_ID="$DATA_SNAPSHOT_ID"
else
    print_info "Creando secret sin COS..."
    ibmcloud ce secret create --name tunal-credentials \
        --from-literal IBM_CLOUD_API_KEY="$IBM_CLOUD_API_KEY" \
        --from-literal IBM_CLOUD_REGION="us-east" \
        --from-literal BOOT_VOLUME_SNAPSHOT_ID="$BOOT_SNAPSHOT_ID" \
        --from-literal DATA_VOLUME_SNAPSHOT_ID="$DATA_SNAPSHOT_ID"
fi

print_success "Secret actualizado con IDs de snapshots"

print_header "Paso 6: Verificar Configuración"

print_info "Verificando secret..."
ibmcloud ce secret get --name tunal-credentials

print_header "✅ Configuración Completada"

echo -e "${GREEN}Los snapshots han sido configurados correctamente:${NC}"
echo ""
echo -e "  📀 Boot Snapshot: ${CYAN}$BOOT_SNAPSHOT_ID${NC}"
echo -e "  💾 Data Snapshot: ${CYAN}$DATA_SNAPSHOT_ID${NC}"
echo ""
echo -e "${YELLOW}Próximos pasos:${NC}"
echo ""
echo "  1. Probar creación de VSI:"
echo -e "     ${CYAN}ibmcloud ce jobrun submit --job tunal-smart-start --wait${NC}"
echo ""
echo "  2. Ver logs:"
echo -e "     ${CYAN}ibmcloud ce jobrun logs --jobrun <jobrun-name>${NC}"
echo ""
echo "  3. Verificar estado:"
echo -e "     ${CYAN}ibmcloud ce jobrun submit --job tunal-status --wait${NC}"
echo ""

print_success "¡Sistema listo para crear instancias desde snapshots!"

# Made with Bob
