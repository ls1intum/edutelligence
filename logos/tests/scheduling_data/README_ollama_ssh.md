# Ollama SSH Access (Current Approach)

This documents the current SSH-based approach for reaching a private Ollama `/api/ps` endpoint from the app and for running the optional live SSH test. This may evolve—treat it as the “current best effort”.

## Prerequisites
- Connected to the correct VPN so `ssh <user>@<host>` works from your host.
- A private key present on your host (e.g., `~/.ssh/id_ed25519`) and a corresponding `known_hosts` entry for the target host.

## Host-side setup
1) Ensure key permissions:
```
chmod 600 ~/.ssh/id_ed25519            # or your actual key name
chmod 644 ~/.ssh/known_hosts
```
2) Add host key if needed:
```
ssh-keyscan <host> >> ~/.ssh/known_hosts
```

## Docker compose mounts
In `docker-compose.yaml` ensure the key/known_hosts mounts match your actual key name and destination path used by the provider:
```yaml
services:
  logos-server:
    volumes:
      - ${HOME}/.ssh/id_ed25519:/root/.ssh/id_ed25519:ro    # adjust filename if different
      - ${HOME}/.ssh/known_hosts:/root/.ssh/known_hosts:ro
```
If your key has a different name, update both the mount and the DB `ssh_key_path` (see below).

## Database fields (providers table)
One-time migration (if not already applied):
```bash
# Run all migrations (includes SSH columns + SDI monitoring fields)
cd db/migrations
./run_all_migrations.sh
```
Or manually run individual migrations in order (see `db/migrations/README.md`).

Populate the provider row (example for openwebui):
```
docker exec -it logos-db psql -U postgres -d logosdb \
  -c "UPDATE providers
      SET ssh_host='<host>',
          ssh_user='<user>',
          ssh_port=22,
          ssh_key_path='/root/.ssh/id_ed25519',
          ssh_remote_ollama_port=11434
      WHERE name='openwebui';"
```
Adjust the key path if you mounted a differently named key.

## Container restart
After mounts/DB changes:
```
docker compose up -d --force-recreate logos-server
```

## Connectivity smoke-tests
From inside the app container:
```
docker exec -it logos-server sh -c "ssh -o BatchMode=yes -o ConnectTimeout=5 <user>@<host> 'echo ok'"
docker exec -it logos-server sh -c "ssh -o BatchMode=yes -o ConnectTimeout=5 <user>@<host> 'curl -s http://127.0.0.1:11434/api/ps | head'"
```
If permissions errors appear, temporarily mount the key without `:ro`, `chmod 600` inside, then restore `:ro`.

## Optional live SSH test
The test suite stays mocked by default. To run the live SSH poll test, pass parameters to the test script:
```
cd tests/scheduling_data
./test_scheduling_data.sh \
  --ssh-host=<host> \
  --ssh-user=<user> \
  --ssh-key-path=/root/.ssh/id_ed25519 \
  --ssh-remote-port=11434
```
If these parameters are not provided, the live test is skipped and all other tests still run.

## Real workflow: polling + real inference
The SSH config above only covers `/api/ps` polling. To also send real inference to the remote Ollama:
1) Keep the SSH polling fields set on the provider (ssh_host/user/port/key_path/ssh_remote_ollama_port).
2) Expose the actual Ollama HTTP endpoint to the app. Two options:
   - **Local tunnel:** Run on your host:  
     `ssh -N -L 11434:127.0.0.1:11434 <user>@<host>`  
     Then set `providers.base_url` to `http://host.docker.internal:11434` (or `http://localhost:11434` if your container can reach it).
   - **Direct reachability:** If the app can reach the Ollama HTTP port directly, set `providers.base_url` to `http://<host>:11434`.
3) Update the provider row to include the inference base URL (in addition to ssh_* used for polling):
```
docker exec -it logos-db psql -U postgres -d logosdb \
  -c "UPDATE providers SET base_url='http://host.docker.internal:11434' WHERE name='openwebui';"
```
4) Ensure models exist and are linked to that provider (models.endpoint should be the model name or endpoint as expected by Ollama).
5) Start/refresh the app container; SDI will poll `/api/ps` over SSH, and live requests will go to `base_url`.
6) Send a real request through Logos (example, adjust logos_key and model):
```
curl -X POST https://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "logos_key: <your-logos-key>" \
  -d '{"model":"llama3.3:latest","messages":[{"role":"user","content":"hello"}]}'
```
This uses Logos routing/policy to send traffic to the configured Ollama provider; SDI still polls model load via SSH.

## Optional live inference test (DB-driven, end-to-end)
To run a real inference against the remote Ollama (loads model + polls via SSH) using DB configuration:
```
cd tests/scheduling_data
./test_scheduling_data.sh \
  --ssh-host=<host> \
  --ssh-user=<user> \
  --ssh-key-path=/root/.ssh/id_ed25519 \
  --ollama-live-model-id=18
```
Where `18` is a model row ID linked to the openwebui provider (e.g., gemma3:4b).
This test uses DB rows (provider/model) for base_url, ssh_* fields, and model name. The test will skip if the base_url is not reachable.

## For new users cloning the repo
1) Make sure your key/known_hosts exist and are chmod'd on the host.
2) Adjust `docker-compose.yaml` mounts to your key name/path.
3) Apply all database migrations (see `db/migrations/run_all_migrations.sh`) and set provider row fields.
4) Recreate the app container.
5) Verify `docker exec ... ssh` works.
6) Run tests; pass SSH parameters (`--ssh-host`, `--ssh-user`, `--ssh-key-path`) only if you want the live SSH poll.
7) For real inference, configure `providers.base_url` as described above (tunnel or direct). To exercise the DB-driven live inference test, pass `--ollama-live-model-id=<id>`; provider ssh_* comes from the DB row.
