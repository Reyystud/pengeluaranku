# One build for the Python services (PRD 19.1, 16.7). Targets: `backend`, `ml-service`, `pipelines`.
#   docker build -f infrastructure/docker/python.Dockerfile --target backend --build-arg PACKAGE=sei-backend .
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app
# libgomp is needed by LightGBM / scikit-learn wheels.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

FROM base AS build
ARG PACKAGE
COPY pyproject.toml uv.lock ./
COPY ml ./ml
COPY data_generator ./data_generator
COPY pipelines ./pipelines
COPY services ./services
COPY config ./config
COPY schemas ./schemas
COPY data_splits ./data_splits
RUN uv sync --frozen --no-dev --package ${PACKAGE}

FROM base AS runtime
RUN useradd --system --uid 10001 --create-home app
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app
USER app

FROM runtime AS backend
WORKDIR /app/services/backend
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["python", "-m", "app"]

FROM runtime AS ml-service
WORKDIR /app
ENV HOST=0.0.0.0 PORT=8080
EXPOSE 8080
CMD ["python", "-m", "ml_service"]

# Cloud Run job image (PRD 16.1, 15.1): Cloud Scheduler passes the job name as its argument.
FROM runtime AS pipelines
WORKDIR /app
ENTRYPOINT ["python", "-m", "pipelines"]
