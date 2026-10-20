FROM python:3.10.20-slim@sha256:63669fd2563fa90b0442fa7b568e66e3667755636cda086d7bcaaa895f66fe39
WORKDIR /workspace
COPY --from=ghcr.io/astral-sh/uv:0.10.5@sha256:476133fa2aaddb4cbee003e3dc79a88d327a5dc7cb3179b7f02cabd8fdfbcc6e /uv /usr/local/bin/uv
ENV UV_NO_CACHE=1
COPY backend/pyproject.toml backend/uv.lock /workspace/backend/
RUN uv sync --project backend --frozen --no-dev --no-install-project
COPY backend /workspace/backend
RUN uv sync --project backend --frozen --no-dev
ENV PATH="/workspace/backend/.venv/bin:$PATH"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
