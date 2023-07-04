#!/usr/bin/env bash

# check if environment variable configuration exists
if [ ! -d athena-env ]; then
    echo "No athena-env directory found. Please create a copy of https://github.com/ls1intum/Athena/tree/develop/env_example with real secrets called "athena-env" and try again."
    exit 1
fi

# heavily inspired by https://github.com/ls1intum/artemis-ansible-collection/blob/20b000d7601735e6916e225b5cea41b960d51197/roles/artemis/templates/artemis-docker.sh.j2#L4

# Function: Print general usage information
function general_help {
    cat << HELP
Usage:
  ./$(basename "$0") <command> [options]

Commands:
  start <pr_tag> <pr_branch> <domain>   Start Athena
  stop                                  Stop the Athena server.
  restart <pr_tag> <pr_branch> <domain> Restart the Athena server.
  run <docker compose cmd>              Run any docker compose subcommand of your choice
HELP
}

function download_docker_compose {
  local pr_branch=$1

  echo "Downloading docker compose files..."
  for file in docker-compose.prod.yml docker-compose.cofee.yml docker-compose.playground.prod.yml; do
    echo "  Downloading $file..."
    curl -sSL -o "$file" https://raw.githubusercontent.com/ls1intum/Athena/"$pr_branch"/"$file"
  done
}

function download_caddyfile {
  local pr_branch=$1

  echo "Downloading Caddyfile..."
  curl -sSL -o Caddyfile https://raw.githubusercontent.com/ls1intum/Athena/"$pr_branch"/Caddyfile
}

function start {
  local pr_tag=$1
  local pr_branch=$2
  local domain=$3

  download_docker_compose "$pr_branch"
  download_caddyfile "$pr_branch"

  echo "Starting Athena with PR tag: $pr_tag and branch: $pr_branch"
  export ATHENA_ENV_DIR="$(pwd)/athena-env"
  export ATHENA_TAG="$pr_tag"
  export ATHENA_DOMAIN="$domain"
  docker compose -f docker-compose.prod.yml -f docker-compose.playground.prod.yml -f docker-compose.cofee.yml up -d --pull always --no-build
}

function stop {
  # TODO: In the future extract pr_tag and pr_branch from env

  echo "Stopping Athena"
  docker compose -f docker-compose.prod.yml -f docker-compose.playground.prod.yml -f docker-compose.cofee.yml stop
}

function restart {
    stop "$@"
    start "$@"
}

function short_logs {
  docker compose -f docker-compose.prod.yml -f docker-compose.playground.prod.yml -f docker-compose.cofee.yml logs -f --tail 1000
}

function all_logs {
  docker compose -f docker-compose.prod.yml -f docker-compose.playground.prod.yml -f docker-compose.cofee.yml logs -f
}

function run_docker_compose_cmd {
  export ATHENA_ENV_DIR="$(pwd)/athena-env"
  export ATHENA_TAG="$pr_tag"
  docker compose -f docker-compose.prod.yml -f docker-compose.playground.prod.yml -f docker-compose.cofee.yml "$@"
}

# read subcommand `athena-docker subcommand server` in variable and remove base command from argument list
subcommand=$1; shift

# Handle empty subcommand
if [ -z "$subcommand" ]; then
    general_help
    exit 1
fi

case "$subcommand" in
    start)
        start "$@"
        ;;
    stop)
        stop "$@"
        ;;
    restart)
        restart "$@"
        ;;
    logs-short)
        short_logs "$@"
        ;;
    logs)
        all_logs "$@"
        ;;
    run)
        run_docker_compose_cmd "$@"
        ;;
    *)
        printf "Invalid Command: $subcommand\n\n" 1>&2
        general_help
        exit 1
        ;;
esac