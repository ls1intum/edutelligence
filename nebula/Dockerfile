FROM python:3.13-alpine

RUN apk update && \
    apk add --no-cache gcc musl-dev postgresql-dev rust cargo curl

RUN pip install poetry==2.1.1

# Setze Arbeitsverzeichnis
WORKDIR /app

# Poetry config und Code kopieren
COPY pyproject.toml poetry.lock /app/
COPY src/ /app/src/

# PYTHONPATH so setzen, dass "main" gefunden wird
ENV PYTHONPATH=/app/src

# Installiere nur Abhängigkeiten, nicht das Projekt selbst
RUN poetry install --no-root

# Exponiere gRPC-Port
EXPOSE 50051

ENV PYTHONPATH="/app/src"
# Starte das Hauptmodul
CMD ["poetry", "run", "nebula"]
