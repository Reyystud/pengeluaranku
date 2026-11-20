import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import { jsonResponse, renderWithQuery } from "@/test/utils";
import { IntelligenceView } from "./IntelligenceView";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => ({ timeZone: "Asia/Jakarta" }) }));

const FORECAST = {
  available: true,
  period: {
    start: "2026-11-01",
    end: "2026-11-30",
    period_id: "2026-11-01",
    days_in_period: 30,
    days_elapsed: 20,
  },
  category: null,
  spent_to_date: "2000000.00",
  predicted_total: "3000000.00",
  interval_low: "2800000.00",
  interval_high: "3300000.00",
  predicted_remaining: "1000000.00",
  expected_recurring_remaining: "0.00",
  baseline_prediction: "2950000.00",
  method: "run_rate",
  history_level: "limited",
  model_version: "run-rate-1",
  generated_at: "2026-11-20T05:00:00Z",
  budget: {
    limit_amount: "3100000.00",
    predicted_over_budget: "-100000.00",
    exceed_band: "medium",
  },
  estimated_period_end_balance: "1500000.00",
  daily_curve: [
    { date: "2026-11-21", p10: "2050000.00", p50: "2100000.00", p90: "2150000.00" },
    { date: "2026-11-22", p10: "2150000.00", p50: "2200000.00", p90: "2260000.00" },
  ],
};

const CATEGORIES = [
  { id: "1", slug: "groceries", name: "Groceries", transaction_type: "expense" },
  { id: "2", slug: "salary", name: "Salary", transaction_type: "income" },
];

describe("Forecast tab", () => {
  const fetchMock = vi.fn();
  let forecast: unknown;

  beforeEach(() => {
    setToken("t");
    forecast = FORECAST;
    fetchMock.mockReset().mockImplementation(async (url: string) => {
      if (url.includes("/intelligence/forecast")) return jsonResponse(forecast);
      if (url.includes("/categories")) return jsonResponse(CATEGORIES);
      return jsonResponse({ items: [], next_cursor: null });
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const open = async () => {
    renderWithQuery(<IntelligenceView />);
    await userEvent.click(screen.getByRole("tab", { name: "Forecast" }));
  };

  it("starts on Alerts and switches tabs", async () => {
    renderWithQuery(<IntelligenceView />);
    expect(screen.getByRole("tab", { name: "Alerts" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: "Forecast" }));
    expect(screen.getByRole("tab", { name: "Forecast" })).toHaveAttribute("aria-selected", "true");
  });

  it("labels the total as an estimate with its range, rough label and band in words", async () => {
    await open();
    expect(await screen.findByText("Rp3.000.000")).toBeInTheDocument();
    expect(screen.getByText("Estimate")).toBeInTheDocument();
    expect(screen.getByText("Rough estimate (limited history)")).toBeInTheDocument();
    expect(screen.getByText("Likely between Rp2.800.000 and Rp3.300.000")).toBeInTheDocument();
    expect(screen.getByText("Rp2.000.000")).toBeInTheDocument();
    expect(screen.getByText("Rp1.500.000")).toBeInTheDocument(); // estimated end balance
    expect(screen.getByText("May exceed")).toBeInTheDocument();
    expect(screen.getByText(/Budget Rp3.100.000: estimated Rp100.000 under/)).toBeInTheDocument();
  });

  it("explains the method and shows the baseline value", async () => {
    await open();
    await screen.findByText("Rp3.000.000");
    await userEvent.click(screen.getByText("How is this calculated?"));
    expect(screen.getByText(/Run rate: what you spent per day so far/)).toBeVisible();
    expect(screen.getByText("Run-rate value for comparison: Rp2.950.000")).toBeVisible();
    expect(screen.getByText(/not a guarantee/)).toBeVisible();
  });

  it("has a text summary and a data table for the chart", async () => {
    await open();
    expect(
      await screen.findByText(/Estimated total Rp3.000.000, likely between Rp2.800.000/),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show data table" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("Rp2.100.000")).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(3);
  });

  it("says how much history is missing", async () => {
    forecast = {
      available: false,
      reason: "INSUFFICIENT_HISTORY",
      days_needed: 4,
      transactions_needed: 0,
    };
    await open();
    expect(
      await screen.findByText(/Add at least 2 weeks of transactions.*4 more days needed/),
    ).toBeInTheDocument();
  });

  it("requests a category forecast and explains its minimum", async () => {
    await open();
    await screen.findByText("Rp3.000.000");
    forecast = {
      available: false,
      reason: "INSUFFICIENT_HISTORY",
      days_needed: 40,
      transactions_needed: 5,
    };
    await userEvent.selectOptions(screen.getByLabelText("Category"), "groceries");
    expect(await screen.findByText(/60 days of history and 20 transactions/)).toHaveTextContent(
      "40 more days of history · 5 more transactions in this category",
    );
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes("category=groceries"))).toBe(
        true,
      ),
    );
    expect(screen.queryByRole("option", { name: "Salary" })).not.toBeInTheDocument(); // expense only
  });

  it("shows the request id when the forecast fails", async () => {
    forecast = { code: "INTERNAL", detail: "Boom", request_id: "req-5" };
    fetchMock.mockImplementation(async (url: string) =>
      url.includes("/intelligence/forecast")
        ? jsonResponse(forecast, 500)
        : url.includes("/categories")
          ? jsonResponse(CATEGORIES)
          : jsonResponse({ items: [], next_cursor: null }),
    );
    await open();
    expect(await screen.findByText("req-5")).toBeInTheDocument();
  });
});
