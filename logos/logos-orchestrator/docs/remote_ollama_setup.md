# Remote Ollama Configuration Guide

## Overview

This guide explains how to connect Logos to an Ollama instance.

## Connecting to Localhost

If Ollama is running on the same machine as Logos:

1.  **Mac/Windows**: Use `http://host.docker.internal:11434` # Check what is the port of Ollama server
2.  **Linux**: Use `http://localhost:11434` (requires `--network host`) or `http://172.17.0.1:11434`

## Connecting to Production (SSH Tunnel)

To connect to a remote server securely:

1.  **Open Tunnel**: `ssh -L 11435:localhost:11434 user@remote-server`
2.  **Configure Logos**: Update the database to use `http://host.docker.internal:11435`
3.  **Restart Logos**: `docker compose restart logos-server`
