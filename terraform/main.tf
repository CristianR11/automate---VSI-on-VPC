locals {
  # Nombre del address prefix: se usa el provisto o se genera uno basado en zona + timestamp
  address_prefix_name = var.address_prefix_name != "" ? var.address_prefix_name : "tunal-prefix-${var.zone_name}"

  # Nombre del boot volume
  boot_volume_name = "${var.instance_name}-boot"

  # Nombre del data volume
  data_volume_name = "${var.instance_name}-data"
}

# ─── Address Prefix ───────────────────────────────────────────────────────────
# Crea el prefijo de red en la zona destino. Necesario para que la subnet
# 10.10.10.16/28 sea enrutable dentro de la VPC en esta zona.
resource "ibm_is_vpc_address_prefix" "compute" {
  name = local.address_prefix_name
  zone = var.zone_name
  vpc  = var.vpc_id
  cidr = var.address_prefix_cidr
}

# ─── Subnet de Compute ────────────────────────────────────────────────────────
# Subnet dinámica: se crea en la zona donde se despliega el servidor.
# Depende del address prefix para garantizar el orden correcto de creación.
resource "ibm_is_subnet" "compute" {
  name            = var.subnet_name
  vpc             = var.vpc_id
  zone            = var.zone_name
  ipv4_cidr_block = var.subnet_cidr
  resource_group  = var.resource_group_id

  depends_on = [ibm_is_vpc_address_prefix.compute]
}

# ─── Instancia VSI GPU ────────────────────────────────────────────────────────
# La instancia se crea desde el snapshot del boot volume.
# El volumen de datos se incluye en el bloque volume_attachments para garantizar
# que IBM Cloud provisione AMBOS discos antes de arrancar el servidor, evitando
# la condición de carrera donde el OS arranca antes de que el data volume esté listo.
resource "ibm_is_instance" "vsi" {
  name              = var.instance_name
  profile           = var.vsi_profile
  vpc               = var.vpc_id
  zone              = var.zone_name
  resource_group    = var.resource_group_id

  # Boot volume desde snapshot
  boot_volume {
    name    = local.boot_volume_name
    profile = var.boot_volume_profile

    snapshot = var.boot_snapshot_id
  }

  # Interfaz de red primaria con IP fija
  primary_network_interface {
    name            = "eth0"
    subnet          = ibm_is_subnet.compute.id
    # Security groups como lista de IDs (sintaxis plana del provider IBM)
    security_groups = var.security_group_ids

    # IP fija 10.10.10.20 — consistente en todas las zonas para
    # que las rutas VPN on-premise no requieran cambios.
    primary_ip {
      address = var.vsi_ip
    }
  }

  # SSH keys autorizadas
  keys = var.ssh_key_ids

  depends_on = [ibm_is_subnet.compute]
}

# ─── Attachment del volumen de datos ─────────────────────────────────────────
# Se crea como recurso separado para poder hacer depends_on explícito.
# El volumen se crea desde el snapshot del data volume del día anterior.
resource "ibm_is_instance_volume_attachment" "data" {
  instance = ibm_is_instance.vsi.id
  name     = "${var.instance_name}-data-attach"

  profile  = var.data_volume_profile
  snapshot = var.data_snapshot_id

  # Preservar el volumen al destruir — los datos del cliente viven aquí.
  delete_volume_on_attachment_delete = var.delete_volumes_on_delete
  delete_volume_on_instance_delete   = var.delete_volumes_on_delete

  # Esperar a que la instancia esté disponible antes de atachar el volumen
  depends_on = [ibm_is_instance.vsi]
}
