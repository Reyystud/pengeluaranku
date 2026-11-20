import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getToken, setAuthLostHandler, setToken } from "@/auth/token";
import { api } from "./client";
import { ApiError } from "./errors";

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });

describe("api client", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
    setToken("old");
  });
  afterEach(() => {
    setAuthLostHandler(null);
    vi.unstubAllGlobals();
  });

  it("sends the in-memory token and same-origin /api/v1 URLs", async () => {
    fetchMock.mockResolvedValueOnce(json({ ok: true }));
    await api.get("/transactions", { q: "kopi", category: ["a", "b"], empty: "", none: null });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/transactions?q=kopi&category=a&category=b");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer old");
    expect(init.credentials).toBe("same-origin");
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ code: "UNAUTHENTICATED" }, 401))
      .mockResolvedValueOnce(json({ access_token: "new", expires_in: 900 }))
      .mockResolvedValueOnce(json({ items: [] }));
    expect(await api.get("/transactions")).toEqual({ items: [] });
    expect(getToken()).toBe("new");
    const retry = fetchMock.mock.calls[2] as [string, RequestInit];
    expect((retry[1].headers as Record<string, string>).Authorization).toBe("Bearer new");
  });

  it("shares one refresh between concurrent 401s", async () => {
    let refreshes = 0;
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (url.endsWith("/auth/refresh")) {
        refreshes++;
        return json({ access_token: "new", expires_in: 900 });
      }
      const auth = (init.headers as Record<string, string>).Authorization;
      return auth === "Bearer new" ? json({ ok: true }) : json({ code: "UNAUTHENTICATED" }, 401);
    });
    await Promise.all([api.get("/a"), api.get("/b"), api.get("/c")]);
    expect(refreshes).toBe(1);
  });

  it("drops the session when refresh fails (PRD 8.3: redirect to /login)", async () => {
    const lost = vi.fn();
    setAuthLostHandler(lost);
    fetchMock
      .mockResolvedValueOnce(json({ code: "UNAUTHENTICATED" }, 401))
      .mockResolvedValueOnce(json({ code: "UNAUTHENTICATED" }, 401));
    await expect(api.get("/transactions")).rejects.toMatchObject({ status: 401 });
    expect(lost).toHaveBeenCalledOnce();
    expect(getToken()).toBeNull();
  });

  it("anonymous calls (login) never trigger a refresh", async () => {
    fetchMock.mockResolvedValueOnce(
      json({ code: "INVALID_CREDENTIALS", detail: "Wrong email or password." }, 401),
    );
    await expect(api.post("/auth/login", {}, { anonymous: true })).rejects.toMatchObject({
      code: "INVALID_CREDENTIALS",
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("turns problem+json into ApiError with request_id and field errors", async () => {
    fetchMock.mockResolvedValueOnce(
      json(
        {
          code: "VALIDATION_ERROR",
          detail: "Check the fields.",
          request_id: "req-1",
          errors: [{ field: "amount", code: "INVALID_VALUE", message: "Too big" }],
        },
        422,
      ),
    );
    const error = (await api.post("/transactions", {}).catch((e) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.requestId).toBe("req-1");
    expect(error.errors[0]?.field).toBe("amount");
  });

  it("a plain-text 5xx (backend down behind the proxy) reads as unreachable, not generic", async () => {
    fetchMock.mockResolvedValueOnce(new Response("Internal Server Error", { status: 500 }));
    await expect(api.get("/x")).rejects.toMatchObject({
      code: "BACKEND_UNREACHABLE",
      message: "Cannot reach the server. Check your connection.",
    });
  });

  it("maps a network failure to NETWORK_ERROR", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("failed"));
    await expect(api.get("/x")).rejects.toMatchObject({ code: "NETWORK_ERROR", status: 0 });
  });

  it("returns undefined for 204", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    expect(await api.delete("/merchant-rules/1")).toBeUndefined();
  });
});
