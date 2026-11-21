# MLflow tracking + registry server (PRD 16.7). Version matches uv.lock.
FROM python:3.12-slim
ARG MLFLOW_VERSION=3.18.0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir "mlflow==${MLFLOW_VERSION}" \
    && useradd --system --uid 10001 --create-home mlflow \
    && mkdir /mlflow && chown mlflow /mlflow
USER mlflow
WORKDIR /mlflow
EXPOSE 5000
# Artifacts are proxied through the server (clients need no access to its disk).
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000", \
     "--backend-store-uri", "sqlite:////mlflow/mlflow.db", \
     "--artifacts-destination", "/mlflow/artifacts", "--serve-artifacts", \
     "--allowed-hosts", "*"]
