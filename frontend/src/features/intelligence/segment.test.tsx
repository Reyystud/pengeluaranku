import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import { jsonResponse, renderWithQuery } from "@/test/utils";
import { IntelligenceView } from "./IntelligenceView";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => ({ timeZone: "Asia/Jakarta" }) }));

const BASE = { complete_periods: 3, required_periods: 2 };
const SEGMENT = {
  ...BASE,
  reason: null,
  segment: {
    id: "segment-1",
    name: "Small everyday spender",
    description: "Many small purchases.",
    traits: [
      {
        feature: "savings_rate",
        direction: "higher",
        percent: 80,
        value: 0.2,
        message: "Your share of income you save is higher than 80% of similar users",
      },
    ],
    model_version: "clustering-1",
    computed_at: "2026-11-16T05:00:00Z",
  },
};

describe("Segment tab", () => {
  const fetchMock = vi.fn();
  let body: unknown;

  beforeEach(() => {
    setToken("t");
    body = SEGMENT;
    fetchMock
      .mockReset()
      .mockImplementation(async (url: string) =>
        url.includes("/intelligence/segment")
          ? jsonResponse(body)
          : jsonResponse({ items: [], next_cursor: null }),
      );
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const open = async () => {
    renderWithQuery(<IntelligenceView />);
    await userEvent.click(screen.getByRole("tab", { name: "Spending style" }));
  };

  it("fr_13_04 shows the segment name, description and traits", async () => {
    await open();
    expect(
      await screen.findByRole("heading", { name: "Small everyday spender" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Many small purchases.")).toBeInTheDocument();
    expect(screen.getByText(/higher than 80% of similar users/)).toBeInTheDocument();
  });

  it("fr_13_01 explains when there is too little history", async () => {
    body = { ...BASE, complete_periods: 1, segment: null, reason: "INSUFFICIENT_HISTORY" };
    await open();
    expect(
      await screen.findByText(/at least 2 complete budget periods.*1 so far/),
    ).toBeInTheDocument();
  });
});
