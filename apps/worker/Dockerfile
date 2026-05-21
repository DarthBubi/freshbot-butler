FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY freshbot_butler ./freshbot_butler

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "freshbot-worker", "--once"]
