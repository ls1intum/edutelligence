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
ATHENA_ENV_DIR=some-path ATHENA_DOMAIN=athena.example.com docker-compose -f docker-compose.prod.yml up
```

The `ATHENA_ENV_DIR` is expected to contain environment files `assessment_module_manager.env` and `module_something.env`. The `ATHENA_DOMAIN` environment variable is used to configure the domain name of the assessment module manager API. The assessment module manager API will be available at [https://athena.example.com](https://athena.example.com) (depending on the `ATHENA_DOMAIN` environment variable).
