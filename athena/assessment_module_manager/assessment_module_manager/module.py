import configparser
from typing import List


class Module:
    def __init__(self, name, url, type_):
        self.name = name
        self.url = url
        self.type = type_

    def __repr__(self):
        return f"Module({self.name}, {self.url}, {self.type})"


def get_module_list() -> List[Module]:
    modules = configparser.ConfigParser()
    modules.read("modules.ini")
    return [
        Module(module, modules[module]["url"], modules[module]["type"])
        for module in modules.sections()
    ]
