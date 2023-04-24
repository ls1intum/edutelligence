import os
import subprocess
import sys
from logging import getLogger
from pathlib import Path

logger = getLogger(__name__)


def get_module_folders(args):
    if not args:
        return [dir_name for dir_name in os.listdir() if os.path.isdir(dir_name) and dir_name.startswith('module_')]
    else:
        return args


def filter_valid_modules(modules):
    valid_modules = []
    for module in modules:
        if os.path.isdir(module) and os.path.isfile(os.path.join(module, "docker-compose.yml")):
            valid_modules.append(module)
        else:
            logger.warning(f"Skipping module '{module}' because it is not a valid module folder")
    return valid_modules


def build_docker_compose_files(compose_files):
    subprocess.run(["docker-compose"] + compose_files + ["build"])


def start_docker_compose_files(compose_files):
    subprocess.run(["docker-compose"] + compose_files + ["up"])


def main():
    modules = get_module_folders(sys.argv[1:])
    valid_modules = filter_valid_modules(modules)

    compose_files = ["-f", "docker-compose.yml"]
    for module in valid_modules:
        compose_files += ["-f", str(Path(module, "docker-compose.yml"))]

    logger.info("Building docker-compose file for assessment module manager...")
    build_docker_compose_files(["-f", "docker-compose.yml"])
    for module in valid_modules:
        logger.info(f"Building docker-compose.yml for module '{module}'...")
        build_docker_compose_files(["-f", str(Path(module, "docker-compose.yml"))])

    logger.info("Starting docker-compose files...")
    start_docker_compose_files(compose_files)


if __name__ == "__main__":
    main()
