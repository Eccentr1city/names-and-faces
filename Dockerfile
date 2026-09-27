FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN chmod -R a+rX /app
ENV NAMES_AND_FACES_DATA_DIR=/data NAMES_AND_FACES_HOST=0.0.0.0 NAMES_AND_FACES_DEBUG=0 PYTHONUNBUFFERED=1
USER 1000:1000
EXPOSE 5050
CMD ["/app/.venv/bin/python", "run.py"]
