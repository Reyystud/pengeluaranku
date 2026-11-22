# TODO

Things decided but not done. Move an item to `PROGRESS.md` when a task starts.

## Deploy to reyy.space (decided 2026-11-22, not started)

Domain `reyy.space` is active in the Hostinger account (expires 2027-03-07). The account has no hosting plan, website or VPS yet, so nothing is deployed.

Choose one target (undecided):

1. Run on the owner's laptop with `docker compose` and a Cloudflare Tunnel. Free; needs the reyy.space nameservers moved to Cloudflare; only up while the laptop is on.
2. A free VPS elsewhere (for example Oracle Cloud Always Free). DNS stays at Hostinger (A record, set through the Hostinger MCP). Free, up 24 hours, needs a card for verification.
3. A Hostinger VPS. KVM 2 (2 vCPU, 8 GB, 100 GB) is Rp252.900 for the first month, Rp407.900/month after; KVM 1 (4 GB) is Rp193.900 then Rp320.900. Do not buy without the owner's explicit approval of the plan and price.

A Hostinger shared/Node plan only hosts the frontend, so it does not make login and data work without a backend somewhere else.

Work that is the same for every target and costs nothing:

- [ ] Production frontend image (`next build`, not the dev server).
- [ ] Production compose file: postgres, backend (migrations on start), ml-service, frontend, and Caddy for automatic HTTPS on reyy.space; `COOKIE_SECURE=true`; mlflow, Grafana and Prometheus left out.
- [ ] Secrets (`JWT_SECRET`, database password, demo password) created on the server, never committed.
- [ ] Model for the ML service: `models/` is gitignored; decide how the baseline gets onto the server, or accept `needs_review` for every transaction.
- [ ] Set `INTERNAL_OIDC_AUDIENCE`, `CORS_ORIGINS` and the cookie domain for reyy.space; check `APP_ENV=demo` rules.
- [ ] DNS records for reyy.space (A record, or Cloudflare nameservers for option 1).
- [ ] Smoke test after deploy (`/readyz`, register, add a transaction) and note the result in `PROGRESS.md`.

## Finish T-40 to T-46 records

- [ ] `MODEL_EVALUATION.md` section 5 (IndoBERT: not shipped; test macro-F1 0.9642 vs 0.9685, unseen 0.6901 vs 0.5334, RAM 2.17 GiB, MLflow run `7cbbba4cb53046199baf913f106e1251`).
- [ ] DECISIONS rows and PRD addenda for T-40, T-42, T-43, T-44; `PROGRESS.md` entries and table rows for T-40 to T-46.
- [ ] One full `make check`, then `pre-commit run --all-files` twice.

## Known gaps (see `docs/VERIFICATION.md`)

- [ ] Run the k6 load test and cold-start scenario against a real stack.
- [ ] `pip-audit` and `npm audit` in CI; implement `purge-deleted-users`.
- [ ] Run `make demo` end to end and the compose-based `e2e.yml` once.
- [ ] Data export (FR-16, "Could").
- [ ] Independent reviewer for T-46; record the demo video (script in `DEMO_SCRIPT.md`).
