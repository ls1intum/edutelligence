FROM python:3.12.3-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false && poetry install --no-root

COPY src ./src

#compile proto files
RUN python -m grpc_tools.protoc \
    -I=src \
    --python_out=src \
    --grpc_python_out=src \
    src/nebula/services/faq_service/faq.proto

ENV PYTHONPATH=/app/src

CMD ["python", "src/nebula/main.py"]
