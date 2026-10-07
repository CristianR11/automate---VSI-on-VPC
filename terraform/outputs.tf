output "instance_id" {
  description = "ID de la instancia VSI creada"
  value       = ibm_is_instance.vsi.id
}

output "instance_name" {
  description = "Nombre de la instancia VSI"
  value       = ibm_is_instance.vsi.name
}

output "instance_status" {
  description = "Estado de la instancia al finalizar el apply"
  value       = ibm_is_instance.vsi.status
}

output "instance_ip" {
  description = "IP privada asignada a la instancia"
  value       = ibm_is_instance.vsi.primary_network_interface[0].primary_ip[0].address
}

output "subnet_id" {
  description = "ID de la subnet compute creada"
  value       = ibm_is_subnet.compute.id
}

output "address_prefix_id" {
  description = "ID del address prefix creado en la zona"
  value       = ibm_is_vpc_address_prefix.compute.id
}

output "boot_volume_id" {
  description = "ID del volumen boot de la instancia"
  value       = ibm_is_instance.vsi.boot_volume[0].volume_id
}

output "data_volume_id" {
  description = "ID del volumen de datos atachado"
  # En el provider IBM v2.x el attachment no expone volume_id directamente;
  # se obtiene listando los attachments de la instancia post-apply.
  value       = ibm_is_instance_volume_attachment.data.id
}

output "zone" {
  description = "Zona de disponibilidad donde se desplegó la instancia"
  value       = var.zone_name
}
