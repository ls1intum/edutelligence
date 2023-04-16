import configparser

modules = configparser.ConfigParser()
modules.read("modules.ini")

print("Starting assessment module manager...")
for module in modules.sections():
    print(f"Found module {module}")
    module_url = modules[module]["url"]
    print(f"Module {module} is at {module_url}")
    module_type = modules[module]["type"]
    print(f"Module {module} is of type {module_type}")