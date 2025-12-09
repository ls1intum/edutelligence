---
title: Create a Module
---

To create a new Athena Module, follow the following steps:

1.  Copy the `module_example` folder to a new folder with the name of
    your module. It should still be at the project root and its name
    should start with `module_`.

2.  Update your module name (`module_something`) in the following places:  
    - `module_something/pyproject.toml`
    - rename `module_something/module_example` to
      `module_something/module_something`

3.  Delete the `poetry.lock` file, then run `poetry install` in your
    module folder to recreate it.

4.  Update the `module.conf` file to include the following values:  
    - `MODULE_NAME`: The name of your module, e.g. `module_something`
    - `MODULE_TYPE`: The type of exercise your module supports, e.g.
      `text` or `programming`
    - `PORT`: The port your module will run on, e.g. `5002`. Look for
      the ports that existing modules are using and use a port that is
      not already in use. It's best if you just count one up from the
      highest number (e.g. if the highest used port is 5002, use 5003).

5.  Add your module to the `assessment_module_manager/modules.ini` and
    `assessment_module_manager/modules.docker.ini` files. Update the
    URLs accordingly. The Docker URL for your module should be
    `http://module_something:port`.

6.  Add a service to in `docker-compose.yml` and
    `docker-compose.prod.yml`. Look at the existing modules for
    examples. Make sure to use the same port as in the `.env` file.

7.  Add a new Run Configuration to PyCharm:  
    - Run -\> Edit Configurations...
    - Click the `+` button and select `Python`
    - Name it `Module Something`
    - Choose the `Module Name` instead of the `Script Path` (see
      screenshot below)
    - Set all other parameters similar to the ones from the example
      module
    - Click `OK`

  ![PyCharm Run Configuration](./images/pycharm-run-configuration.png)

8.  Add a new workspace folder entry for VS Code:  
    - Edit `athena-workspace.code-workspace`
    - Add a new entry to the `folders` array, similar to the one from
      the example module

9.  Add a launch configuration for VS Code:  
    - Open the `.vscode/launch.json` file
    - Add a new configuration, similar to the one from the example
      module
