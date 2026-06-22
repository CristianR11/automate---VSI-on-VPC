#!/bin/bash
# Script para limpiar recursos huérfanos del VPC
# IMPORTANTE: NO toca la subnet 10.10.10.0/28 (VPN Gateway)

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Limpieza de Recursos VPC - El Tunal${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}\n"

# Obtener VPC ID
VPC_ID=$(ibmcloud is vpcs --output json | jq -r '.[] | select(.name | contains("tunal")) | .id')

if [ -z "$VPC_ID" ]; then
    echo -e "${RED}❌ No se encontró VPC con nombre 'tunal'${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} VPC encontrado: $VPC_ID\n"

# IMPORTANTE: Subnet del VPN Gateway que NO debe eliminarse
VPN_SUBNET_CIDR="10.10.10.0/28"
echo -e "${YELLOW}⚠️  PROTEGIDO: Subnet VPN Gateway ${VPN_SUBNET_CIDR}${NC}\n"

# Listar subnets con el prefix de compute (NO VPN)
COMPUTE_SUBNET_CIDR="10.10.10.16/28"
echo -e "${YELLOW}Buscando subnets de compute con CIDR ${COMPUTE_SUBNET_CIDR}...${NC}"
SUBNETS=$(ibmcloud is subnets --output json | jq -r ".[] | select(.ipv4_cidr_block == \"${COMPUTE_SUBNET_CIDR}\") | .id")

if [ -n "$SUBNETS" ]; then
    echo -e "${YELLOW}Subnets de compute encontradas:${NC}"
    for subnet_id in $SUBNETS; do
        subnet_info=$(ibmcloud is subnet $subnet_id --output json)
        subnet_name=$(echo $subnet_info | jq -r '.name')
        subnet_zone=$(echo $subnet_info | jq -r '.zone.name')
        subnet_cidr=$(echo $subnet_info | jq -r '.ipv4_cidr_block')
        echo -e "  - ${subnet_name} (${subnet_id})"
        echo -e "    CIDR: ${subnet_cidr}, Zona: ${subnet_zone}"
        
        # Verificar si tiene interfaces de red
        interfaces=$(echo $subnet_info | jq -r '.network_interfaces | length')
        if [ "$interfaces" -gt 0 ]; then
            echo -e "    ${RED}⚠️  Tiene $interfaces interfaces de red activas${NC}"
        fi
    done
    echo ""
else
    echo -e "${GREEN}✓${NC} No se encontraron subnets de compute para limpiar\n"
fi

# Listar address prefixes con el CIDR de compute
echo -e "${YELLOW}Buscando address prefixes de compute con CIDR ${COMPUTE_SUBNET_CIDR}...${NC}"
PREFIXES=$(ibmcloud is vpc-address-prefixes $VPC_ID --output json | jq -r ".[] | select(.cidr == \"${COMPUTE_SUBNET_CIDR}\") | .id")

if [ -n "$PREFIXES" ]; then
    echo -e "${YELLOW}Address prefixes de compute encontrados:${NC}"
    for prefix_id in $PREFIXES; do
        prefix_info=$(ibmcloud is vpc-address-prefix $VPC_ID $prefix_id --output json)
        prefix_name=$(echo $prefix_info | jq -r '.name')
        prefix_zone=$(echo $prefix_info | jq -r '.zone.name')
        prefix_cidr=$(echo $prefix_info | jq -r '.cidr')
        has_subnets=$(echo $prefix_info | jq -r '.has_subnets')
        echo -e "  - ${prefix_name} (${prefix_id})"
        echo -e "    CIDR: ${prefix_cidr}, Zona: ${prefix_zone}"
        if [ "$has_subnets" == "true" ]; then
            echo -e "    ${RED}⚠️  Tiene subnets asociadas${NC}"
        fi
    done
    echo ""
else
    echo -e "${GREEN}✓${NC} No se encontraron address prefixes de compute para limpiar\n"
fi

# Verificar si hay algo que limpiar
if [ -z "$SUBNETS" ] && [ -z "$PREFIXES" ]; then
    echo -e "${GREEN}✅ No hay recursos de compute para limpiar${NC}"
    echo -e "${BLUE}El ambiente está limpio y listo para desplegar${NC}\n"
    exit 0
fi

# Preguntar si desea eliminar
echo -e "${RED}═══════════════════════════════════════════════════${NC}"
echo -e "${RED}  ADVERTENCIA${NC}"
echo -e "${RED}═══════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}Se eliminarán SOLO los recursos de compute (${COMPUTE_SUBNET_CIDR})${NC}"
echo -e "${GREEN}La subnet del VPN Gateway (${VPN_SUBNET_CIDR}) NO será tocada${NC}\n"
echo -e "${YELLOW}¿Desea continuar con la eliminación? (y/n)${NC}"
read -r response

if [ "$response" != "y" ]; then
    echo -e "${BLUE}Operación cancelada${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Iniciando limpieza...${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}\n"

# Eliminar subnets de compute primero
if [ -n "$SUBNETS" ]; then
    for subnet_id in $SUBNETS; do
        subnet_name=$(ibmcloud is subnet $subnet_id --output json | jq -r '.name')
        subnet_cidr=$(ibmcloud is subnet $subnet_id --output json | jq -r '.ipv4_cidr_block')
        
        # Doble verificación: NO eliminar subnet del VPN
        if [ "$subnet_cidr" == "$VPN_SUBNET_CIDR" ]; then
            echo -e "${RED}⚠️  PROTEGIDO: Saltando subnet VPN Gateway ${subnet_name}${NC}\n"
            continue
        fi
        
        echo -e "${YELLOW}Eliminando subnet de compute ${subnet_name} (${subnet_cidr})...${NC}"
        
        if ibmcloud is subnet-delete $subnet_id --force 2>&1; then
            echo -e "${GREEN}✓${NC} Subnet eliminada\n"
        else
            echo -e "${RED}❌ Error al eliminar subnet${NC}\n"
        fi
        
        # Esperar un poco
        sleep 2
    done
fi

# Eliminar address prefixes de compute
if [ -n "$PREFIXES" ]; then
    for prefix_id in $PREFIXES; do
        prefix_name=$(ibmcloud is vpc-address-prefix $VPC_ID $prefix_id --output json | jq -r '.name')
        prefix_cidr=$(ibmcloud is vpc-address-prefix $VPC_ID $prefix_id --output json | jq -r '.cidr')
        
        echo -e "${YELLOW}Eliminando address prefix de compute ${prefix_name} (${prefix_cidr})...${NC}"
        
        if ibmcloud is vpc-address-prefix-delete $VPC_ID $prefix_id --force 2>&1; then
            echo -e "${GREEN}✓${NC} Address prefix eliminado\n"
        else
            echo -e "${RED}❌ Error al eliminar address prefix${NC}\n"
        fi
        
        # Esperar un poco
        sleep 2
    done
fi

echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Limpieza completada${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}Estado final:${NC}"
echo -e "${BLUE}Address prefixes en VPC:${NC}"
ibmcloud is vpc-address-prefixes $VPC_ID

echo -e "\n${BLUE}Subnets en VPC:${NC}"
ibmcloud is subnets --output json | jq -r '.[] | select(.vpc.id == "'$VPC_ID'") | "\(.name) - \(.ipv4_cidr_block) - \(.zone.name)"'

echo ""

# Made with Bob
