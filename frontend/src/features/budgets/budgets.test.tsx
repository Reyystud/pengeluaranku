import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import { jsonResponse, renderWithQuery } from "@/test/utils";
import { BudgetsView, parseThresholds } from "./BudgetsView";

const CATEGORIES = [
  { id: "1", slug: "food_beverage", name: "Food & Beverage", transaction_type: "expense" },
  { id: "2", slug: "groceries", name: "Groceries", transaction_type: "expense" },
  { id: "3", slug: "salary", name: "Salary", transaction_type: "income" },
  { id: "9", slug: "uncategorized", name: "Uncategorized", transaction_type: "any" },
];
const PERIOD = {
  start: "2026-11-01",
  end: "2026-11-30",
  period_id: "2026-11-01",
  days_in_period: 30,
  days_elapsed: 20,
};
const budget = (over: Record<string, unknown>) => ({
  id: "b1",
  category: null,
  limit_amount: "1000000.00",
  alert_thresholds: [80, 100],
  spent: "250000.00",
  remaining: "750000.00",
  utilization: "25.0",
  status: "healthy",
  projected: null,
  period: PERIOD,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  ...over,
});

describe("parseThresholds (FR-05.05)", () => {
  it("accepts commas or spaces, sorts and removes duplicates", () => {
    expect(parseThresholds("100, 80 80")).toEqual([80, 100]);
    expect(parseThresholds("")).toEqual([]);
  });
  it("rejects values outside 1..200, decimals, text and more than 10", () => {
    for (const bad of ["0", "201", "80.5", "abc", "-5", "1,2,3,4,5,6,7,8,9,10,11"])
      expect(parseThresholds(bad)).toBeNull();
  });
});

