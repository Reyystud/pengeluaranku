import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import { jsonResponse, renderWithQuery } from "@/test/utils";
import { POLL_MS } from "./hooks";
import { NotificationBell } from "./NotificationBell";
import { NotificationsView } from "./NotificationsView";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => ({ timeZone: "Asia/Jakarta" }) }));

const note = (id: string, read: boolean) => ({
  id,
  type: "budget_threshold",
  title: `Groceries budget at 80% (${id})`,
  body: "You have used 85.0% of your Groceries budget this period.",
  link: "/budgets",
  payload: {},
  read_at: read ? "2026-11-20T03:00:00Z" : null,
  created_at: "2026-11-20T02:00:00Z",
});

describe("notifications", () => {
  const fetchMock = vi.fn();
  let unread = 2;
  const calls = (method: string, path: string) =>
    fetchMock.mock.calls.filter(
      ([url, init]) => String(url).includes(path) && (init?.method ?? "GET") === method,
    );

  beforeEach(() => {
    setToken("t");
    unread = 2;
    fetchMock.mockReset().mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url.includes("/unread-count")) return jsonResponse({ count: unread });
      if (url.includes("/read-all")) return jsonResponse({ updated: 2 });
      if (method === "POST" && url.includes("/read")) return jsonResponse(note("n1", true));
      if (url.includes("/notifications"))
        return jsonResponse({ items: [note("n1", false), note("n2", true)], next_cursor: null });
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("puts the unread count in the bell's accessible name", async () => {
    renderWithQuery(<NotificationBell />);
    expect(await screen.findByRole("link", { name: "Notifications, 2 unread" })).toHaveAttribute(
      "href",
      "/notifications",
    );
  });

  it("has a plain name when nothing is unread", async () => {
    unread = 0;
    renderWithQuery(<NotificationBell />);
    await waitFor(() => expect(calls("GET", "/unread-count")).toHaveLength(1));
    expect(screen.getByRole("link", { name: "Notifications" })).toBeInTheDocument();
  });

  it("polls every 60 seconds (FR-14.04)", async () => {
    expect(POLL_MS).toBe(60_000);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithQuery(<NotificationBell />);
    await waitFor(() => expect(calls("GET", "/unread-count")).toHaveLength(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS + 100);
    });
    await waitFor(() => expect(calls("GET", "/unread-count").length).toBeGreaterThanOrEqual(2));
  });

  it("lists notifications, marks one as read and all as read", async () => {
    const user = userEvent.setup();
    renderWithQuery(<NotificationsView />);
    expect(await screen.findByText(/Groceries budget at 80% \(n1\)/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Open" })[0]).toHaveAttribute("href", "/budgets");
    await user.click(screen.getByRole("button", { name: "Mark as read" })); // only the unread one has it
    await waitFor(() => expect(calls("POST", "/notifications/n1/read")).toHaveLength(1));
    await user.click(screen.getByRole("button", { name: "Mark all as read" }));
    await waitFor(() => expect(calls("POST", "/notifications/read-all")).toHaveLength(1));
  });

  it("filters to unread only", async () => {
    const user = userEvent.setup();
    renderWithQuery(<NotificationsView />);
    await screen.findByText(/\(n1\)/);
    await user.click(screen.getByRole("button", { name: "Unread only" }));
    await waitFor(() =>
      expect(
        calls("GET", "/notifications").some(([u]) => String(u).includes("unread_only=true")),
      ).toBe(true),
    );
  });

  it("shows an empty state", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.includes("/unread-count")
        ? jsonResponse({ count: 0 })
        : jsonResponse({ items: [], next_cursor: null }),
    );
    renderWithQuery(<NotificationsView />);
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
  });
});
