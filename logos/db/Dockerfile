FROM postgres:17
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-17-cron && rm -rf /var/lib/apt/lists/*
COPY init.sql /docker-entrypoint-initdb.d/init.sql
