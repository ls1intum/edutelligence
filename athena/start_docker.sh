#!/bin/bash

# This script will start all Docker Compose files for the selected modules as well as the assessment module manager.

# Check if any arguments were provided
if [ $# -eq 0 ]; then
  # No arguments, select all module folders
  modules=$(ls -d module_*)
else
  # Use provided arguments as module names
  modules="$@"
fi

# Initialize a variable to hold all -f flags
compose_files="-f docker-compose.yml"

# Iterate through the selected modules and create -f flags
for module in $modules; do
  if [ -d "$module" ] && [ -f "$module/docker-compose.yml" ]; then
    compose_files+=" -f $module/docker-compose.yml"
  else
    echo "Warning: Skipping invalid module '$module'"
  fi
done

# Build the assessment module manager
docker-compose -f docker-compose.yml build
# Build each of the selected modules
for module in $modules; do
  if [ -d "$module" ] && [ -f "$module/docker-compose.yml" ]; then
    echo "Building module '$module'"
    docker-compose -f $module/docker-compose.yml build
  fi
done

# Start all Docker Compose files at once
docker-compose $compose_files up
