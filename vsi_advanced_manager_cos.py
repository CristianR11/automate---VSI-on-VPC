#!/usr/bin/env python3
"""
IBM Cloud VPC Advanced VSI Manager with Multi-Zone Failover and COS Integration
Gestiona VSI con capacidad de recreación en múltiples zonas usando snapshots
Integra Cloud Object Storage para persistencia de estado y logs
"""

import os
import sys
import json
import time
import io
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from ibm_vpc import VpcV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core import ApiException
import logging

# Importar módulo de COS
try:
    from cos_storage import COSStorage
    COS_AVAILABLE = True
except ImportError:
    COS_AVAILABLE = False
    logging.warning("cos_storage no disponible, usando almacenamiento local")

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LogCapture(io.StringIO):
    """Captura logs para guardarlos en COS"""
    def __init__(self):
        super().__init__()
        self.logs = []
    
    def write(self, msg):
        self.logs.append(msg)
        return super().write(msg)
    
    def get_logs(self):
        return ''.join(self.logs)


class VSIAdvancedManagerCOS:
    """Clase avanzada para gestionar VSI con failover multi-zona y COS"""
    
    def __init__(self, config_file: str = 'config.json', use_cos: bool = True):
        """Inicializa el gestor con configuración desde archivo"""
        self.api_key = os.environ.get('IBM_CLOUD_API_KEY')
        self.region = os.environ.get('IBM_CLOUD_REGION', 'us-east')
        self.use_cos = use_cos and COS_AVAILABLE
        
        if not self.api_key:
            raise ValueError("IBM_CLOUD_API_KEY no está configurada")
        
        # Obtener IDs de snapshots desde variables de entorno
        self.boot_snapshot_id = os.environ.get('BOOT_VOLUME_SNAPSHOT_ID')
        self.data_snapshot_id = os.environ.get('DATA_VOLUME_SNAPSHOT_ID')
        
        logger.info(f"Boot Snapshot ID: {self.boot_snapshot_id or 'No configurado'}")
        logger.info(f"Data Snapshot ID: {self.data_snapshot_id or 'No configurado'}")
        
        # Cargar configuración
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        # Configurar autenticación VPC
        authenticator = IAMAuthenticator(self.api_key)
        self.vpc_service = VpcV1(authenticator=authenticator)
        self.vpc_service.set_service_url(f'https://{self.region}.iaas.cloud.ibm.com/v1')
        
        # Inicializar COS si está disponible
        self.cos = None
        if self.use_cos:
            try:
                self.cos = COSStorage()
                logger.info("COS inicializado correctamente")
            except Exception as e:
                logger.warning(f"No se pudo inicializar COS: {e}. Usando almacenamiento local")
                self.use_cos = False
        
        # Archivo de estado local (fallback)
        self.state_file = self.config.get('state_file', 'vsi_state.json')
        
        # Capturador de logs
        self.log_capture = LogCapture()
        
        logger.info(f"VSIAdvancedManagerCOS inicializado para región: {self.region}")
        logger.info(f"COS habilitado: {self.use_cos}")
    
    def load_state(self) -> Dict:
        """Carga el estado actual desde COS o archivo local"""
        if self.use_cos and self.cos:
            try:
                state = self.cos.load_state()
                if state:
                    logger.info("Estado cargado desde COS")
                    return state
            except Exception as e:
                logger.warning(f"Error al cargar estado desde COS: {e}")
        
        # Fallback a archivo local
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                logger.info("Estado cargado desde archivo local")
                return json.load(f)
        
        logger.info("No se encontró estado previo, retornando estado vacío")
        return {}
    
    def save_state(self, state: Dict):
        """Guarda el estado actual en COS y archivo local"""
        # Guardar en COS si está disponible
        if self.use_cos and self.cos:
            try:
                self.cos.save_state(state)
                logger.info("Estado guardado en COS")
            except Exception as e:
                logger.error(f"Error al guardar estado en COS: {e}")
        
        # Siempre guardar en archivo local como backup
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
            logger.info(f"Estado guardado en archivo local: {self.state_file}")
        except Exception as e:
            logger.error(f"Error al guardar estado local: {e}")
    
    def save_execution_log(self, execution_data: Dict):
        """Guarda log de ejecución en COS"""
        if self.use_cos and self.cos:
            try:
                self.cos.save_execution_log(execution_data)
                logger.info("Log de ejecución guardado en COS")
            except Exception as e:
                logger.error(f"Error al guardar log de ejecución: {e}")
    
    def get_latest_snapshot(self, volume_id: str) -> Optional[Dict]:
        """Obtiene el snapshot más reciente de un volumen"""
        try:
            response = self.vpc_service.list_snapshots()
            snapshots = response.get_result().get('snapshots', [])
            
            # Filtrar snapshots del volumen específico
            volume_snapshots = [
                s for s in snapshots 
                if s.get('source_volume', {}).get('id') == volume_id
            ]
            
            if not volume_snapshots:
                logger.warning(f"No se encontraron snapshots para volumen {volume_id}")
                return None
            
            # Ordenar por fecha de creación (más reciente primero)
            volume_snapshots.sort(
                key=lambda x: x.get('created_at', ''), 
                reverse=True
            )
            
            latest = volume_snapshots[0]
            logger.info(f"Snapshot más reciente: {latest['id']} - {latest['created_at']}")
            return latest
            
        except ApiException as e:
            logger.error(f"Error al obtener snapshots: {e}")
            return None
    
    def get_address_prefix_id(self, zone_name: str, cidr: str) -> Optional[str]:
        """Obtiene el ID de un address prefix existente"""
        try:
            vpc_id = self.config['vpc']['id']
            response = self.vpc_service.list_vpc_address_prefixes(vpc_id=vpc_id)
            prefixes = response.get_result().get('address_prefixes', [])
            
            for prefix in prefixes:
                if (prefix.get('zone', {}).get('name') == zone_name and
                    prefix.get('cidr') == cidr):
                    return prefix['id']
            return None
        except ApiException as e:
            logger.error(f"Error al buscar address prefix: {e}")
            return None
    
    def create_address_prefix(self, zone_name: str) -> Optional[str]:
        """Crea un address prefix en la zona especificada"""
        try:
            vpc_id = self.config['vpc']['id']
            cidr = self.config['address_prefix_cidr']
            
            # Verificar si ya existe
            existing_id = self.get_address_prefix_id(zone_name, cidr)
            if existing_id:
                logger.info(f"Address prefix ya existe en {zone_name}: {existing_id}")
                return existing_id
            
            # Crear nuevo address prefix
            logger.info(f"Creando address prefix {cidr} en zona {zone_name}...")
            
            response = self.vpc_service.create_vpc_address_prefix(
                vpc_id=vpc_id,
                cidr=cidr,
                zone={'name': zone_name},
                name=f"tunal-prefix-{zone_name}"
            )
            prefix = response.get_result()
            prefix_id = prefix['id']
            logger.info(f"✅ Address prefix creado: {prefix_id}")
            
            # Esperar para que esté disponible
            time.sleep(2)
            return prefix_id
            
        except ApiException as e:
            logger.error(f"❌ Error al crear address prefix: {e}")
            return None
    
    def delete_address_prefix(self, prefix_id: str) -> bool:
        """Elimina un address prefix"""
        try:
            vpc_id = self.config['vpc']['id']
            logger.info(f"Eliminando address prefix {prefix_id}...")
            self.vpc_service.delete_vpc_address_prefix(
                vpc_id=vpc_id,
                id=prefix_id
            )
            logger.info(f"✅ Address prefix eliminado")
            time.sleep(1)
            return True
        except ApiException as e:
            logger.error(f"❌ Error al eliminar address prefix: {e}")
            return False
    
    def get_subnet_id(self, zone_name: str) -> Optional[str]:
        """Obtiene el ID de una subnet existente"""
        try:
            subnet_name = self.config['subnet_name']
            response = self.vpc_service.list_subnets()
            subnets = response.get_result().get('subnets', [])
            
            for subnet in subnets:
                if (subnet.get('name') == subnet_name and
                    subnet.get('zone', {}).get('name') == zone_name):
                    return subnet['id']
            return None
        except ApiException as e:
            logger.error(f"Error al buscar subnet: {e}")
            return None
    
    def create_subnet(self, zone_name: str, prefix_id: str) -> Optional[str]:
        """Crea una subnet en la zona especificada"""
        try:
            subnet_name = self.config['subnet_name']
            subnet_cidr = self.config['subnet_cidr']
            
            # Verificar si ya existe
            existing_id = self.get_subnet_id(zone_name)
            if existing_id:
                logger.info(f"Subnet ya existe en {zone_name}: {existing_id}")
                return existing_id
            
            # Crear nueva subnet
            logger.info(f"Creando subnet {subnet_cidr} en zona {zone_name}...")
            subnet_prototype = {
                'name': subnet_name,
                'vpc': {'id': self.config['vpc']['id']},
                'zone': {'name': zone_name},
                'ipv4_cidr_block': subnet_cidr
            }
            
            response = self.vpc_service.create_subnet(subnet_prototype)
            subnet = response.get_result()
            subnet_id = subnet['id']
            logger.info(f"✅ Subnet creada: {subnet_id}")
            
            # Esperar para que esté disponible
            time.sleep(3)
            return subnet_id
            
        except ApiException as e:
            logger.error(f"❌ Error al crear subnet: {e}")
            return None
    
    def delete_subnet(self, subnet_id: str) -> bool:
        """Elimina una subnet"""
        try:
            logger.info(f"Eliminando subnet {subnet_id}...")
            self.vpc_service.delete_subnet(id=subnet_id)
            logger.info(f"✅ Subnet eliminada")
            time.sleep(2)
            return True
        except ApiException as e:
            logger.error(f"❌ Error al eliminar subnet: {e}")
            return False
    
    def delete_instance(self, instance_id: str) -> bool:
        """Elimina una instancia con espera adecuada"""
        try:
            logger.info(f"Eliminando instancia {instance_id}...")
            self.vpc_service.delete_instance(id=instance_id)
            logger.info(f"✅ Orden de eliminación enviada")
            # Esperar 30 segundos para que se complete la eliminación
            logger.info("Esperando 30s para que se complete la eliminación...")
            time.sleep(30)
            logger.info(f"✅ Instancia eliminada")
            return True
        except ApiException as e:
            logger.error(f"❌ Error al eliminar instancia: {e}")
            return False
    
    def cleanup_zone_resources(self, zone_name: str, instance_id: Optional[str], subnet_id: Optional[str], prefix_id: Optional[str]):
        """Limpia recursos de una zona después de un fallo"""
        logger.warning(f"Limpiando recursos de zona {zone_name}...")
        
        # IMPORTANTE: Eliminar instancia primero
        if instance_id:
            self.delete_instance(instance_id)
        
        # Luego eliminar subnet
        if subnet_id:
            self.delete_subnet(subnet_id)
        
        # Finalmente eliminar address prefix
        if prefix_id:
            self.delete_address_prefix(prefix_id)
        
        logger.info(f"Limpieza de zona {zone_name} completada")
    
    def check_instance_status(self, instance_id: str) -> Tuple[str, bool]:
        """
        Verifica el estado de una instancia
        Retorna: (status, is_error)
        """
        try:
            response = self.vpc_service.get_instance(id=instance_id)
            instance = response.get_result()
            status = instance.get('status', 'unknown')
            
            # Estados de error conocidos
            error_states = ['failed', 'deleting', 'deleted']
            is_error = status in error_states
            
            logger.info(f"Estado de instancia {instance_id}: {status}")
            return status, is_error
            
        except ApiException as e:
            logger.error(f"Error al verificar instancia: {e}")
            return 'error', True
    
    def wait_for_instance_ready(self, instance_id: str, max_wait: int = 600, initial_wait: int = 10) -> bool:
        """
        Espera a que la instancia esté lista o en error
        
        Args:
            instance_id: ID de la instancia
            max_wait: Tiempo máximo de espera en segundos
            initial_wait: Tiempo de espera inicial antes de empezar a verificar
        
        Retorna True si está running, False si hay error
        """
        # Espera inicial para que la instancia se provisione
        logger.info(f"Esperando {initial_wait}s para que la instancia se provisione...")
        time.sleep(initial_wait)
        
        start_time = time.time()
        check_interval = self.config.get('check_interval_seconds', 30)
        
        while time.time() - start_time < max_wait:
            status, is_error = self.check_instance_status(instance_id)
            
            if status == 'running':
                logger.info(f"✅ Instancia {instance_id} está running")
                return True
            
            if is_error:
                logger.error(f"❌ Instancia {instance_id} en estado de error: {status}")
                return False
            
            logger.info(f"Esperando... Estado actual: {status}")
            time.sleep(check_interval)
        
        logger.error(f"Timeout esperando instancia {instance_id}")
        return False
    
    def create_instance_from_snapshot(
        self,
        zone_config: Dict,
        boot_snapshot_id: str,
        instance_name: str,
        data_snapshot_id: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Crea una nueva instancia desde snapshots en la zona especificada
        
        Args:
            zone_config: Configuración de la zona
            boot_snapshot_id: ID del snapshot del volumen de boot
            instance_name: Nombre para la nueva instancia
            data_snapshot_id: ID del snapshot del volumen de datos (opcional)
            
        Returns:
            Tuple[instance_id, subnet_id, prefix_id] o (None, None, None) si falla
        """
        zone_name = zone_config['name']
        prefix_id = None
        subnet_id = None
        
        try:
            logger.info(f"Creando instancia en zona {zone_name}")
            logger.info(f"  Boot snapshot: {boot_snapshot_id}")
            if data_snapshot_id:
                logger.info(f"  Data snapshot: {data_snapshot_id}")
            
            # 1. Crear address prefix
            prefix_id = self.create_address_prefix(zone_name)
            if not prefix_id:
                logger.error(f"No se pudo crear address prefix en zona {zone_name}")
                return None, None, None
            
            # 2. Crear subnet
            subnet_id = self.create_subnet(zone_name, prefix_id)
            if not subnet_id:
                logger.error(f"No se pudo crear subnet en zona {zone_name}")
                self.cleanup_zone_resources(zone_name, None, None, prefix_id)
                return None, None, None
            
            # Preparar configuración de volumen de boot desde snapshot
            boot_volume_attachment = {
                'delete_volume_on_instance_delete': False,
                'volume': {
                    'name': f"{instance_name}-boot",
                    'profile': {'name': 'general-purpose'},
                    'source_snapshot': {'id': boot_snapshot_id}
                }
            }
            
            # Preparar configuración de red con IP fija
            primary_network_interface = {
                'name': 'eth0',
                'subnet': {'id': subnet_id},
                'primary_ip': {
                    'address': self.config['vsi_ip']  # IP fija 10.10.10.20
                }
            }
            
            if self.config.get('security_group_ids'):
                primary_network_interface['security_groups'] = [
                    {'id': sg_id} for sg_id in self.config['security_group_ids']
                ]
            
            # Preparar volúmenes adicionales (data volume)
            volume_attachments = []
            if data_snapshot_id:
                data_volume_attachment = {
                    'delete_volume_on_instance_delete': False,
                    'volume': {
                        'name': f"{instance_name}-data",
                        'profile': {'name': 'general-purpose'},
                        'source_snapshot': {'id': data_snapshot_id}
                    }
                }
                volume_attachments.append(data_volume_attachment)
                logger.info(f"Configurado volumen de datos desde snapshot")
            
            # Crear instancia
            instance_prototype = {
                'name': instance_name,
                'profile': {'name': self.config['vsi_profile']},
                'zone': {'name': zone_name},
                'vpc': {'id': self.config['vpc']['id']},
                'resource_group': {'id': self.config['resource_group_id']},
                'boot_volume_attachment': boot_volume_attachment,
                'primary_network_interface': primary_network_interface,
                'keys': [{'id': key_id} for key_id in self.config.get('ssh_key_ids', [])]
            }
            
            # Agregar volúmenes adicionales si existen
            if volume_attachments:
                instance_prototype['volume_attachments'] = volume_attachments
            
            response = self.vpc_service.create_instance(instance_prototype)
            instance = response.get_result()
            instance_id = instance['id']
            
            logger.info(f"✅ Instancia creada: {instance_id} en zona {zone_name}")
            return instance_id, subnet_id, prefix_id
            
        except ApiException as e:
            logger.error(f"❌ Error al crear instancia en zona {zone_name}: {e}")
            # Limpiar recursos creados si falla la creación de la instancia
            self.cleanup_zone_resources(zone_name, None, subnet_id, prefix_id)
            return None, None, None
    
    def start_existing_instance(self, instance_id: str) -> bool:
        """Intenta iniciar una instancia existente"""
        try:
            status, is_error = self.check_instance_status(instance_id)
            
            if is_error:
                logger.error(f"Instancia {instance_id} en estado de error: {status}")
                return False
            
            if status == 'running':
                logger.info(f"Instancia {instance_id} ya está running")
                return True
            
            if status == 'stopped':
                logger.info(f"Iniciando instancia {instance_id}...")
                self.vpc_service.create_instance_action(
                    instance_id=instance_id,
                    type='start'
                )
                
                # Esperar a que esté lista
                return self.wait_for_instance_ready(instance_id)
            
            logger.warning(f"Estado inesperado: {status}")
            return False
            
        except ApiException as e:
            logger.error(f"Error al iniciar instancia: {e}")
            return False
    
    def update_backup_policy(self, instance_id: str, volume_ids: List[str]):
        """Actualiza la política de backup con los nuevos volúmenes"""
        try:
            backup_policy_id = self.config.get('backup_policy_id')
            if not backup_policy_id:
                logger.warning("No hay backup_policy_id configurado")
                return
            
            logger.info(f"Actualizando política de backup {backup_policy_id}")
            logger.info(f"Volúmenes a incluir en backup: {volume_ids}")
            
            # Guardar metadata de backup en COS
            if self.use_cos and self.cos:
                backup_metadata = {
                    'instance_id': instance_id,
                    'volume_ids': volume_ids,
                    'backup_policy_id': backup_policy_id,
                    'updated_at': datetime.now().isoformat()
                }
                self.cos.save_backup_metadata(backup_metadata)
            
        except ApiException as e:
            logger.error(f"Error al actualizar política de backup: {e}")
    
    def get_instance_volumes(self, instance_id: str) -> List[str]:
        """Obtiene los IDs de todos los volúmenes de una instancia"""
        try:
            response = self.vpc_service.get_instance(id=instance_id)
            instance = response.get_result()
            
            volume_ids = []
            
            # Boot volume
            boot_volume = instance.get('boot_volume_attachment', {}).get('volume', {})
            if boot_volume.get('id'):
                volume_ids.append(boot_volume['id'])
            
            # Data volumes
            for attachment in instance.get('volume_attachments', []):
                volume = attachment.get('volume', {})
                if volume.get('id'):
                    volume_ids.append(volume['id'])
            
            logger.info(f"Volúmenes de instancia {instance_id}: {volume_ids}")
            return volume_ids
            
        except ApiException as e:
            logger.error(f"Error al obtener volúmenes: {e}")
            return []
    
    def smart_start(self) -> Dict:
        """
        Lógica inteligente de inicio con logging a COS
        """
        execution_start = datetime.now()
        execution_log = {
            'action': 'smart_start',
            'start_time': execution_start.isoformat(),
            'region': self.region,
            'steps': []
        }
        
        try:
            state = self.load_state()
            current_instance_id = state.get('active_instance_id')
            
            # Intentar iniciar instancia existente
            if current_instance_id:
                logger.info(f"Intentando iniciar instancia existente: {current_instance_id}")
                execution_log['steps'].append({
                    'step': 'try_start_existing',
                    'instance_id': current_instance_id,
                    'timestamp': datetime.now().isoformat()
                })
                
                if self.start_existing_instance(current_instance_id):
                    logger.info("✅ Instancia existente iniciada exitosamente")
                    execution_log['status'] = 'success'
                    execution_log['result'] = 'started_existing'
                    execution_log['instance_id'] = current_instance_id
                    execution_log['end_time'] = datetime.now().isoformat()
                    
                    self.save_execution_log(execution_log)
                    
                    return {
                        'status': 'success',
                        'action': 'started_existing',
                        'instance_id': current_instance_id
                    }
            
            # Si no hay instancia o falló, crear nueva
            logger.info("Creando nueva instancia desde snapshots...")
            execution_log['steps'].append({
                'step': 'create_new_from_snapshot',
                'timestamp': datetime.now().isoformat()
            })
            
            # Verificar que tenemos los IDs de snapshots desde variables de entorno
            if not self.boot_snapshot_id:
                error_msg = 'BOOT_VOLUME_SNAPSHOT_ID no está configurado en las variables de entorno'
                logger.error(error_msg)
                execution_log['status'] = 'error'
                execution_log['error'] = error_msg
                execution_log['end_time'] = datetime.now().isoformat()
                self.save_execution_log(execution_log)
                
                return {'status': 'error', 'message': error_msg}
            
            execution_log['boot_snapshot_id'] = self.boot_snapshot_id
            if self.data_snapshot_id:
                execution_log['data_snapshot_id'] = self.data_snapshot_id
                logger.info(f"Usando snapshots: Boot={self.boot_snapshot_id}, Data={self.data_snapshot_id}")
            else:
                logger.info(f"Usando snapshot de boot: {self.boot_snapshot_id}")
                logger.warning("No se configuró DATA_VOLUME_SNAPSHOT_ID, solo se creará volumen de boot")
            
            # Intentar crear en cada zona según prioridad
            zones = sorted(self.config['zones'], key=lambda x: x['priority'])
            
            for zone_config in zones:
                zone_name = zone_config['name']
                instance_name = f"tunal-gpu-{zone_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                
                logger.info(f"Intentando crear instancia en zona {zone_name}...")
                execution_log['steps'].append({
                    'step': 'try_create_in_zone',
                    'zone': zone_name,
                    'timestamp': datetime.now().isoformat()
                })
                
                # Intentar crear instancia y obtener IDs de recursos
                instance_id, subnet_id, prefix_id = self.create_instance_from_snapshot(
                    zone_config,
                    self.boot_snapshot_id,
                    instance_name,
                    self.data_snapshot_id
                )
                
                if instance_id:
                    # Esperar a que esté lista
                    if self.wait_for_instance_ready(instance_id):
                        logger.info(f"✅ Instancia creada exitosamente en zona {zone_name}")
                        
                        # Obtener volúmenes de la nueva instancia
                        volume_ids = self.get_instance_volumes(instance_id)
                        
                        # Actualizar política de backup
                        self.update_backup_policy(instance_id, volume_ids)
                        
                        # Guardar estado incluyendo IDs de recursos de red
                        new_state = {
                            'active_instance_id': instance_id,
                            'instance_name': instance_name,
                            'zone': zone_name,
                            'subnet_id': subnet_id,
                            'prefix_id': prefix_id,
                            'boot_volume_id': volume_ids[0] if volume_ids else None,
                            'volume_ids': volume_ids,
                            'created_at': datetime.now().isoformat(),
                            'last_start': datetime.now().isoformat()
                        }
                        self.save_state(new_state)
                        
                        # Log de ejecución exitosa
                        execution_log['status'] = 'success'
                        execution_log['result'] = 'created_new'
                        execution_log['instance_id'] = instance_id
                        execution_log['zone'] = zone_name
                        execution_log['volume_ids'] = volume_ids
                        execution_log['end_time'] = datetime.now().isoformat()
                        self.save_execution_log(execution_log)
                        
                        return {
                            'status': 'success',
                            'action': 'created_new',
                            'instance_id': instance_id,
                            'zone': zone_name
                        }
                    else:
                        logger.warning(f"Instancia en zona {zone_name} no quedó ready, esperando antes de limpiar...")
                        # Esperar 30 segundos antes de intentar eliminar la instancia
                        logger.info("Esperando 30s antes de eliminar recursos...")
                        time.sleep(30)
                        # Limpiar recursos de esta zona antes de intentar en la siguiente
                        self.cleanup_zone_resources(zone_name, instance_id, subnet_id, prefix_id)
                        execution_log['steps'].append({
                            'step': 'zone_failed',
                            'zone': zone_name,
                            'reason': 'instance_not_ready',
                            'timestamp': datetime.now().isoformat()
                        })
                else:
                    # Si no se pudo crear la instancia, los recursos ya fueron limpiados en create_instance_from_snapshot
                    logger.warning(f"No se pudo crear instancia en zona {zone_name}, intentando siguiente zona...")
                    execution_log['steps'].append({
                        'step': 'zone_failed',
                        'zone': zone_name,
                        'reason': 'instance_creation_failed',
                        'timestamp': datetime.now().isoformat()
                    })
            
            # Si llegamos aquí, falló en todas las zonas
            error_msg = 'No se pudo crear instancia en ninguna zona'
            logger.error(error_msg)
            execution_log['status'] = 'error'
            execution_log['error'] = error_msg
            execution_log['end_time'] = datetime.now().isoformat()
            self.save_execution_log(execution_log)
            
            return {'status': 'error', 'message': error_msg}
            
        except Exception as e:
            logger.error(f"Error inesperado en smart_start: {e}")
            execution_log['status'] = 'error'
            execution_log['error'] = str(e)
            execution_log['end_time'] = datetime.now().isoformat()
            self.save_execution_log(execution_log)
            raise
    
    def stop_instance(self) -> Dict:
        """Detiene la instancia activa con logging a COS"""
        execution_start = datetime.now()
        execution_log = {
            'action': 'stop',
            'start_time': execution_start.isoformat(),
            'region': self.region
        }
        
        try:
            state = self.load_state()
            instance_id = state.get('active_instance_id')
            
            if not instance_id:
                error_msg = 'No hay instancia activa en el estado'
                logger.error(error_msg)
                execution_log['status'] = 'error'
                execution_log['error'] = error_msg
                execution_log['end_time'] = datetime.now().isoformat()
                self.save_execution_log(execution_log)
                
                return {'status': 'error', 'message': error_msg}
            
            execution_log['instance_id'] = instance_id
            
            status, is_error = self.check_instance_status(instance_id)
            
            if status == 'stopped':
                logger.info("Instancia ya está detenida")
                execution_log['status'] = 'success'
                execution_log['result'] = 'already_stopped'
                execution_log['end_time'] = datetime.now().isoformat()
                self.save_execution_log(execution_log)
                
                return {'status': 'success', 'message': 'Instancia ya está detenida'}
            
            if is_error:
                error_msg = f'Instancia en estado de error: {status}'
                logger.error(error_msg)
                execution_log['status'] = 'error'
                execution_log['error'] = error_msg
                execution_log['end_time'] = datetime.now().isoformat()
                self.save_execution_log(execution_log)
                
                return {'status': 'error', 'message': error_msg}
            
            logger.info(f"Deteniendo instancia {instance_id}...")
            self.vpc_service.create_instance_action(
                instance_id=instance_id,
                type='stop'
            )
            
            # Actualizar estado
            state['last_stop'] = datetime.now().isoformat()
            self.save_state(state)
            
            # Log de ejecución exitosa
            execution_log['status'] = 'success'
            execution_log['result'] = 'stopped'
            execution_log['end_time'] = datetime.now().isoformat()
            self.save_execution_log(execution_log)
            
            return {
                'status': 'success',
                'message': 'Instancia detenida',
                'instance_id': instance_id
            }
            
        except ApiException as e:
            logger.error(f"Error al detener instancia: {e}")
            execution_log['status'] = 'error'
            execution_log['error'] = str(e)
            execution_log['end_time'] = datetime.now().isoformat()
            self.save_execution_log(execution_log)
            
            return {'status': 'error', 'message': str(e)}
    
    def get_status(self) -> Dict:
        """Obtiene el estado actual del sistema"""
        state = self.load_state()
        instance_id = state.get('active_instance_id')
        
        if not instance_id:
            return {
                'status': 'no_instance',
                'message': 'No hay instancia activa registrada'
            }
        
        status, is_error = self.check_instance_status(instance_id)
        
        return {
            'instance_id': instance_id,
            'instance_name': state.get('instance_name'),
            'zone': state.get('zone'),
            'status': status,
            'is_error': is_error,
            'created_at': state.get('created_at'),
            'last_start': state.get('last_start'),
            'last_stop': state.get('last_stop'),
            'cos_enabled': self.use_cos
        }


def main():
    """Función principal para ejecutar desde línea de comandos"""
    if len(sys.argv) < 2:
        print("Uso: python vsi_advanced_manager_cos.py [start|stop|status]")
        sys.exit(1)
    
    action = sys.argv[1].lower()
    
    try:
        manager = VSIAdvancedManagerCOS()
        
        if action == 'start':
            result = manager.smart_start()
            print(json.dumps(result, indent=2))
        elif action == 'stop':
            result = manager.stop_instance()
            print(json.dumps(result, indent=2))
        elif action == 'status':
            result = manager.get_status()
            print(json.dumps(result, indent=2))
        else:
            print(f"Acción no reconocida: {action}")
            print("Acciones válidas: start, stop, status")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error: {e}")
        print(json.dumps({'status': 'error', 'message': str(e)}, indent=2))
        sys.exit(1)


if __name__ == '__main__':
    main()

# Made with Bob
