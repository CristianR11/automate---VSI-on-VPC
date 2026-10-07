# ─── Autenticación ───────────────────────────────────────────────────────────
variable "ibmcloud_api_key" {
  description = "IBM Cloud API Key para autenticación"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "Región de IBM Cloud donde se despliegan los recursos"
  type        = string
  default     = "us-east"
}

# ─── Zona de disponibilidad ───────────────────────────────────────────────────
variable "zone_name" {
  description = "Zona de disponibilidad donde se crea la instancia (us-east-1 | us-east-2 | us-east-3)"
  type        = string

  validation {
    condition     = contains(["us-east-1", "us-east-2", "us-east-3"], var.zone_name)
    error_message = "zone_name debe ser us-east-1, us-east-2 o us-east-3."
  }
}

# ─── Snapshots ────────────────────────────────────────────────────────────────
variable "boot_snapshot_id" {
  description = "ID del snapshot del volumen boot desde el que se crea la instancia"
  type        = string
}

variable "data_snapshot_id" {
  description = "ID del snapshot del volumen de datos que se atacha a la instancia"
  type        = string
}

# ─── Red ──────────────────────────────────────────────────────────────────────
variable "vpc_id" {
  description = "ID de la VPC donde se crean los recursos de red y la instancia"
  type        = string
}

variable "address_prefix_cidr" {
  description = "CIDR del address prefix que se crea en la zona (compute subnet)"
  type        = string
  default     = "10.10.10.16/28"
}

variable "subnet_cidr" {
  description = "CIDR de la subnet de compute (debe estar dentro de address_prefix_cidr)"
  type        = string
  default     = "10.10.10.16/28"
}

variable "vsi_ip" {
  description = "IP privada fija que se asigna a la instancia"
  type        = string
  default     = "10.10.10.20"
}

# ─── Instancia ────────────────────────────────────────────────────────────────
variable "instance_name" {
  description = "Nombre de la instancia VSI"
  type        = string
}

variable "vsi_profile" {
  description = "Perfil de la instancia (hardware)"
  type        = string
  default     = "gx3-48x240x2l40s"
}

variable "resource_group_id" {
  description = "ID del resource group donde se crean todos los recursos"
  type        = string
}

variable "ssh_key_ids" {
  description = "Lista de IDs de SSH keys que se configuran en la instancia"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Lista de IDs de security groups que se asocian a la interfaz de red"
  type        = list(string)
}

# ─── Nombres de recursos de red ───────────────────────────────────────────────
variable "address_prefix_name" {
  description = "Nombre del address prefix (se genera automáticamente si está vacío)"
  type        = string
  default     = ""
}

variable "subnet_name" {
  description = "Nombre de la subnet compute"
  type        = string
  default     = "subnet-app-tunal"
}

# ─── Volúmenes ────────────────────────────────────────────────────────────────
variable "boot_volume_profile" {
  description = "Perfil del volumen boot"
  type        = string
  default     = "general-purpose"
}

variable "data_volume_profile" {
  description = "Perfil del volumen de datos"
  type        = string
  default     = "general-purpose"
}

variable "delete_volumes_on_delete" {
  description = "Si true, elimina los volúmenes al destruir la instancia. False conserva los volúmenes para backups."
  type        = bool
  default     = false
}
