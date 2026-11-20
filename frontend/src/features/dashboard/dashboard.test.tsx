import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import { jsonResponse, renderWithQuery } from "@/test/utils";
import { sliceCategories } from "./charts";
import { DashboardView } from "./DashboardView";

const PERIOD = {
  range: "current_period",
  start: "2026-11-01",
  end: "2026-11-30",
  period_id: "2026-11-01",
  days_in_period: 30,
  days_elapsed: 20,
  in_progress: true,
  timezone: "Asia/Jakarta",
};
const SUMMARY = {
  period: PERIOD,
  balance: "8965000.00",
  income: "5000000.00",
  expenses: "585000.00",
  net: "4415000.00",
  savings_rate: "88.3",
  income_count: 1,
  expense_count: 6,
  review_queue_count: 3,
  comparison: {
    label: "vs. same point last period",
    current: {
      start: "2026-11-01",
      end: "2026-11-20",
      income: "5000000.00",
      expenses: "585000.00",
      net: "4415000.00",
      savings_rate: "88.3",
    },
    previous: {
      start: "2026-10-01",
      end: "2026-10-20",
      income: "5000000.00",
      expenses: "500000.00",
      net: "4500000.00",
      savings_rate: "90.0",
    },
    change: { income: "0.0", expenses: "17.0", net: "-1.9" },
  },
};
const CATEGORIES = {
  period: PERIOD,
  total_expenses: "585000.00",
  items: [
    { slug: "groceries", name: "Groceries", amount: "300000.00", share: "51.3", count: 1 },
    {
      slug: "food_beverage",
      name: "Food & Beverage",
      amount: "155000.00",
      share: "26.5",
      count: 3,
    },
  ],
};
const TREND = {
  period: PERIOD,
  granularity: "day",
  budget_limit: "3000000.00",
  series: [
    {
      start: "2026-11-01",
      end: "2026-11-01",
      expenses: "85000.00",
      cumulative: "85000.00",
      future: false,
      budget_pace: "100000.00",
    },
    {
      start: "2026-11-02",
      end: "2026-11-02",
      expenses: "0.00",
      cumulative: null,
      future: true,
      budget_pace: "200000.00",
    },
  ],
};
const MERCHANTS = {
  period: PERIOD,
  items: [{ merchant_key: "indomaret", name: "Indomaret", amount: "300000.00", count: 1 }],
};
const BUDGETS = {
  category_limits_exceed_overall: false,
  items: [
    {
      id: "b1",
      category: null,
      limit_amount: "3000000.00",
      alert_thresholds: [80, 100],
      spent: "585000.00",
      remaining: "2415000.00",
      utilization: "19.5",
      status: "healthy",
      projected: null,
      period: {
        start: "2026-11-01",
        end: "2026-11-30",
        period_id: "2026-11-01",
        days_in_period: 30,
        days_elapsed: 20,
      },
      created_at: "",
      updated_at: "",
    },
  ],
};

describe("slices", () => {
  const item = (i: number, amount: string, share: string) => ({
    slug: `c${i}`,
    name: `Cat ${i}`,
    amount,
    share,
    count: 1,
  });
  it("keeps up to 8 categories as they are", () => {
    const items = Array.from({ length: 8 }, (_, i) => item(i, "10.00", "12.5"));
    expect(sliceCategories(items)).toHaveLength(8);
  });
  it("folds the tail into Other with exact cents (no float sums)", () => {
    const items = Array.from({ length: 10 }, (_, i) => item(i, "0.10", "1.0"));
    const out = sliceCategories(items);
    expect(out).toHaveLength(8);
    expect(out[7]).toMatchObject({
      slug: "other",
      name: "Other",
      amount: "0.30",
      share: "3.0",
      count: 3,
    });
  });
});

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
  baseline_prediction: "3000000.00",
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

