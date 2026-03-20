---
title: Contributing
---

# Contributing

This guide covers the contribution workflow for Iris, including code style, branching, and the pull request process.

## Code Style

Iris enforces consistent code style through automated tools. All of these are run automatically by pre-commit hooks, but you can also run them manually.

### Formatting

| Tool      | Purpose         | Command                        |
| --------- | --------------- | ------------------------------ |
| **Black** | Code formatting | `poetry run black src/ tests/` |
| **isort** | Import sorting  | `poetry run isort src/ tests/` |

Black and isort are configured to be compatible with each other (`profile = "black"` in isort config).

### Static Analysis

| Tool       | Purpose                     | Command                               |
| ---------- | --------------------------- | ------------------------------------- |
| **Pylint** | Linting and static analysis | `poetry run pylint src/iris/`         |
| **mypy**   | Static type checking        | `poetry run mypy src/`                |
| **bandit** | Security scanning           | `poetry run bandit -r src/ -x tests/` |

### Pre-commit Hooks

Install pre-commit hooks from the **monorepo root** (one level above `iris/`):

```bash
pre-commit install
```

Run all hooks on all files:

```bash
pre-commit run --all-files
```

:::tip
Always run `pre-commit run --all-files` before pushing to catch issues early. The CI pipeline will reject PRs that fail these checks.
:::

## Branch Naming

Iris follows a consistent branch naming convention:

```
feature/iris/<short-description>
```

Examples:

- `feature/iris/add-competency-extraction`
- `feature/iris/fix-memory-retrieval`
- `feature/iris/update-lecture-chat-prompt`

For bug fixes, the convention is the same:

```
bugfix/iris/<short-description>
```

## Commit Messages

Commit messages must follow this format:

```
Iris: Description starting with a capital letter
```

Examples:

- `Iris: Add competency extraction pipeline`
- `Iris: Fix memory retrieval failures crashing agent pipeline`
- `Iris: Update lecture chat system prompt`

If the commit addresses a GitHub issue, include the issue number:

```
Iris: Add competency extraction pipeline (#123)
```

## Pull Request Process

### 1. Create a Feature Branch

```bash
git checkout main
git pull origin main
git checkout -b feature/iris/your-feature
```

### 2. Implement Your Changes

- Follow the code style guidelines above.
- Add tests for new functionality where possible.
- Update documentation if you change public APIs or configuration.

### 3. Run Quality Checks

Before pushing, verify everything passes:

```bash
# Run tests
poetry run pytest -v

# Run all pre-commit hooks
pre-commit run --all-files
```

### 4. Push and Create a PR

```bash
git push origin feature/iris/your-feature
```

Create a PR targeting the `main` branch. The PR title must match this format (enforced by CI):

```
`Iris`: Description starting with a capital letter
```

Note the backtick-wrapped project name — this is required by the CI title validation regex.

### 5. PR Description

Include in your PR description:

- **Summary** — What the PR does and why.
- **Changes** — List of files changed with brief descriptions.
- **Testing** — How the changes were tested.
- **Related issues** — Link with `Closes #NNN` if applicable.

### 6. CI Checks

After creating the PR, verify that all CI checks pass:

```bash
gh pr checks <PR_NUMBER>
```

If any check fails, fix it before requesting review. Common failures:

- **Title validation** — Fix with `gh pr edit <NUMBER> --title '...'`
- **Linting** — Run `pre-commit run --all-files` and commit the fixes.
- **Tests** — Run `poetry run pytest -v` locally to reproduce.

### 7. Review and Merge

- Request review from a team member.
- Address review feedback with additional commits.
- Once approved, the PR can be merged to `main`.

:::warning
Never push directly to `main`. Always create a feature branch and go through the PR process.
:::

## Development Workflow Tips

### Adding a New Pipeline

See [Pipeline System](./pipeline-system.md#creating-a-new-pipeline) for the step-by-step guide.

### Adding a New Tool

See [Tools](./tools.md#creating-a-new-tool) for the pattern and instructions.

### Adding a New LLM Provider

1. Create a new model class in `src/iris/llm/external/` extending `ChatModel`, `EmbeddingModel`, or `LanguageModel`.
2. Add the new type discriminator to the `AnyLlm` union in `src/iris/llm/external/__init__.py`.
3. Add a corresponding `type` string to `llm_config.yml`.
4. Test with a local configuration entry.

### Debugging Pipeline Execution

- Enable verbose logging by setting `LOG_LEVEL=DEBUG`.
- Enable LangFuse tracing in `application.local.yml` to see full trace trees.
- Check the FastAPI docs at `/docs` for endpoint schemas.
- Use the health endpoint (`/api/v1/health`) to verify the server is running.

## Reporting Issues

Report bugs and feature requests on the [GitHub Issues](https://github.com/ls1intum/edutelligence/issues) page. When reporting a bug, include:

- Steps to reproduce.
- Expected vs. actual behavior.
- Relevant log output.
- Iris version (from `pyproject.toml`).
