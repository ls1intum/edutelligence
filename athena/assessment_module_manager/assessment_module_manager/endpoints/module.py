import configparser
from typing import List

from ..app import app
from ..module import Module


@app.get("/modules")
def get_module_list() -> List[Module]:
    """Get a list of all Athena modules that are available."""
    modules = configparser.ConfigParser()
    modules.read("modules.ini")
    return [
        Module(name=module, url=modules[module]["url"], type=modules[module]["type"])
        for module in modules.sections()
    ]