const ALERTS = {
  items: [
    {
      id: "a1",
      anomaly_type: "amount_spike",
      severity: "high",
      status: "open",
      is_alert: true,
      score: 0.8,
      history_level: "personal",
      category: { id: "c", slug: "food_beverage", name: "Food & Beverage" },
      period_id: "2026-11-01",
      reasons: [
        {
          code: "AMOUNT_VS_CATEGORY",
          message: "10.0\u00d7 your typical Food & Beverage spending (Rp40.000)",
          feature: "ratio_to_cat_median",
          value: 10,
          reference: 40000,
        },
      ],
      transaction: {
        id: "t1",
        transaction_date: "2026-11-19T05:00:00+07:00",
        amount: "400000.00",
        merchant: "Warung Spike",
        description: "Warung Spike",
      },
      model_version: "baseline-1",
      feedback_reason: null,
      feedback_at: null,
      created_at: "2026-11-19T05:00:00Z",
    },
  ],
  next_cursor: null,
};

describe("DashboardView", () => {
  const fetchMock = vi.fn();
  let summary: unknown;
  const urls = () => fetchMock.mock.calls.map(([u]) => String(u));

  beforeEach(() => {
    setToken("t");
    summary = SUMMARY;
    fetchMock.mockReset().mockImplementation(async (url: string) => {
      if (url.includes("/analytics/summary")) return jsonResponse(summary);
      if (url.includes("/analytics/categories")) return jsonResponse(CATEGORIES);
      if (url.includes("/analytics/trends")) return jsonResponse(TREND);
      if (url.includes("/analytics/merchants")) return jsonResponse(MERCHANTS);
      if (url.includes("/intelligence/anomalies")) return jsonResponse(ALERTS);
      if (url.includes("/intelligence/forecast")) return jsonResponse(FORECAST);
      if (url.includes("/budgets")) return jsonResponse(BUDGETS);
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows the figures as formatted money, with the period and the comparison", async () => {
    renderWithQuery(<DashboardView />);
    expect(await screen.findByText("Rp8.965.000")).toBeInTheDocument();
    expect(screen.getAllByText("Rp5.000.000").length).toBeGreaterThan(0); // card and comparison
    expect(screen.getAllByText("Rp4.415.000").length).toBeGreaterThan(0);
    expect(screen.getByText(/01 Nov to 30 Nov · Day 20 of 30/)).toBeInTheDocument();
    expect(screen.getByText(/Savings rate/)).toHaveTextContent("88.3%");
    // spending up 17% is bad news, so it is shown with words and an arrow, not only a color
    expect(screen.getByText("17.0% up vs. same point last period")).toBeInTheDocument();
    expect(screen.getByText("1.9% down vs. same point last period")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Compared with vs. same point last period" }),
    ).toBeInTheDocument();
  });

  it("links to the review queue when rows wait for a category", async () => {
    renderWithQuery(<DashboardView />);
    const banner = await screen.findByText("3 transactions need review");
    expect(within(banner.parentElement!).getByRole("link", { name: "Review now" })).toHaveAttribute(
      "href",
      "/transactions",
    );
  });

  it("lists budget progress with status and a progressbar", async () => {
    renderWithQuery(<DashboardView />);
    const bar = await screen.findByRole("progressbar", { name: "Overall" });
    expect(bar).toHaveAttribute("aria-valuetext", "19.5% used");
    expect(screen.getByText("Healthy")).toBeInTheDocument();
  });

  it("describes charts in text and offers a data table", async () => {
    const user = userEvent.setup();
    renderWithQuery(<DashboardView />);
    expect(
      await screen.findByText("Rp585.000 spent. Largest: Groceries (51.3%)."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Rp85\.000 spent in 2 days; the budget pace line shows an even spend of Rp3\.000\.000/,
      ),
    ).toBeInTheDocument();
    const toggles = screen.getAllByRole("button", { name: "Show data table" });
    await user.click(toggles[1]!); // the trend chart
    const table = await screen.findByRole("table", { name: "" }).catch(() => null);
    expect(table ?? screen.getAllByRole("table")[0]).toBeTruthy();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0); // future day has no cumulative
  });

  it("shows the top merchants", async () => {
    renderWithQuery(<DashboardView />);
    expect(await screen.findByText("Indomaret")).toBeInTheDocument();
    expect(screen.getByText("1×")).toBeInTheDocument();
  });

  it("asks the API for the chosen range", async () => {
    const user = userEvent.setup();
    renderWithQuery(<DashboardView />);
    await screen.findByText("Rp8.965.000");
    await user.selectOptions(screen.getByLabelText("Period"), "last_3_periods");
    await waitFor(() =>
      expect(
        urls().some((u) => u.includes("/analytics/summary") && u.includes("range=last_3_periods")),
      ).toBe(true),
    );
    expect(
      urls().some((u) => u.includes("/analytics/trends") && u.includes("range=last_3_periods")),
    ).toBe(true);
  });

  it("shows an onboarding card when there is nothing yet", async () => {
    summary = {
      ...SUMMARY,
      balance: "0.00",
      income_count: 0,
      expense_count: 0,
      review_queue_count: 0,
      income: "0.00",
      expenses: "0.00",
      net: "0.00",
      savings_rate: null,
      comparison: { ...SUMMARY.comparison, change: { income: null, expenses: null, net: null } },
    };
    renderWithQuery(<DashboardView />);
    expect(await screen.findByText("No transactions in this period yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Add a transaction/ })).toHaveAttribute(
      "href",
      "/transactions",
    );
    expect(screen.getByRole("link", { name: /Import a CSV/ })).toHaveAttribute(
      "href",
      "/transactions/import",
    );
    expect(screen.getAllByText("No comparison").length).toBe(3);
  });

  it("shows the request id when the summary fails", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.includes("/analytics/summary")
        ? jsonResponse({ code: "INTERNAL", detail: "Boom", request_id: "req-9" }, 500)
        : url.includes("/analytics/categories")
          ? jsonResponse(CATEGORIES)
          : url.includes("/analytics/trends")
            ? jsonResponse(TREND)
            : url.includes("/analytics/merchants")
              ? jsonResponse(MERCHANTS)
              : url.includes("/intelligence/anomalies")
                ? jsonResponse(ALERTS)
                : url.includes("/intelligence/forecast")
                  ? jsonResponse(FORECAST)
                  : jsonResponse(BUDGETS),
    );
    renderWithQuery(<DashboardView />);
    expect(await screen.findByText("req-9")).toBeInTheDocument();
  });

  it("lists the active alerts with the reason, and links to the intelligence page", async () => {
    renderWithQuery(<DashboardView />);
    expect(await screen.findByText("Warung Spike")).toBeInTheDocument();
    expect(screen.getByText(/10\.0× your typical Food & Beverage spending/)).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument(); // severity as a word, not only a color
    expect(urls().some((u) => u.includes("alerts_only=true") && u.includes("status=open"))).toBe(
      true,
    );
    expect(screen.getByRole("link", { name: "View all" })).toHaveAttribute("href", "/intelligence");
  });

  it("says so when there are no alerts", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.includes("/intelligence/anomalies")
        ? jsonResponse({ items: [], next_cursor: null })
        : url.includes("/analytics/summary")
          ? jsonResponse(summary)
          : url.includes("/analytics/categories")
            ? jsonResponse(CATEGORIES)
            : url.includes("/analytics/trends")
              ? jsonResponse(TREND)
              : url.includes("/analytics/merchants")
                ? jsonResponse(MERCHANTS)
                : jsonResponse(BUDGETS),
    );
    renderWithQuery(<DashboardView />);
    expect(await screen.findByText("No active alerts.")).toBeInTheDocument();
  });

  it("shows the period-end estimate with its range, the band in words and a link", async () => {
    renderWithQuery(<DashboardView />);
    expect(await screen.findByText("Rp3.000.000")).toBeInTheDocument();
    expect(screen.getByText("Likely between Rp2.800.000 and Rp3.300.000")).toBeInTheDocument();
    expect(screen.getByText("May exceed")).toBeInTheDocument();
    expect(screen.getAllByText("Estimate").length).toBeGreaterThan(0);
  });
});
