# Dockerfile para IBM Cloud Code Engine
# Automatización Multi-Zona con Failover de VSI en VPC

FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Copiar archivos de requisitos
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar archivos de configuración y scripts
COPY vsi_advanced_manager_cos.py .
COPY cos_storage.py .
COPY config.json .

# Hacer el script ejecutable
RUN chmod +x vsi_advanced_manager_cos.py

# Variables de entorno por defecto (se sobrescriben en Code Engine)
ENV IBM_CLOUD_REGION=us-east

# Comando por defecto (se sobrescribe en Code Engine Job con args)
# Los jobs de Code Engine ejecutarán:
# - python vsi_advanced_manager_cos.py start  (7:00 AM)
# - python vsi_advanced_manager_cos.py stop   (7:00 PM)
CMD ["python", "vsi_advanced_manager_cos.py", "status"]

# Made with Bob
