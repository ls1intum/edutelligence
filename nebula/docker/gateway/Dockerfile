# docker/gateway/Dockerfile
FROM python:3.10-slim

WORKDIR /app

# Copy only the gateway logic and shared config
COPY gateway/main.py .
COPY src/security.py ./security.py
COPY application_local.nebula.yml ./application_local.nebula.yml

RUN pip install fastapi uvicorn httpx pyyaml

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
