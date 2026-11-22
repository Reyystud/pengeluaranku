# Load test (T-43)

`main.js` is a k6 script for the traffic mix in PRD 21.2 against the SLOs in PRD 5.3.

```bash
make loadtest                                   # against http://localhost:8000
make loadtest TARGET_URL=https://<backend-url>  # against a deployment
make loadtest SCENARIO=cold TARGET_URL=...      # one request after the instances idled to zero
```

`make loadtest` uses a local `k6` binary, or the `grafana/k6` image when `k6` is not installed.

## Status

The script and thresholds exist. **No run has been made yet**, so there are no results:
`[TBD after run]`. A result needs a running stack (`make demo` locally, or the Cloud Run deployment),
k6, and for the cold-start figure a Cloud Run service with `min_instances = 0` that has been idle.
Record the run here and in `docs/MODEL_EVALUATION.md` with the date, target, k6 summary and commit.

## Reading the numbers

- k6 measures from the client, so latencies include the network. The SLOs are server-side; use
  the backend's own `http_request_duration_seconds` (Grafana, PRD 18) for the SLI and k6 for load.
- Registration happens in `setup()`; those requests carry `kind:setup` and are not in the thresholds.
- Cold starts are reported by the `cold` scenario (`cold_start_ms`) and are excluded from the P95 SLOs (5.3).
