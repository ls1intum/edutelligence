From Docker
===========================================

You can start the Assessment Module Manager and all available modules in this repository using Docker.

It is recommended to use the provided Python script ``start_docker.py`` to start the Docker containers. This script will find the dockerfiles in the assessment module manager and in all modules, automatically build the Docker images if they are not available yet and start all containers using the ``.env`` environment files from the different folders. To run it:

    .. code-block:: bash

        python start_docker.py

The assessment module manager API will be available at http://localhost:5000.