describe("BudgetsView", () => {
  const fetchMock = vi.fn();
  let listing: unknown;
  const calls = (method: string, path: string) =>
    fetchMock.mock.calls.filter(
      ([url, init]) => String(url).endsWith(path) && (init?.method ?? "GET") === method,
    );

  beforeEach(() => {
    setToken("t");
    listing = { items: [], category_limits_exceed_overall: false };
    fetchMock.mockReset().mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url.endsWith("/categories")) return jsonResponse(CATEGORIES);
      if (url.endsWith("/budgets") && method === "GET") return jsonResponse(listing);
      if (url.endsWith("/budgets") && method === "POST")
        return jsonResponse(budget({ id: "new" }), 201);
      if (url.includes("/history"))
        return jsonResponse({
          items: [
            {
              period_id: "2026-10-01",
              limit_amount: "900000.00",
              spent: "450000.00",
              utilization: "50.0",
            },
          ],
        });
      if (method === "PATCH") return jsonResponse(budget({}));
      return new Response(null, { status: 204 });
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows an empty state", async () => {
    renderWithQuery(<BudgetsView />);
    expect(await screen.findByText(/No budgets yet/)).toBeInTheDocument();
  });

  it("shows each budget with status as icon plus words, never color alone (PRD 8.2)", async () => {
    listing = {
      items: [
        budget({}),
        budget({
          id: "b2",
          category: { id: "2", slug: "groceries", name: "Groceries" },
          status: "exceeded",
          utilization: "120.0",
          spent: "1200000.00",
          remaining: "-200000.00",
        }),
      ],
      category_limits_exceed_overall: true,
    };
    renderWithQuery(<BudgetsView />);
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("Exceeded")).toBeInTheDocument();
    expect(screen.getByText("Overall")).toBeInTheDocument();
    expect(screen.getByText(/Over by Rp200\.000/)).toBeInTheDocument();
    const bars = screen.getAllByRole("progressbar");
    expect(bars[1]).toHaveAttribute("aria-valuenow", "100"); // the bar stops at 100 ...
    expect(bars[1]).toHaveAttribute("aria-valuetext", "120.0% used"); // ... the text keeps the truth
    expect(screen.getByRole("note")).toHaveTextContent(/add up to more than your overall budget/);
  });

  it("creates a budget with a normalized money string and thresholds", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BudgetsView />);
    await user.click(await screen.findByRole("button", { name: "Add budget" }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Applies to"), "groceries");
    await user.type(within(dialog).getByLabelText("Monthly limit"), "1.500.000");
    const thresholds = within(dialog).getByLabelText(/Alert at/);
    await user.clear(thresholds);
    await user.type(thresholds, "100, 50");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls("POST", "/budgets")).toHaveLength(1));
    const [, init] = calls("POST", "/budgets")[0]!;
    expect(JSON.parse(init.body as string)).toEqual({
      category: "groceries",
      limit_amount: "1500000.00",
      alert_thresholds: [50, 100],
    });
  });

  it("only offers expense categories that have no budget yet", async () => {
    listing = {
      items: [budget({ category: { id: "2", slug: "groceries", name: "Groceries" } })],
      category_limits_exceed_overall: false,
    };
    const user = userEvent.setup();
    renderWithQuery(<BudgetsView />);
    await user.click(await screen.findByRole("button", { name: "Add budget" }));
    const select = within(await screen.findByRole("dialog")).getByLabelText("Applies to");
    const names = within(select)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(names).toEqual(["Overall", "Food & Beverage"]); // no Salary, no Uncategorized, no Groceries
  });

  it("validates before sending", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BudgetsView />);
    await user.click(await screen.findByRole("button", { name: "Add budget" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Monthly limit"), "0");
    const thresholds = within(dialog).getByLabelText(/Alert at/);
    await user.clear(thresholds);
    await user.type(thresholds, "300");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText(/Enter an amount above zero/)).toBeInTheDocument();
    expect(within(dialog).getByText(/whole numbers from 1 to 200/)).toBeInTheDocument();
    expect(calls("POST", "/budgets")).toHaveLength(0);
  });

  it("edits only the limit and thresholds", async () => {
    listing = { items: [budget({})], category_limits_exceed_overall: false };
    const user = userEvent.setup();
    renderWithQuery(<BudgetsView />);
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText("Applies to")).not.toBeInTheDocument();
    const limit = within(dialog).getByLabelText("Monthly limit");
    expect(limit).toHaveValue("1000000");
    await user.clear(limit);
    await user.type(limit, "2000000");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls("PATCH", "/budgets/b1")).toHaveLength(1));
    expect(JSON.parse(calls("PATCH", "/budgets/b1")[0]![1].body as string)).toEqual({
      limit_amount: "2000000.00",
      alert_thresholds: [80, 100],
    });
  });

  it("asks before deleting, then deletes", async () => {
    listing = { items: [budget({})], category_limits_exceed_overall: false };
    const user = userEvent.setup();
    renderWithQuery(<BudgetsView />);
    await user.click(await screen.findByRole("button", { name: "Delete budget: Overall" }));
    expect(calls("DELETE", "/budgets/b1")).toHaveLength(0);
    expect(screen.getByText(/Past notifications stay/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete budget: Overall" }));
    await waitFor(() => expect(calls("DELETE", "/budgets/b1")).toHaveLength(1));
  });

  it("shows the history of closed periods on demand", async () => {
    listing = { items: [budget({})], category_limits_exceed_overall: false };
    const user = userEvent.setup();
    renderWithQuery(<BudgetsView />);
    await user.click(await screen.findByRole("button", { name: "History" }));
    expect(await screen.findByText("Rp900.000")).toBeInTheDocument();
    expect(screen.getByText("50.0%")).toBeInTheDocument();
  });

  it("keeps the drawer open and shows the 409 message when the budget already exists", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/categories")) return jsonResponse(CATEGORIES);
      if (url.endsWith("/budgets") && init?.method === "POST")
        return jsonResponse({ code: "BUDGET_EXISTS", detail: "x" }, 409);
      return jsonResponse(listing);
    });
    const user = userEvent.setup();
    renderWithQuery(<BudgetsView />);
    await user.click(await screen.findByRole("button", { name: "Add budget" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Monthly limit"), "100");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText("You already have a budget for that."),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows the request id when the API fails", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.endsWith("/categories")
        ? jsonResponse(CATEGORIES)
        : jsonResponse({ code: "INTERNAL", detail: "Boom", request_id: "req-123" }, 500),
    );
    renderWithQuery(<BudgetsView />);
    expect(await screen.findByText("req-123")).toBeInTheDocument();
  });
});
