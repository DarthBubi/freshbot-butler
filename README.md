# FreshBot Butler
Your Freshness Guardian - Bringing Convenience to Your Kitchen!

## Development

Use `uv` for dependency management and local environments:

```bash
uv sync --all-groups
uv run python -m flask --app freshbot_butler.app run --debug
```

Refresh the lockfile after dependency changes with:

```bash
uv lock
```
