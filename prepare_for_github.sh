#!/bin/bash
# Script para preparar el proyecto para GitHub
# Elimina archivos innecesarios y consolida documentación

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Preparando Proyecto para GitHub${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}\n"

# Crear carpeta temporal para archivos a eliminar
TEMP_DIR=".github_cleanup"
mkdir -p "$TEMP_DIR"

echo -e "${YELLOW}Moviendo archivos innecesarios...${NC}\n"

# Archivos de documentación redundante/temporal
DOCS_TO_REMOVE=(
    "CAMBIOS_CONFIGURACION.md"
    "CAMBIOS_FINALES.md"
    "CONFIGURACION_INICIAL.md"
    "CORRECCIONES_FINALES_V2.md"
    "ESTRUCTURA_PROYECTO.md"
    "SOLUCION_PODMAN.md"
)

# Scripts de limpieza temporal
SCRIPTS_TO_REMOVE=(
    "cleanup_project.sh"
    "setup_config.sh"
)

# Mover documentación redundante
for file in "${DOCS_TO_REMOVE[@]}"; do
    if [ -f "$file" ]; then
        mv "$file" "$TEMP_DIR/"
        echo -e "${GREEN}✓${NC} Movido: $file"
    fi
done

# Mover scripts temporales
for file in "${SCRIPTS_TO_REMOVE[@]}"; do
    if [ -f "$file" ]; then
        mv "$file" "$TEMP_DIR/"
        echo -e "${GREEN}✓${NC} Movido: $file"
    fi
done

# Eliminar carpeta de archivos antiguos
if [ -d "archive_old_versions" ]; then
    rm -rf "archive_old_versions"
    echo -e "${GREEN}✓${NC} Eliminada: archive_old_versions/"
fi

echo -e "\n${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Limpieza completada${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}Archivos del proyecto para GitHub:${NC}\n"

echo -e "${BLUE}📄 Scripts Python:${NC}"
ls -1 *.py 2>/dev/null || echo "  (ninguno)"

echo -e "\n${BLUE}🔧 Scripts de Despliegue:${NC}"
ls -1 *.sh 2>/dev/null | grep -v prepare_for_github || echo "  (ninguno)"

echo -e "\n${BLUE}⚙️  Configuración:${NC}"
ls -1 *.json 2>/dev/null || echo "  (ninguno)"

echo -e "\n${BLUE}🐳 Docker:${NC}"
ls -1 Dockerfile requirements.txt .gitignore 2>/dev/null || echo "  (ninguno)"

echo -e "\n${BLUE}📚 Documentación:${NC}"
ls -1 *.md 2>/dev/null | grep -v prepare_for_github || echo "  (ninguno)"

echo -e "\n${YELLOW}Archivos movidos a: ${TEMP_DIR}/${NC}"
echo -e "${YELLOW}Puedes eliminar esta carpeta si todo está correcto${NC}\n"

echo -e "${GREEN}¡Proyecto listo para GitHub!${NC}\n"

# Made with Bob
