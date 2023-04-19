import configparser
from typing import List

from ..app import app
from ..module import Module


@app.get("/modules")
def get_modules() -> List[Module]:
    """Get a list of all Athena modules that are available."""
    modules_config = configparser.ConfigParser()
    modules_config.read("modules.ini")
    return [
        Module(name=module, url=modules_config[module]["url"], type=modules_config[module]["type"])
        for module in modules_config.sections()
    ]
