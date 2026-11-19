# Privacy

Smart Expense Intelligence handles personal financial data, so privacy rules are part of the design (PRD §17.2–17.3). This page describes what the application stores and how it is protected.

## Data used by this project

- **Training and demo data are synthetic.** They come from a seeded generator (`data_generator/`). No real personal financial data is used to train models ([ADR-0008](adr/0008-synthetic-data-only.md)).
- Public datasets are used only for comparison, and only after their source and license are recorded in `docs/DATA_SOURCES.md`.

## What the application stores

- Account: email, password hash (Argon2id), display name, timezone, budget period start day, consent flag.
- Transactions you enter or import: date, description, amount, type, payment method, merchant, category, notes.
- Derived data: predicted categories, anomalies, forecasts, recurring series, insights, notifications, and your feedback (corrections, alert confirmations).

## What it never stores

- Card numbers, bank credentials, or national ID numbers. If a description contains a 13–19 digit number, it is masked to the last 4 digits (`****1234`) **before** it is saved.
- Bank logins or connections. There is no bank integration.

## Logs and analytics

- Logs never contain descriptions, merchant names, notes, amounts tied to a user, emails, passwords, tokens, or raw CSV content. A test checks this with a sentinel value.
- Analytics exports and logs use a pseudonymous ID (HMAC-SHA256 with a secret key) instead of your user ID or email.

## Consent

`training_consent` is off by default. In this release, user data is **not** used for training, even with consent; the flag exists so the rule is enforced in the data model.

## Deleting your account

Deleting your account removes all your rows from the application database (cascade). Your pseudonymized rows in the analytics store are purged within 24 hours. You can also export your data before deleting (FR-16).

## Demo deployment

The public demo holds synthetic data only. Accounts registered on the demo are labelled "demo, may be wiped" and are wiped every 30 days. Do not enter real financial data in the demo.
