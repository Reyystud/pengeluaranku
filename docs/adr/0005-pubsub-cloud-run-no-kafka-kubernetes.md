# ADR-0005: Pub/Sub + Cloud Run for events and compute; no Kafka or Kubernetes

- Status: accepted
- Date: 2026-11-19
- PRD sections affected: 3.2, 6.1, 6.3, 7.11, 14.3, 19.3

## Context
Anomaly scoring should run asynchronously after a transaction is created, with at-least-once delivery, retries, and a dead-letter queue. Services need to run with HTTPS and autoscaling at very low cost, since the demo has little traffic and is paid for personally.

## Options considered
1. **Kafka + Kubernetes (GKE)** — powerful and common in large companies; but always-on clusters cost money, need operations work, and are far beyond this scale.
2. **Pub/Sub push subscriptions + Cloud Run services/jobs** — fully managed, scale to zero, push to an HTTP endpoint on the worker, built-in retries and DLQ.
3. **Synchronous scoring in the request path** — simplest; but adds latency to transaction creation and couples it to ML availability.

## Decision
Option 2. The backend writes an outbox row in the same DB transaction as the transaction insert; a relay publishes `transaction.created` to Pub/Sub; a push subscription calls `worker POST /internal/events/transaction`; consumers are idempotent by `event_id`; after 5 attempts messages go to a dead-letter topic. Locally, `EVENT_BUS=inmemory` (or the Pub/Sub emulator) replaces Pub/Sub.

## Consequences
- Positive: managed, cheap, scale-to-zero; demonstrates event-driven design (outbox, idempotency, DLQ) without heavy infra.
- Negative: Pub/Sub has no strict ordering by default → consumers must handle duplicates and out-of-order versions (tested).
- Negative: Cloud Run cold starts affect latency; reported separately from SLOs.
- Revisit if: throughput or ordering requirements outgrow Pub/Sub, or a stream-processing need appears. Kafka/Kubernetes stay listed as future options only.
