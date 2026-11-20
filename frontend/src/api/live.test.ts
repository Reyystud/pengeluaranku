// Contract smoke test against a real backend. Skipped unless LIVE_API_URL is set, e.g.
//   LIVE_API_URL=http://127.0.0.1:8000 pnpm test src/api/live.test.ts
// It runs the real client code (headers, idempotency keys, parsing) against the real API.
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import type {
  Anomaly,
  AnomalyPage,
  AuthResponse,
  Budget,
  BudgetList,
  CategorySplit,
  Summary,
  Trends,
  NotificationPage,
  Category,
  CategorizePreviewOut,
  TransactionCreated,
  TransactionPage,
} from "./types";
import { api } from "./client";

const base = process.env.LIVE_API_URL;

// The ML service may be down when this runs; the backend then waits for its timeout first.
const LIVE_TIMEOUT_MS = 30_000;

describe.skipIf(!base)("live API contract", { timeout: LIVE_TIMEOUT_MS }, () => {
  const realFetch = globalThis.fetch;
  beforeAll(() => {
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => realFetch(`${base}${url}`, init));
  });
  afterAll(() => vi.unstubAllGlobals());

  it("register -> categories -> preview -> create -> list -> bulk delete", async () => {
    const email = `live-${crypto.randomUUID().slice(0, 8)}@example.com`;
    const auth = await api.post<AuthResponse>(
      "/auth/register",
      { email, password: `Pw-${crypto.randomUUID()}`, display_name: "Live" },
      { anonymous: true },
    );
    setToken(auth.access_token);

    const categories = await api.get<Category[]>("/categories");
    expect(categories.map((c) => c.slug)).toContain("food_beverage");

    const preview = await api.post<CategorizePreviewOut>("/transactions/categorize-preview", {
      description: "Kopi Kenangan",
      transaction_type: "expense",
      payment_method: "cash",
      amount: "25000.00",
    });
    expect(["auto", "suggested", "needs_review", "rule"]).toContain(preview.category_status);

    const key = crypto.randomUUID();
    const body = {
      transaction_type: "expense",
      amount: "25000.00",
      description: "Kopi Kenangan",
      transaction_date: "2026-11-18",
      payment_method: "cash",
    };
    const created = await api.post<TransactionCreated>("/transactions", body, {
      headers: { "Idempotency-Key": key },
    });
    const replay = await api.post<TransactionCreated>("/transactions", body, {
      headers: { "Idempotency-Key": key },
    });
    expect(replay.id).toBe(created.id); // same key -> same transaction, not a second one
    expect(created.amount).toBe("25000.00"); // money stays a string

    const page = await api.get<TransactionPage>("/transactions", { q: "Kenangan" });
    expect(page.items.map((t) => t.id)).toEqual([created.id]);

    const gone = await api.post<{ deleted: number }>(
      "/transactions/bulk-delete",
      { ids: [created.id] },
      { headers: { "Idempotency-Key": crypto.randomUUID() } },
    );
    expect(gone.deleted).toBe(1);
  });

  it("budgets, analytics and notifications follow the generated types", async () => {
    const auth = await api.post<AuthResponse>(
      "/auth/register",
      {
        email: `live-${crypto.randomUUID().slice(0, 8)}@example.com`,
        password: `Pw-${crypto.randomUUID()}`,
        display_name: "Live",
      },
      { anonymous: true },
    );
    setToken(auth.access_token);
    const budget = await api.post<Budget>("/budgets", {
      category: "groceries",
      limit_amount: "100000",
      alert_thresholds: [80, 100],
    });
    expect(budget.limit_amount).toBe("100000.00");
    expect(budget.status).toBe("healthy");
    const now = new Date().toISOString();
    await api.post(
      "/transactions",
      {
        transaction_type: "expense",
        amount: "90000",
        description: "Supermarket",
        category: "groceries",
        transaction_date: now,
        payment_method: "cash",
      },
      { headers: { "Idempotency-Key": crypto.randomUUID() } },
    );
    const list = await api.get<BudgetList>("/budgets");
    expect(list.items[0]?.status).toBe("warning");
    expect(list.items[0]?.utilization).toBe("90.0");
    const summary = await api.get<Summary>("/analytics/summary", { range: "current_period" });
    expect(summary.expenses).toBe("90000.00");
    const cats = await api.get<CategorySplit>("/analytics/categories");
    expect(cats.items[0]?.slug).toBe("groceries");
    const trend = await api.get<Trends>("/analytics/trends");
    expect(trend.budget_limit).toBeNull(); // the pace line follows the overall budget only
    const unread = await api.get<{ count: number }>("/notifications/unread-count");
    expect(unread.count).toBe(1); // the 80% threshold
    const notes = await api.get<NotificationPage>("/notifications", { unread_only: true });
    expect(notes.items[0]?.type).toBe("budget_threshold");
    await api.post("/notifications/read-all");
    expect((await api.get<{ count: number }>("/notifications/unread-count")).count).toBe(0);
  });

  it("a first, very large expense is scored and the feedback round-trips", async () => {
    const auth = await api.post<AuthResponse>(
      "/auth/register",
      {
        email: `live-${crypto.randomUUID().slice(0, 8)}@example.com`,
        password: `Pw-${crypto.randomUUID()}`,
        display_name: "Live",
      },
      { anonymous: true },
    );
    setToken(auth.access_token);
    await api.post(
      "/transactions",
      {
        transaction_type: "expense",
        amount: "5000000",
        description: "Resto Mewah",
        category: "food_beverage",
        transaction_date: new Date().toISOString(),
        payment_method: "cash",
      },
      { headers: { "Idempotency-Key": crypto.randomUUID() } },
    );
    const page = await api.get<AnomalyPage>("/intelligence/anomalies");
    const spike = page.items.find((a) => a.anomaly_type === "amount_spike");
    expect(spike?.history_level).toBe("limited"); // a brand-new account: category prior only
    expect(spike?.reasons.at(-1)?.code).toBe("LIMITED_HISTORY");
    expect(spike?.transaction?.amount).toBe("5000000.00");
    const done = await api.post<Anomaly>(`/intelligence/anomalies/${spike?.id}/feedback`, {
      action: "dismiss",
      reason: "expected_purchase",
    });
    expect(done.status).toBe("dismissed");
    expect(done.feedback_reason).toBe("expected_purchase");
  });
});
