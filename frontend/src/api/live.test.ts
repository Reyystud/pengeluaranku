// Contract smoke test against a real backend. Skipped unless LIVE_API_URL is set, e.g.
//   LIVE_API_URL=http://127.0.0.1:8000 pnpm test src/api/live.test.ts
// It runs the real client code (headers, idempotency keys, parsing) against the real API.
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import type {
  AuthResponse,
  Category,
  CategorizePreviewOut,
  TransactionCreated,
  TransactionPage,
} from "./types";
import { api } from "./client";

const base = process.env.LIVE_API_URL;

describe.skipIf(!base)("live API contract", () => {
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
});
