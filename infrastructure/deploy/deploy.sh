#!/usr/bin/env bash
# Cloud Run deploy steps used by .github/workflows/deploy.yml (PRD 19.5).
#
#   deploy.sh migrate    run Alembic as the `migrate` Cloud Run job with the new backend image
#   deploy.sh deploy     record the live revisions, roll every service to the new image digest
#   deploy.sh rollback   send traffic back to the revisions recorded by `deploy`
#
# Images are referenced by digest, never by tag. Needs gcloud authenticated as the deployer
# service account. Environment: PROJECT_ID, REGION, REGISTRY (<region>-docker.pkg.dev/<project>/sei),
# TAG (git SHA the build pushed). STATE_DIR holds the recorded revisions (default: ./.deploy-state).
#
# Database migrations are forward-only: they must stay compatible with the previous revision
# (expand, then contract in a later release), because a rollback does not revert the schema.
set -euo pipefail

: "${PROJECT_ID:?}" "${REGION:?}" "${REGISTRY:?}" "${TAG:?}"
STATE_DIR="${STATE_DIR:-.deploy-state}"
REVISIONS_FILE="${STATE_DIR}/previous-revisions.txt"

# service name -> image repository name. `worker` runs the backend image (PRD 6.5).
SERVICES=("ml-service:ml-service" "mlflow:mlflow" "backend:backend" "worker:backend" "frontend:frontend")

digest_ref() { # <image> -> <registry>/<image>@sha256:...
  local digest
  digest="$(gcloud artifacts docker images describe "${REGISTRY}/$1:${TAG}" \
    --format='value(image_summary.digest)')"
  [[ "${digest}" == sha256:* ]] || { echo "no digest for $1:${TAG}" >&2; return 1; }
  echo "${REGISTRY}/$1@${digest}"
}

migrate() {
  local image
  image="$(digest_ref backend)"
  gcloud run jobs update migrate --project "${PROJECT_ID}" --region "${REGION}" --image "${image}"
  gcloud run jobs execute migrate --project "${PROJECT_ID}" --region "${REGION}" --wait
}

deploy() {
  mkdir -p "${STATE_DIR}"
  : > "${REVISIONS_FILE}"
  local entry service image ref previous
  # Resolve every digest first: a missing image must stop the run before anything changes.
  declare -A refs=()
  for entry in "${SERVICES[@]}"; do
    refs["${entry%%:*}"]="$(digest_ref "${entry##*:}")"
  done
  for entry in "${SERVICES[@]}"; do
    service="${entry%%:*}"
    previous="$(gcloud run services describe "${service}" --project "${PROJECT_ID}" \
      --region "${REGION}" --format='value(status.latestReadyRevisionName)')"
    echo "${service} ${previous}" >> "${REVISIONS_FILE}"
  done
  for entry in "${SERVICES[@]}"; do
    service="${entry%%:*}"
    gcloud run services update "${service}" --project "${PROJECT_ID}" --region "${REGION}" \
      --image "${refs[${service}]}"
    # A previous rollback pins traffic to one revision; this puts it back on the newest.
    gcloud run services update-traffic "${service}" --project "${PROJECT_ID}" \
      --region "${REGION}" --to-latest
  done
  image="$(digest_ref pipelines)" || image=""
  if [[ -n "${image}" ]]; then
    gcloud run jobs update pipelines --project "${PROJECT_ID}" --region "${REGION}" --image "${image}"
  fi
}

rollback() {
  [[ -s "${REVISIONS_FILE}" ]] || { echo "nothing recorded to roll back to" >&2; return 1; }
  local service revision failed=0
  while read -r service revision; do
    if [[ -z "${revision}" ]]; then
      echo "skip ${service}: no previous revision"
      continue
    fi
    gcloud run services update-traffic "${service}" --project "${PROJECT_ID}" \
      --region "${REGION}" --to-revisions "${revision}=100" || failed=1
  done < "${REVISIONS_FILE}"
  return "${failed}"
}

case "${1:-}" in
  migrate) migrate ;;
  deploy) deploy ;;
  rollback) rollback ;;
  *) echo "usage: $0 migrate|deploy|rollback" >&2; exit 2 ;;
esac
