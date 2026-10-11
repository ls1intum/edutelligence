FROM python:3.13-slim

ARG VERSION=dev
ARG MODE=good
ENV WORKER_VERSION=$VERSION \
    WORKER_MODE=$MODE \
    PYTHONUNBUFFERED=1

COPY server.py /server.py

CMD ["python", "/server.py"]
