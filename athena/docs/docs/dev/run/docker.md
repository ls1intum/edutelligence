---
title: From Docker
---

You can start the Assessment Module Manager and all available modules in
this repository using Docker.

## Build and start with local images

```bash
docker-compose up --build
```

The assessment module manager API will be available at [http://localhost:5100](http://localhost:5100).

## Start with remote images

```bash
ATHENA_ENV_DIR=some-path \
ATHENA_DOMAIN=athena.example.com \
ATHENA_TLS_CERT_FILE=/path/to/server.fullchain.pem \
ATHENA_TLS_KEY_FILE=/path/to/server.privkey.pem \
docker compose -f docker-compose.prod.yml up
```

The `ATHENA_ENV_DIR` is expected to contain environment files `assessment_module_manager.env` and `module_something.env`. The `ATHENA_DOMAIN` environment variable is used to configure the domain name of the assessment module manager API. The assessment module manager API will be available at [https://athena.example.com](https://athena.example.com) (depending on the `ATHENA_DOMAIN` environment variable).

The TLS variables must point to an existing full-chain certificate and its matching private key on the Docker host. Caddy mounts only these two files, read-only. They can also be set in the deployment directory's `.env` file instead of on the command line.

If the host certificate filenames contain colons (as pira-client's can), Docker may reject them as bind mount source paths. Create colon-free symlink aliases on the host, outside pira-client's managed directory, and set the TLS variables to those aliases. For example, `/opt/athena/pira-fullchain.pem` can point to pira-client's `live/*.fullchain.pem`, while `/opt/athena/pira-key.pem` points to the matching `live/*.privkey.pem`. The aliases do not copy the private key.

When a certificate manager replaces a symlinked certificate, restart the Caddy container so Docker binds the new file (for example, `docker restart athena-caddy-1` for the default Athena Compose project). Reloading Caddy alone does not refresh an individual file bind mount.
