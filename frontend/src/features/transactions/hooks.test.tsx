import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import { jsonResponse } from "@/test/utils";
import { useDeleteTransactions } from "./hooks";

describe("mutations the API protects with Idempotency-Key (PRD 13.1.4)", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    setToken("t");
    fetchMock.mockReset().mockImplementation(async () => jsonResponse({ deleted: 2 }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("bulk delete sends a fresh key per action", async () => {
    const client = new QueryClient();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useDeleteTransactions(), { wrapper });
    await act(() => result.current.mutateAsync(["a", "b"]));
    await act(() => result.current.mutateAsync(["c"]));
    const keys = fetchMock.mock.calls.map(
      ([, init]) => (init.headers as Record<string, string>)["Idempotency-Key"],
    );
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(keys[1]).toMatch(/^[0-9a-f-]{36}$/);
    expect(keys[0]).not.toBe(keys[1]);
  });
});
