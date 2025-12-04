---
title: Configuration
---

Athena can serve requests from multiple LM systems. It uses a custom
HTTP header `X-Server-URL` to identify the origin of each request. To
prevent unauthorized use of resources, the admin must whitelist all
supported deployments. This configuration is done in the
`assessment_module_manager/deployments.ini` file or the corresponding
Docker analog for server deployments using Docker images.

For each listed deployment, the admin must define a corresponding secret
in the environment variable `LMS_DEPLOYMENT_NAME_SECRET` (replace
DEPLOYMENT_NAME with the name from the .ini file) of the
`assessment_module_manager`. Please note: Playground counts as an LMS
and needs its own record.

This configuration does not exclude or replace inter-module
authentication; Athena still requires keys between modules and the
assessment module manager.
