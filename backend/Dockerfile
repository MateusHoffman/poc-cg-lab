FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
ENTRYPOINT ["./docker-entrypoint.sh"]
