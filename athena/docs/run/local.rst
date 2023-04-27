From the Command Line
===========================================

To run Athena, you have to start at least two processes.
The assessment module manager API will be available at http://localhost:5000.

**Before you start the processes, make sure that you have loaded the environment variables from the** ``.env`` **file in each folder.** This can be achieved using
    .. code-block:: bash

        source .env

The Assessment Module Manager
-----------------------------
Start it from the ``assessment_module_manager`` folder using
    .. code-block:: bash

        poetry run assessment_module_manager

An Assessment Module, like the ``module_example``
-------------------------------------------------
Start it from the ``module_example`` (or another ``module_*`` folder) using
    .. code-block:: bash

        poetry run module

