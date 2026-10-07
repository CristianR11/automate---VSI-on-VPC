# Dockerfile para IBM Cloud Code Engine
# Automatización Multi-Zona con Failover de VSI en VPC

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Archivos de la aplicación
COPY vsi_advanced_manager_cos.py .
COPY cos_storage.py .
COPY schematics_client.py .
COPY config.json .

RUN chmod +x vsi_advanced_manager_cos.py

ENV IBM_CLOUD_REGION=us-east

# Comando por defecto — los jobs de Code Engine sobrescriben con:
#   python vsi_advanced_manager_cos.py start
#   python vsi_advanced_manager_cos.py stop
#   python vsi_advanced_manager_cos.py stop --force
CMD ["python", "vsi_advanced_manager_cos.py", "status"]

# Made with Bob
