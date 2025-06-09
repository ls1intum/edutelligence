# Basisimage: schlankes Python
FROM python:3.12.3-slim

# Setze Arbeitsverzeichnis
WORKDIR /app

# Installiere Poetry
RUN pip install --no-cache-dir poetry

# Kopiere Poetry-Konfiguration
COPY pyproject.toml poetry.lock ./

# Installiere Abhängigkeiten (ohne virtuelle Umgebung)
RUN poetry config virtualenvs.create false && poetry install --no-root

# Kopiere Quellcode
COPY src ./src

# Kompiliere Protobuf (optional, falls du das im Container willst)
RUN python -m grpc_tools.protoc \
    -I=src \
    --python_out=src \
    --grpc_python_out=src \
    src/nebula/services/faq_service/faq.proto

# Füge Python-Importpfad hinzu
ENV PYTHONPATH=/app/src

# Starte die main.py
CMD ["python", "src/nebula/main.py"]
