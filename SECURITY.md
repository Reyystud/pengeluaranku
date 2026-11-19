# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Report them privately through GitHub's **"Report a vulnerability"** button (Security tab → Private vulnerability reporting) on this repository.

Include what you found, how to reproduce it, and the impact you expect. You should get a reply within 7 days.

## Scope

This is a portfolio project. The public demo holds synthetic data only. In scope: the code in this repository and the demo deployment. Out of scope: denial-of-service testing, social engineering, and third-party services.

## Security controls (summary)

Full detail in [PRD §17](docs/PRD.md#17-security-and-privacy).

- HTTPS only with HSTS; strict security headers (CSP, `nosniff`, `frame-ancestors 'none'`).
- Passwords hashed with Argon2id; short-lived access tokens; rotating refresh tokens with reuse detection, stored as SHA-256 hashes.
- Every resource is scoped by `user_id`; cross-user access returns 404; a BOLA/IDOR test suite covers every endpoint that takes an ID.
- ML service is private; service-to-service calls use Google OIDC tokens and one least-privilege service account per service.
- Secrets live in Secret Manager, never in the repository; gitleaks runs in CI.
- Locked dependencies; pip-audit, npm audit, and Trivy image scans in CI; Dependabot weekly.
- Rate limiting on auth and write endpoints; request size limits; CSV export is protected against formula injection.
- Model artifacts are hash-verified at load; registry writes are limited to the pipelines service account.
- No sensitive data in logs (verified by a sentinel test).
