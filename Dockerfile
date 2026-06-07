FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY *.py ./

RUN mkdir -p /app/data

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

VOLUME ["/app/data"]

CMD ["python", "bot.py"]
