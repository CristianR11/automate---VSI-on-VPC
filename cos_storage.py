#!/usr/bin/env python3
"""
Cloud Object Storage Integration
Gestiona persistencia de estado y logs en IBM Cloud Object Storage
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Optional
import ibm_boto3
from ibm_botocore.client import Config
from ibm_botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class COSStorage:
    """Clase para gestionar almacenamiento en Cloud Object Storage"""
    
    def __init__(self):
        """Inicializa el cliente de COS"""
        # Credenciales desde variables de entorno
        self.api_key = os.environ.get('IBM_CLOUD_API_KEY')
        self.instance_id = os.environ.get('COS_INSTANCE_ID')
        self.endpoint = os.environ.get('COS_ENDPOINT', 'https://s3.us-east.cloud-object-storage.appdomain.cloud')
        self.bucket_name = os.environ.get('COS_BUCKET_NAME', 'tunal-automation')
        
        if not self.api_key:
            raise ValueError("IBM_CLOUD_API_KEY no está configurada")
        if not self.instance_id:
            raise ValueError("COS_INSTANCE_ID no está configurado")
        
        # Configurar cliente COS
        self.cos_client = ibm_boto3.client(
            's3',
            ibm_api_key_id=self.api_key,
            ibm_service_instance_id=self.instance_id,
            config=Config(signature_version='oauth'),
            endpoint_url=self.endpoint
        )
        
        logger.info(f"COSStorage inicializado - Bucket: {self.bucket_name}")
    
    def save_state(self, state: Dict) -> bool:
        """
        Guarda el estado en COS
        Path: state/vsi_state.json
        """
        try:
            key = 'state/vsi_state.json'
            body = json.dumps(state, indent=2)
            
            self.cos_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=body,
                ContentType='application/json'
            )
            
            logger.info(f"Estado guardado en COS: {key}")
            return True
            
        except ClientError as e:
            logger.error(f"Error al guardar estado en COS: {e}")
            return False
    
    def load_state(self) -> Dict:
        """
        Carga el estado desde COS
        Path: state/vsi_state.json
        """
        try:
            key = 'state/vsi_state.json'
            
            response = self.cos_client.get_object(
                Bucket=self.bucket_name,
                Key=key
            )
            
            body = response['Body'].read().decode('utf-8')
            state = json.loads(body)
            
            logger.info(f"Estado cargado desde COS: {key}")
            return state
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning("No existe estado previo en COS, retornando estado vacío")
                return {}
            else:
                logger.error(f"Error al cargar estado desde COS: {e}")
                return {}
    
    def save_log(self, log_content: str, log_type: str = 'execution') -> bool:
        """
        Guarda logs en COS
        Path: logs/{log_type}/{timestamp}.log
        
        Args:
            log_content: Contenido del log
            log_type: Tipo de log (execution, error, debug)
        """
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            key = f'logs/{log_type}/{timestamp}.log'
            
            self.cos_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=log_content,
                ContentType='text/plain'
            )
            
            logger.info(f"Log guardado en COS: {key}")
            return True
            
        except ClientError as e:
            logger.error(f"Error al guardar log en COS: {e}")
            return False
    
    def save_execution_log(self, execution_data: Dict) -> bool:
        """
        Guarda log de ejecución en formato JSON
        Path: logs/execution/{timestamp}.json
        """
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            key = f'logs/execution/{timestamp}.json'
            body = json.dumps(execution_data, indent=2)
            
            self.cos_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=body,
                ContentType='application/json'
            )
            
            logger.info(f"Log de ejecución guardado en COS: {key}")
            return True
            
        except ClientError as e:
            logger.error(f"Error al guardar log de ejecución en COS: {e}")
            return False
    
    def list_logs(self, log_type: str = 'execution', limit: int = 10) -> list:
        """
        Lista los últimos logs de un tipo específico
        
        Args:
            log_type: Tipo de log (execution, error, debug)
            limit: Número máximo de logs a retornar
        """
        try:
            prefix = f'logs/{log_type}/'
            
            response = self.cos_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=limit
            )
            
            if 'Contents' not in response:
                return []
            
            logs = []
            for obj in response['Contents']:
                logs.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat()
                })
            
            # Ordenar por fecha (más reciente primero)
            logs.sort(key=lambda x: x['last_modified'], reverse=True)
            
            return logs[:limit]
            
        except ClientError as e:
            logger.error(f"Error al listar logs en COS: {e}")
            return []
    
    def get_log_content(self, key: str) -> Optional[str]:
        """
        Obtiene el contenido de un log específico
        
        Args:
            key: Key del objeto en COS (ej: logs/execution/20260620_070015.json)
        """
        try:
            response = self.cos_client.get_object(
                Bucket=self.bucket_name,
                Key=key
            )
            
            content = response['Body'].read().decode('utf-8')
            return content
            
        except ClientError as e:
            logger.error(f"Error al obtener contenido del log: {e}")
            return None
    
    def save_backup_metadata(self, metadata: Dict) -> bool:
        """
        Guarda metadata de backups
        Path: state/backup_metadata.json
        """
        try:
            key = 'state/backup_metadata.json'
            body = json.dumps(metadata, indent=2)
            
            self.cos_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=body,
                ContentType='application/json'
            )
            
            logger.info(f"Metadata de backup guardada en COS: {key}")
            return True
            
        except ClientError as e:
            logger.error(f"Error al guardar metadata de backup: {e}")
            return False
    
    def load_backup_metadata(self) -> Dict:
        """
        Carga metadata de backups
        Path: state/backup_metadata.json
        """
        try:
            key = 'state/backup_metadata.json'
            
            response = self.cos_client.get_object(
                Bucket=self.bucket_name,
                Key=key
            )
            
            body = response['Body'].read().decode('utf-8')
            metadata = json.loads(body)
            
            logger.info(f"Metadata de backup cargada desde COS: {key}")
            return metadata
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning("No existe metadata de backup en COS")
                return {}
            else:
                logger.error(f"Error al cargar metadata de backup: {e}")
                return {}
    
    def create_bucket_if_not_exists(self) -> bool:
        """
        Crea el bucket si no existe
        """
        try:
            # Intentar obtener información del bucket
            self.cos_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"Bucket {self.bucket_name} ya existe")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == '404':
                # Bucket no existe, crearlo
                try:
                    self.cos_client.create_bucket(
                        Bucket=self.bucket_name,
                        CreateBucketConfiguration={
                            'LocationConstraint': 'us-east-standard'
                        }
                    )
                    logger.info(f"Bucket {self.bucket_name} creado exitosamente")
                    return True
                    
                except ClientError as create_error:
                    logger.error(f"Error al crear bucket: {create_error}")
                    return False
            else:
                logger.error(f"Error al verificar bucket: {e}")
                return False
    
    def cleanup_old_logs(self, log_type: str = 'execution', days_to_keep: int = 30) -> int:
        """
        Elimina logs antiguos
        
        Args:
            log_type: Tipo de log a limpiar
            days_to_keep: Días de retención
            
        Returns:
            Número de logs eliminados
        """
        try:
            from datetime import timedelta
            
            prefix = f'logs/{log_type}/'
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            
            response = self.cos_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            
            if 'Contents' not in response:
                return 0
            
            deleted_count = 0
            for obj in response['Contents']:
                if obj['LastModified'].replace(tzinfo=None) < cutoff_date:
                    self.cos_client.delete_object(
                        Bucket=self.bucket_name,
                        Key=obj['Key']
                    )
                    deleted_count += 1
                    logger.info(f"Log antiguo eliminado: {obj['Key']}")
            
            logger.info(f"Limpieza completada: {deleted_count} logs eliminados")
            return deleted_count
            
        except ClientError as e:
            logger.error(f"Error al limpiar logs antiguos: {e}")
            return 0


# Funciones de utilidad para uso directo
def get_cos_storage() -> COSStorage:
    """Obtiene una instancia de COSStorage"""
    return COSStorage()


def save_state_to_cos(state: Dict) -> bool:
    """Guarda estado en COS (función de conveniencia)"""
    cos = get_cos_storage()
    return cos.save_state(state)


def load_state_from_cos() -> Dict:
    """Carga estado desde COS (función de conveniencia)"""
    cos = get_cos_storage()
    return cos.load_state()


def save_execution_log_to_cos(execution_data: Dict) -> bool:
    """Guarda log de ejecución en COS (función de conveniencia)"""
    cos = get_cos_storage()
    return cos.save_execution_log(execution_data)

# Made with Bob
