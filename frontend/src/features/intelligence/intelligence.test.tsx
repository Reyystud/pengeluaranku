import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import { jsonResponse, renderWithQuery } from "@/test/utils";
import { AnomaliesView } from "./AnomaliesView";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => ({ timeZone: "Asia/Jakarta" }) }));

const anomaly = (over: Record<string, unknown> = {}) => ({
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
      message: "10.0× your typical Food & Beverage spending (Rp40.000)",
      feature: "ratio_to_cat_median",
      value: 10,
      reference: 40000,
    },
    {
      code: "AMOUNT_PERCENTILE",
      message: "Higher than 100% of your Food & Beverage transactions",
      feature: "pct_rank_cat",
      value: 100,
      reference: 100,
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
  ...over,
});

describe("AnomaliesView", () => {
  const fetchMock = vi.fn();
  let page: unknown;
  const posts = () => fetchMock.mock.calls.filter(([, init]) => (init?.method ?? "GET") === "POST");

  const firstPost = () => {
    const call = posts()[0];
    if (!call) throw new Error("no POST was sent");
    return call;
  };

  beforeEach(() => {
    setToken("t");
    page = { items: [anomaly()], next_cursor: null };
    fetchMock.mockReset().mockImplementation(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? "GET") === "POST")
        return jsonResponse(anomaly({ status: "confirmed", is_alert: true }));
      return jsonResponse(page);
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows the amount, severity as a word, the alert flag and the reasons", async () => {
    renderWithQuery(<AnomaliesView />);
    expect(await screen.findByText("Warung Spike")).toBeInTheDocument();
    expect(screen.getByText("Rp400.000")).toBeInTheDocument();
    const card = within(screen.getByRole("article"));
    expect(card.getByText("High")).toBeInTheDocument(); // a word, not only a color
    expect(card.getByText("Alert")).toBeInTheDocument();
    expect(card.getByText(/Unusually large/)).toBeInTheDocument();
    expect(screen.getByText(/10\.0× your typical Food & Beverage spending/)).toBeInTheDocument();
    expect(screen.getByText(/Higher than 100%/)).toBeInTheDocument();
    expect(screen.queryByText("Limited history")).not.toBeInTheDocument();
  });

  it("marks limited-history anomalies and category surges without a transaction", async () => {
    page = {
      items: [
        anomaly({ history_level: "limited", severity: "medium", is_alert: false }),
        anomaly({
          id: "a2",
          anomaly_type: "category_surge",
          transaction: null,
          reasons: [
            {
              code: "CATEGORY_SURGE",
              message: "Groceries spending in the last 7 days is 3.0× your weekly norm",
              feature: "cat_spend_7d_ratio",
              value: 3,
              reference: 300000,
            },
          ],
          category: { id: "g", slug: "groceries", name: "Groceries" },
        }),
      ],
      next_cursor: null,
    };
    renderWithQuery(<AnomaliesView />);
    expect(await screen.findByText("Limited history")).toBeInTheDocument();
    expect(screen.getByText("Groceries")).toBeInTheDocument(); // surge title falls back to category
    expect(screen.getByText(/3\.0× your weekly norm/)).toBeInTheDocument();
  });

  it("confirms with one click", async () => {
    renderWithQuery(<AnomaliesView />);
    await userEvent.click(await screen.findByRole("button", { name: "Yes, unusual" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    const [url, init] = firstPost();
    expect(String(url)).toContain("/intelligence/anomalies/a1/feedback");
    expect(JSON.parse(init.body)).toEqual({ action: "confirm" });
  });

  it("dismisses with an optional reason and explains what 'expected' does", async () => {
    renderWithQuery(<AnomaliesView />);
    await userEvent.click(await screen.findByRole("button", { name: "This is normal" }));
    expect(screen.getByText(/stop alerts for this merchant for 90 days/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Why is it normal?"), "expected_purchase");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(JSON.parse(firstPost()[1].body)).toEqual({
      action: "dismiss",
      reason: "expected_purchase",
    });
  });

  it("dismisses without a reason", async () => {
    renderWithQuery(<AnomaliesView />);
    await userEvent.click(await screen.findByRole("button", { name: "This is normal" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(JSON.parse(firstPost()[1].body)).toEqual({ action: "dismiss" });
  });

  it("shows given feedback instead of the buttons", async () => {
    page = {
      items: [anomaly({ status: "dismissed", feedback_reason: "wrong_amount", is_alert: false })],
      next_cursor: null,
    };
    renderWithQuery(<AnomaliesView />);
    expect(await screen.findByText(/You marked this as dismissed/)).toHaveTextContent(
      "The amount is wrong",
    );
    expect(screen.queryByRole("button", { name: "Yes, unusual" })).not.toBeInTheDocument();
  });

  it("sends the filters to the API", async () => {
    renderWithQuery(<AnomaliesView />);
    await screen.findByText("Warung Spike");
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "high");
    await userEvent.selectOptions(screen.getByLabelText("Type"), "category_surge");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "confirmed");
    await waitFor(() => {
      const last = String(fetchMock.mock.calls.at(-1)?.[0]);
      expect(last).toContain("severity=high");
      expect(last).toContain("type=category_surge");
      expect(last).toContain("status=confirmed");
    });
  });

  it("explains an empty list, with and without filters", async () => {
    page = { items: [], next_cursor: null };
    renderWithQuery(<AnomaliesView />);
    expect(await screen.findByText(/No unusual spending found/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "low");
    expect(await screen.findByText("Nothing matches these filters.")).toBeInTheDocument();
  });

  it("loads more pages", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      jsonResponse(
        String(url).includes("cursor=c2")
          ? {
              items: [
                anomaly({
                  id: "a2",
                  transaction: { ...anomaly().transaction, merchant: "Toko Dua" },
                }),
              ],
              next_cursor: null,
            }
          : { items: [anomaly()], next_cursor: "c2" },
      ),
    );
    renderWithQuery(<AnomaliesView />);
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Toko Dua")).toBeInTheDocument();
    expect(screen.getByText("Warung Spike")).toBeInTheDocument();
  });

  it("shows the request id when loading fails", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse({ code: "INTERNAL", detail: "Boom", request_id: "req-7" }, 500),
    );
    renderWithQuery(<AnomaliesView />);
    expect(await screen.findByText("req-7")).toBeInTheDocument();
  });
});
