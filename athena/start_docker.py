#!/usr/bin/env python3
"""
Helper script to start all docker-compose files
for the assessment module manager and all assessment modules.
"""

import argparse
import os
import subprocess
import glob
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_docker_compose_files(production_mode, modules):
    logger.info('Getting docker-compose files...')
    compose_files = []

    for folder in ["assessment_module_manager"] + modules:
        module_files = [f'./{folder}/docker-compose.yml']
        if not production_mode:
            module_files.append(f'./{folder}/docker-compose.override.yml')
        else:
            module_files.append(f'./{folder}/docker-compose.prod.yml')
        compose_files.append(module_files)

    logger.info('Docker-compose files collected.')
    return compose_files

def build_and_start_docker_compose_files(compose_files, env_file_path, production_mode):
    logger.info('Building and starting docker-compose files...')
    for files in compose_files:
        directory = os.path.dirname(files[0])
        env_file = os.path.join(env_file_path, directory, '.env')

        cmd = ['docker-compose'] + ['-f ' + file for file in files]

        # run the build in non-production mode only
        if not production_mode:
            build_cmd = cmd + ['build']
            logger.info('Building docker containers using command: %s', " ".join(build_cmd))
            subprocess.run(' '.join(build_cmd), shell=True, check=True)

        up_cmd = cmd + ['--env-file', env_file, 'up', '-d']
        logger.info('Starting docker containers using command: %s', " ".join(up_cmd))
        subprocess.run(' '.join(up_cmd), shell=True, check=True)
    logger.info('Docker-compose files have been built and started.')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--production', action='store_true', help='Run in production mode')
    parser.add_argument('--env_file_path', default='.', help='Path to .env file dir')
    parser.add_argument('--modules', nargs='*', default=glob.glob('module_*'), help='Modules to run')

    args = parser.parse_args()

    logger.info('Parsed arguments.')

    compose_files = get_docker_compose_files(args.production, args.modules)

    build_and_start_docker_compose_files(compose_files, args.env_file_path, args.production)


if __name__ == '__main__':
    main()
