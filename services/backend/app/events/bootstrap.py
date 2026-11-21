"""``python -m app.events.bootstrap``: create the topics and the push subscription on a Pub/Sub
emulator (PRD 7.11 FR-11.06, 14.3). Idempotent. The GCP deployment creates the same objects with
Terraform (``infrastructure/terraform/pubsub.tf``); this is for local development only.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

TOPIC = "transaction-events"
DLQ = "transaction-events-dlq"
SUBSCRIPTION = "transaction-events-worker"


def _put(client: httpx.Client, path: str, body: dict[str, object]) -> None:
    response = client.put(path, json=body)
    if response.status_code not in (200, 409):  # 409: already exists
        response.raise_for_status()


def bootstrap(client: httpx.Client, project: str, push_endpoint: str) -> None:
    resource = f"projects/{project}"  # resource names inside request bodies
    base = f"/v1/{resource}"
    _put(client, f"{base}/topics/{TOPIC}", {})
    _put(client, f"{base}/topics/{DLQ}", {})
    _put(client, f"{base}/subscriptions/{DLQ}-inspect", {"topic": f"{resource}/topics/{DLQ}"})
    _put(
        client,
        f"{base}/subscriptions/{SUBSCRIPTION}",
        {
            "topic": f"{resource}/topics/{TOPIC}",
            "pushConfig": {"pushEndpoint": push_endpoint},
            "ackDeadlineSeconds": 60,
            "retryPolicy": {"minimumBackoff": "10s", "maximumBackoff": "600s"},
            "deadLetterPolicy": {
                "deadLetterTopic": f"{resource}/topics/{DLQ}",
                "maxDeliveryAttempts": 5,
            },
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.events.bootstrap")
    parser.add_argument("--emulator", default=os.environ.get("PUBSUB_EMULATOR_HOST", ""))
    parser.add_argument("--project", default=os.environ.get("PUBSUB_PROJECT_ID", ""))
    parser.add_argument("--push-endpoint", default=os.environ.get("PUSH_ENDPOINT", ""))
    parser.add_argument("--wait-s", type=float, default=60)
    args = parser.parse_args(argv)
    if not (args.emulator and args.project and args.push_endpoint):
        print(
            "PUBSUB_EMULATOR_HOST, PUBSUB_PROJECT_ID and PUSH_ENDPOINT are required",
            file=sys.stderr,
        )
        return 2
    deadline = time.monotonic() + args.wait_s
    with httpx.Client(base_url=f"http://{args.emulator}", timeout=10) as client:
        while True:
            try:
                bootstrap(client, args.project, args.push_endpoint)
                break
            except httpx.TransportError:  # the emulator is still starting
                if time.monotonic() > deadline:
                    print("the Pub/Sub emulator did not become reachable", file=sys.stderr)
                    return 1
                time.sleep(1)
    print(f"topics {TOPIC}, {DLQ} and subscription {SUBSCRIPTION} are ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
