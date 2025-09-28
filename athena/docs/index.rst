.. _athena:

====================================================================
Athena: A system to support (semi-)automated assessment of exercises
====================================================================

Athena is a system to support (semi-)automated assessment of exercises.
It connects to an LMS (Learning Management System) and provides endpoints for the LMS for

- sending submissions to Athena
- requesting the best submission to be graded next
- sending existing feedback to Athena
- **requesting suggestions for new feedback to give**

Athena will use the information it is given and provide the automatic suggestions by using sub-modules depending on the exercise type.


.. toctree::
    :caption: Overview
    :includehidden:
    :maxdepth: 1

    overview/athena
    overview/playground

.. toctree::
    :caption: User Guide
    :includehidden:
    :maxdepth: 2

    user_guide/index

.. toctree::
    :caption: Setup
    :includehidden:
    :maxdepth: 1

    setup/install
    setup/pycharm
    setup/vscode
    setup/playground
    setup/evaluation

.. toctree::
    :caption: Run
    :includehidden:
    :maxdepth: 1

    run/pycharm
    run/local
    run/docker
    run/playground

.. toctree::
    :caption: Modules
    :includehidden:
    :maxdepth: 1

    module/structure
    module/create

.. toctree::
    :caption: Athena Package
    :includehidden:
    :maxdepth: 1

    athena_package/storage
    athena_package/helpers

.. toctree::
    :caption: Testing
    :includehidden:
    :maxdepth: 1

    tests/index

.. toctree::
    :caption: Administration of Deployments
    :includehidden:
    :maxdepth: 1

    administration_of_deployments/configuration