// k6 load test (PRD 21.2, SLOs in 5.3). Not run in CI; see loadtest/README.md.
//
//   k6 run -e TARGET_URL=http://localhost:8000 loadtest/main.js
//   k6 run -e SCENARIO=cold -e TARGET_URL=https://<backend> loadtest/main.js   (after idling to 0 instances)
//
// Mix: 20% create transaction (includes synchronous categorization), 50% list, 20% dashboard
// summary, 10% category list. Latencies are measured from the client, so they include the network;
// the SLOs in 5.3 are server-side. Treat the thresholds as an upper bound, not as the SLI itself.
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend } from "k6/metrics";

const BASE = (__ENV.TARGET_URL || "http://localhost:8000").replace(/\/$/, "");
const API = `${BASE}/api/v1`;
const USERS = Number(__ENV.USERS || 20);
const RUN = `${Date.now()}`;
const PASSWORD = __ENV.LOAD_PASSWORD || `Lt-${RUN}-pass-phrase`;
const coldStart = new Trend("cold_start_ms", true);

const MERCHANTS = ["Warung Makan Sari", "Indomaret", "Gojek", "Tokopedia", "Netflix", "PLN", "Kopi Kenangan"];

export const options =
  __ENV.SCENARIO === "cold"
    ? { scenarios: { cold: { executor: "shared-iterations", vus: 1, iterations: 1 } } }
    : {
        scenarios: {
          mix: {
            executor: "ramping-vus",
            stages: [
              { duration: "30s", target: USERS },
              { duration: __ENV.DURATION || "3m", target: USERS },
              { duration: "15s", target: 0 },
            ],
          },
        },
        thresholds: {
          "http_req_failed{kind:api}": ["rate<0.01"], // success >= 99% (5.3)
          "http_req_duration{name:create_tx}": ["p(95)<500"], // POST /transactions P95 (5.3)
          "http_req_duration{name:list_tx}": ["p(95)<300"], // CRUD P95 (5.3)
          "http_req_duration{name:summary}": ["p(95)<300"],
          "http_req_duration{name:categories}": ["p(95)<300"],
        },
      };

const headers = (token) => ({ "Content-Type": "application/json", Authorization: `Bearer ${token}` });

export function setup() {
  if (__ENV.SCENARIO === "cold") return {};
  const tokens = [];
  for (let i = 0; i < USERS; i++) {
    const res = http.post(
      `${API}/auth/register`,
      JSON.stringify({ email: `load-${RUN}-${i}@example.test`, password: PASSWORD, display_name: `Load ${i}` }),
      { headers: { "Content-Type": "application/json" }, tags: { name: "register", kind: "setup" } },
    );
    if (res.status === 201 || res.status === 200) tokens.push(res.json("access_token"));
  }
  if (tokens.length === 0) throw new Error("no user could be registered; is the target reachable?");
  return { tokens };
}

export default function (data) {
  if (__ENV.SCENARIO === "cold") {
    // First request after the instances scaled to zero: report it separately (5.3).
    const started = Date.now();
    const ready = http.get(`${BASE}/readyz`, { tags: { name: "cold_readyz", kind: "cold" } });
    coldStart.add(Date.now() - started);
    check(ready, { "ready after cold start": (r) => r.status === 200 });
    return;
  }
  const token = data.tokens[(__VU - 1) % data.tokens.length];
  const params = (name) => ({ headers: headers(token), tags: { name, kind: "api" } });
  const roll = Math.random();
  if (roll < 0.2) {
    const body = {
      transaction_type: "expense",
      amount: String(10000 + Math.floor(Math.random() * 400000)),
      description: `${MERCHANTS[Math.floor(Math.random() * MERCHANTS.length)]} ${Math.floor(Math.random() * 1000)}`,
      transaction_date: new Date().toISOString(),
    };
    const create = params("create_tx");
    create.headers["Idempotency-Key"] = `k6-${RUN}-${__VU}-${__ITER}`; // required on POST /transactions (13.1.5)
    const res = http.post(`${API}/transactions`, JSON.stringify(body), create);
    check(res, { "created": (r) => r.status === 201 });
  } else if (roll < 0.7) {
    check(http.get(`${API}/transactions?limit=20`, params("list_tx")), { "listed": (r) => r.status === 200 });
  } else if (roll < 0.9) {
    check(http.get(`${API}/analytics/summary`, params("summary")), { "summary": (r) => r.status === 200 });
  } else {
    check(http.get(`${API}/categories`, params("categories")), { "categories": (r) => r.status === 200 });
  }
  sleep(1 + Math.random());
}
