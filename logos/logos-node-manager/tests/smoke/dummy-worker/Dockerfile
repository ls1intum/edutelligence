FROM python:3.13-slim

# The smoke test counts the images with this label, to see whether a deployment leaves an unneeded one on the host.
LABEL nm-smoke=1

ARG VERSION=dev
ARG MODE=good
ENV WORKER_VERSION=$VERSION \
    WORKER_MODE=$MODE \
    PYTHONUNBUFFERED=1

COPY server.py /server.py

CMD ["python", "/server.py"]
