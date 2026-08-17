# Custom chat templates

Jinja chat templates that override the one bundled with a model's tokenizer.

This directory is bind-mounted read-only into the worker container at
`/opt/logos-workernode/chat-templates` — the same absolute path it has on a
production host, because the compose directory there *is*
`/opt/logos-workernode`. Templates therefore survive image updates and
container restarts, and the path printed in the worker log is directly
openable on the host.

## Using a template

Drop the `.jinja` file here, then reference it by file name from
`config.yml`:

```yaml
engines:
  vllm:
    model_overrides:
      Qwen/Qwen3-8B:
        chat_template: qwen3-tools.jinja
```

Subdirectories work too (`chat_template: qwen/tools.jinja`). Absolute paths
are accepted only when they point inside this directory; `..` is rejected.

The worker passes the resolved absolute path to vLLM as `--chat-template`.
If the file is missing, the lane fails to spawn with an explicit error rather
than quietly falling back to the model's built-in template — a silent
fallback would change generation behaviour with no visible signal.

On production hosts this directory is operator-managed (Ansible / manual
`scp`); the deploy workflow only ships `docker-compose.yml` and `.env`, so
adding a template does **not** require a redeploy — only a lane restart.

For local development, `LOGOS_CHAT_TEMPLATE_DIR` overrides the directory when
running the worker outside Docker.
