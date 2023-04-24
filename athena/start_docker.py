#!/usr/bin/env python3

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


def start_docker_compose_files(compose_files, env_files):
    processes = []
    for compose_file, env_file in zip(compose_files, env_files):
        process = subprocess.Popen(["docker-compose", "-f", compose_file, "--env-file", env_file, "up"])
        processes.append(process)

    # Wait for all processes to complete
    for process in processes:
        process.wait()


def main():
    modules = get_module_folders(sys.argv[1:])
    valid_modules = filter_valid_modules(modules)

    compose_files = ["docker-compose.yml"]
    compose_files += [str(Path(module, "docker-compose.yml")) for module in valid_modules]
    env_files = [str(Path("assessment_module_manager") / ".env")]
    env_files += [str(Path(module, ".env")) for module in valid_modules]

    logger.info("Building docker-compose file for assessment module manager...")
    for module, compose_file in zip(valid_modules, compose_files):
        logger.info(f"Building docker-compose.yml for '{module}'...")
        build_docker_compose_files(["-f", compose_file])

    logger.info("Starting docker-compose files...")
    start_docker_compose_files(compose_files, env_files)


if __name__ == "__main__":
    main()
