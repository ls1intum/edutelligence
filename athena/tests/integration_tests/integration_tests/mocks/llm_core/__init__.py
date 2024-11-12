import importlib.util
import sys
import os

utils_path = None
for path in sys.path:
    if path.endswith('llm_core'):
        utils_path = os.path.join(path, 'llm_core', 'utils')
        break

if utils_path and os.path.exists(utils_path):
    utils_spec = importlib.util.spec_from_file_location("llm_core.utils", os.path.join(utils_path, '__init__.py'))
    utils = importlib.util.module_from_spec(utils_spec)
    sys.modules["llm_core.utils"] = utils
    utils_spec.loader.exec_module(utils)
else:
    raise ModuleNotFoundError("Cannot find the llm_core.utils module in the specified path")

print(utils)