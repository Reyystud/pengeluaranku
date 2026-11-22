# Runbook

For an engineer who did not build this system (PRD 18.8). Every alert links to one entry below
(`runbook:` annotation in `monitoring/prometheus/alerts.yml`, documentation text in
`infrastructure/terraform/monitoring.tf`). Each entry reads **Symptom → Check → Action → Escalate
when**, and ends with a **Drill** line: what was actually done to test it, and what is still
untested. A Drill line that says "not drilled" means nobody has run the steps; treat them as a
starting point.

Local commands use the compose stack (`make up`, `make up-events`, `make up-observability`).
GCP commands assume `gcloud` is logged in to the project and `REGION` is the Cloud Run region.

| Alert | Entry |
|---|---|
| `BackendLatencyP95High`, `MlInferenceLatencyP95High`, Cloud Monitoring "P95 latency" | [Inference latency P95 high](#inference-latency-p95-high) |
| `High5xxRate`, Cloud Monitoring "5xx" | [Backend 5xx rate high](#backend-5xx-rate-high) |
| `MlCircuitOpen`, Cloud Monitoring "ML circuit open" | [ML circuit open](#ml-circuit-open) |
| `OutboxBacklogGrowing` (local only) | [Outbox backlog growing](#outbox-backlog-growing) |
| Cloud Monitoring "DLQ" | [DLQ messages > 0](#dlq-messages--0) |
| `JobFailed`, Cloud Monitoring "job failed" | [Job failed](#job-failed) |
| `ModelLoadFailure` | [Model load failure / hash mismatch](#model-load-failure--hash-mismatch) |
| Cloud Monitoring "data drift detected" | [Data drift](#data-drift) |
| none yet | [Correction rate rising](#correction-rate-rising), [Data-quality gate failed](#data-quality-gate-failed), [Forecast WAPE high on closed periods](#forecast-wape-high-on-closed-periods) |

Procedure used by several entries: [Roll back a model](#roll-back-a-model).

---

## Inference latency P95 high

**Symptom.** P95 of `http_request_duration_seconds{service="backend"}` above 0.5 s, or of
`inference_duration_seconds` above 0.2 s, for 10 minutes.

**Check.**
1. Grafana "Service health" and "Model health": is it the backend or the ML service, and since when?
2. Was a model promoted or a service deployed at that time? `docs/ops/rollback-log.md` and the
   deploy history of the workflow run.
3. Request shape: batch size (CSV import preview classifies in one batch call) and request rate.
4. Instance count and CPU of the service; cold starts show as a latency spike after a quiet period
   (Cloud Run min instances are 0 in `infrastructure/terraform/cloud_run.tf`).

**Action.**
- Correlated with a promotion: [roll back the model](#roll-back-a-model).
- Correlated with a deploy: `infrastructure/deploy/deploy.sh rollback` (traffic back to the
  recorded revisions; it does not revert the database schema).
- Cold starts or load, GCP: raise the minimum instances temporarily,
  `gcloud run services update ml-service --region REGION --min-instances=1`, and set it back in
  Terraform afterwards so the state does not drift.

**Escalate when** the latency stays above the SLO 30 minutes after rollback or scaling, or when
transactions fail instead of slowing down (see [ML circuit open](#ml-circuit-open): saving never
depends on the ML service).

**Drill.** The alert rules were tested with a simulated incident: `make alerts-test` feeds
synthetic histograms (all requests between 0.5 s and 1 s) and checks that
`BackendLatencyP95High` stays quiet at 8 minutes, fires at 20 minutes with the link to this entry,
and that fast traffic never fires; the mutation check (raising the threshold) makes the test
fail. The Check and Action steps were not drilled against a real slow service. The scale-up
command was not run.

---

## Backend 5xx rate high

**Symptom.** More than 2% of backend requests return 5xx for 5 minutes.

**Check.**
1. Grafana "Service health": which endpoint and status? Backend logs for the `request_id` of a
   failing request (logs carry a pseudonymous user id, never raw data).
2. Dependencies: `curl localhost:8000/readyz` locally (checks database and Redis); Cloud SQL
   status in GCP.
3. A deploy just before the alert? A migration that ran in the same release?

**Action.**
- Deploy-related: `infrastructure/deploy/deploy.sh rollback`. The release process is expand then
  contract, so the previous revision works with the current schema.
- Database or Redis down: restore the dependency; the backend recovers without a restart.
- The ML service being down does not cause 5xx on saving; if it appears to, that is a bug (PRD
  6.3), collect the `request_id` and escalate.

**Escalate when** the rate is not falling 15 minutes after rollback, or any data loss is suspected.

**Drill.** Rule tested with synthetic series by `make alerts-test` (3% fires with this entry's
link, 1% stays quiet). The Check and Action steps were not drilled. Until this task, this alert
linked to the wrong entry (`#job-failed`); fixed.

---

## ML circuit open

**Symptom.** `ml_circuit_state` is 2 for 5 minutes. New transactions are saved with
`category_status = needs_review` and `ml_error = unavailable` or `circuit_open`; users see them in
the review queue. Nothing is lost.

**Check.**
1. ML service: `curl localhost:8080/readyz` (200 with `"classifier":"ok"` means a model is
   loaded; 503 means no model) and `docker compose ps ml-service`.
2. `model_load_failures_total` and the entry [Model load failure](#model-load-failure--hash-mismatch).
3. Recent deploy or promotion? [rollback-log](ops/rollback-log.md).
4. Backend log line `ml circuit open: call skipped (classify)` confirms the breaker is the cause.

**Action.**
- Service down or crashing: restart or redeploy it (`docker compose start ml-service`; in GCP
  redeploy the previous revision). The breaker closes by itself: after 30 seconds it lets one call
  through and closes when that call succeeds. No backend restart is needed.
- Bad model version: [roll back the model](#roll-back-a-model).
- After recovery, transactions stuck in `needs_review` can be re-run one by one with
  `POST /api/v1/transactions/{id}/recategorize`. The bulk job
  `/internal/jobs/recategorize-needs-review` is planned in T-37 and does not exist yet.

**Escalate when** the circuit stays open 15 minutes after the ML service reports ready.

**Drill (2026-11-22, local compose stack).** Stopped `ml-service`, created 6 transactions. After
5 failures the circuit opened: the 6th request skipped the call (`outcome="circuit_open"`),
`ml_circuit_state` was 2, all six were saved as `needs_review` (`source=fallback`), and the log line
above appeared. Restarted `ml-service`: `/readyz` was 200, about 40 seconds later the next
transaction was `auto_apply` from the model and the circuit was 0, with no backend restart. Not
drilled: the 5-minute alert delay on a real Prometheus (the rule itself is tested by `make
alerts-test`), the GCP alert (log-based, never applied), and the bulk re-categorisation.

---

## Outbox backlog growing

**Symptom.** `outbox_oldest_age_seconds` above 300 for 5 minutes (alert exists locally only; GCP has
no application metrics scraper). Events are written in the same database transaction as the data
(outbox), so nothing is lost; downstream effects (anomaly scoring, recurring detection) are late.

**Check.**
1. `curl -s localhost:8000/metrics | grep ^outbox`: `outbox_pending` and the age.
2. Worker log: `outbox relay failed (<ErrorType>); retry in Ns`. `HTTPStatusError` often means the
   topic or subscription does not exist; `ConnectError` means the broker is unreachable.
3. Broker: `docker compose ps pubsub-emulator`; in GCP Pub/Sub status and the worker's IAM
   (`roles/pubsub.publisher`).

**Action.**
- Local emulator restarted: it keeps topics in memory only, so after any restart run
  `docker compose --profile events run --rm pubsub-init` (idempotent). The relay retries with
  backoff up to 30 seconds and drains by itself afterwards.
- Broker down: restore it. Relay and consumers are idempotent, so no cleanup is needed.
- IAM: fix the binding in Terraform and re-apply.

**Escalate when** the backlog still grows after the broker is healthy and the topics exist.

**Drill (2026-11-22, local, `EVENT_BUS=pubsub`).** With the emulator up one event was pending for
8 seconds while the worker logged `HTTPStatusError` retries: the emulator had been restarted earlier
and had lost its topics. Stopped the emulator and created 3 more transactions: `outbox_pending` 4,
oldest 44 s then 90 s, log `ConnectError; retry in 30s`. Started the emulator: nothing drained
(topics still missing). `pubsub-init` recreated them and within 40 seconds `outbox_pending` was 0.
That is where the topics instruction above comes from. Not drilled: GCP IAM failure.

---

## DLQ messages > 0

**Symptom.** Cloud Monitoring: undelivered messages in `transaction-events-dlq-inspect` above 0. An
event failed delivery repeatedly (the consumer returned 5xx) and was moved to the dead-letter topic.

**Check.**
1. Pull without acknowledging: `gcloud pubsub subscriptions pull transaction-events-dlq-inspect --limit=5`
   (add `--auto-ack` only when done with the message). Locally, pull from the emulator
   subscription `transaction-events-dlq-inspect`.
2. Backend log for the same `event_id`: the consumer's exception type.
3. Invalid events get a 400 `INVALID_EVENT` and are not retried; a message in the DLQ is an
   exception in a consumer.

**Action.** Fix the bug and deploy. Re-publishing the dead messages to the main topic is not
automated: the `make dlq-replay` mentioned in PRD 18.8 does not exist yet. Consumers are idempotent
(`processed_events`), so republishing the same event by hand is safe.

**Escalate when** the same event type reaches the DLQ again after the fix.

**Drill.** Not drilled; the DLQ path was only exercised by the T-33 unit and integration tests.

---

## Job failed

**Symptom.** `jobs_runs_total{status="error"}` increased in the last hour, or a Cloud Run job
execution failed.

**Check.**
1. `job_runs` table: latest rows for the job, column `error`.
2. Cloud Run job logs for that execution (`gcloud run jobs executions list --job pipelines --region REGION`).
3. Jobs process users in chunks and continue after a per-user error; a failed run usually means
   something shared broke (database, a model, a dependency).

**Action.** Fix the cause and re-run the job for the same date: every job is idempotent (PRD 15.1).
`make jobs-run JOB=<name>` is a stub until T-37; until then use the Cloud Run job execution with the
job name argument.

**Escalate when** the same job fails twice after the fix.

**Drill.** Rule tested by `make alerts-test`. The jobs framework arrives in T-37; nothing here has
run on a real job.

---

## Model load failure / hash mismatch

**Symptom.** `model_load_failures_total` increased; `/readyz` of the ML service is 503 when no
model was ever loaded. A running service keeps serving its current model when a later load fails.

**Check.**
1. Reason label of the metric (`SOURCE_UNAVAILABLE`, hash mismatch, unreadable artifact).
2. MLflow: does the alias exist (`production`)? Version metadata hash against the artifact in the
   registry store.
3. Did anyone edit the artifact or move an alias by hand?

**Action.** Re-register the artifact from its training run, or [roll back the alias](#roll-back-a-model).
Never bypass the hash check.

**Escalate when** the registered artifact and its recorded hash disagree and nobody changed it.

**Drill (2026-11-22, local).** The ML service was started while MLflow had no `production` alias:
`/readyz` returned 503, `model_load_failures_total{reason="SOURCE_UNAVAILABLE"}` was 1. After
promoting a version it loaded at the next poll tick (see rollback drill). The hash-mismatch case
was not drilled here.

---

## Data drift

**Symptom.** The daily `drift-report` job found a key feature with PSI above 0.25, or the share of
unseen merchants above 2x its 28-day median; log line `drift_summary` with `status: "drift"`.

**Check.**
1. Open `drift/<date>/report.html` (local `data/reports/`, GCP the `<project>-reports` bucket) and
   `summary.json`: which features, how large.
2. Unseen-merchant share: is the backend sending the same normalised `merchant_key` that training
   used? A different normalisation inflates the share (this happened in the T-35 test harness).
3. Correction rate in Grafana "Model health": drift alone is a warning, not a verdict.

**Action.** Drift alone never promotes anything (PRD 16.6). If drift comes with a rising correction
rate: add merchant aliases (`config/merchant_aliases.yaml`), then train early (`make train`), and let
the gates decide.

**Escalate when** drift persists after retraining.

**Drill.** The job was run on synthetic traffic that matched and on traffic that was shifted
(amounts ×6, all cash): matched gave `ok`, shifted gave `drift` with the right features flagged.
Retraining as an action was not drilled; the GCP alert was never applied.

---

## Roll back a model

Moves alias `production` back to the previous version. No image build, no redeploy (PRD 16.5).

```bash
make rollback MODEL=transaction-classifier REASON="why"   # a reason is required
# or directly:
uv run python -m pipelines rollback --reason "why" --actor "your name"
```

The command swaps `production` and `previous`, tags the versions in MLflow and appends a row to
`docs/ops/rollback-log.md`. Running it again undoes it. The ML service notices the new alias at its
next poll: by default **up to `MODEL_POLL_INTERVAL_S` seconds (300 in `.env.example`)**; restart the
service to apply it at once (`docker compose restart ml-service`).

**Drill (2026-11-22, local MLflow server with 2 real registered versions).** Promoted v1 then v2
(forced, both without a gate tag, because the local versions were not produced by the gated
pipeline), rolled back (production v2 → v1), rolled back again (v1 → v2): three alias moves and
four rows in `docs/ops/rollback-log.md`. The ML service, polling every 300 s, loaded v1 at the next
tick after the rollback and v2 at the tick after the second rollback, with no restart and no
rebuild. Delay observed: up to one poll interval (about 5 minutes). Those four log rows are drill
rows (actor `drill`) on a local registry, not production history.

---

## Correction rate rising

No alert yet (it needs the T-35/T-37 jobs to feed a metric). **Check** the unseen-merchant share
and the most corrected categories against the training data ([Data drift](#data-drift)).
**Action:** collect data, train early, extend `config/merchant_aliases.yaml`. **Drill:** not drilled.

## Data-quality gate failed

The training pipeline stops when validation fails. **Check** the validation report and the
quarantine counts of the run. **Action:** fix the source data and re-run; never lower the gate to
get a model through. **Drill:** not drilled.

## Forecast WAPE high on closed periods

Forecasting arrives with T-38 to T-40; this entry only records the intent. **Check** WAPE by
archetype and history length, then recurring detection. **Action:** retrain; the planned kill switch
`FORECAST_FORCE_BASELINE=true` (in `.env.example`) forces the run-rate baseline once the
forecaster exists. **Drill:** not drilled.
