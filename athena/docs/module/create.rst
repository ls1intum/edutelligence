Create a Module
===========================================

To create a new Athena Module, follow the following steps:

1. Copy the ``module_example`` folder to a new folder with the name of your module.
   It should still be at the project root and its name should start with ``module_``.
2. Update your module name (``module_something``) in the following places:
    * ``module_something/pyproject.toml``
    * rename ``module_something/module_example`` to ``module_something/module_something``
3. Delete the ``poetry.lock`` file, then run ``poetry install`` in your module folder to recreate it.
4. Update the ``.env`` file to include the following values:
    * ``MODULE_NAME``: The name of your module, e.g. ``module_something``
    * ``MODULE_TYPE``: The type of exercise your module supports, e.g. ``text`` or ``programming``
    * ``PORT``: The port your module will run on, e.g. ``5002``. Look for the ports that existing modules are using and use a port that is not already in use. It's best if you just count one up from the highest number (e.g. if the highest used port is 5002, use 5003).
5. Add your module to the ``assessment_module_manager/modules.ini`` and ``assessment_module_manager/modules.docker.ini`` files. Update the URLs accordingly. The Docker URL for your module should be ``http://module_something:port``.