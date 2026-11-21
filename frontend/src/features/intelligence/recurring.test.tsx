import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import { jsonResponse, renderWithQuery } from "@/test/utils";
import { IntelligenceView } from "./IntelligenceView";

vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => ({ timeZone: "Asia/Jakarta" }) }));

const series = (over: Record<string, unknown> = {}) => ({
  id: "s1",
  merchant_key: "netflix",
  merchant_display: "Netflix",
  transaction_type: "expense",
  category: { id: "c1", slug: "entertainment", name: "Entertainment" },
  frequency: "monthly",
  median_interval_days: 31,
  expected_amount: "54000.00",
  user_expected_amount: null,
  effective_amount: "54000.00",
  monthly_equivalent: "54000.00",
  amount_cv: 0,
  last_date: "2026-11-05",
  next_expected_date: "2026-12-06",
  occurrences: 6,
  confidence: 0.95,
  status: "active",
  amount_change: null,
  ...over,
});

const LIST = {
  items: [
    series({
      id: "s2",
      merchant_display: "Spotify",
      merchant_key: "spotify",
      next_expected_date: "2026-11-25",
      effective_amount: "59000.00",
      expected_amount: "59000.00",
      monthly_equivalent: "59000.00",
    }),
    series(),
  ],
  monthly_expense_total: "113000.00",
  monthly_income_total: "0.00",
  upcoming: [
    series({
      id: "s2",
      merchant_display: "Spotify",
      next_expected_date: "2026-11-25",
      effective_amount: "59000.00",
    }),
  ],
  detection_version: "rules-2",
};

describe("Recurring tab", () => {
  const fetchMock = vi.fn();
  let list: unknown;

  beforeEach(() => {
    setToken("t");
    list = LIST;
    fetchMock.mockReset().mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes("/intelligence/recurring/") && init?.method === "PATCH")
        return jsonResponse(series());
      if (url.includes("/intelligence/recurring")) return jsonResponse(list);
      return jsonResponse({ items: [], next_cursor: null });
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const open = async () => {
    renderWithQuery(<IntelligenceView />);
    await userEvent.click(screen.getByRole("tab", { name: "Recurring" }));
  };
  const patches = () =>
    fetchMock.mock.calls
      .filter(([, init]) => (init as RequestInit | undefined)?.method === "PATCH")
      .map(([url, init]) => ({
        url: url as string,
        body: JSON.parse((init as RequestInit).body as string) as unknown,
      }));

  it("shows the monthly total, what is due soon and every series with its status as a word", async () => {
    await open();
    expect(
      await screen.findByText(/recurring costs are about Rp113\.000 per month/),
    ).toBeInTheDocument();
    const upcoming = within(
      screen.getByRole("heading", { name: "Due in the next 7 days" }).closest("section")!,
    );
    expect(upcoming.getByText("Spotify")).toBeInTheDocument();
    expect(upcoming.queryByText("Netflix")).not.toBeInTheDocument();
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(2);
    expect(within(cards[0]!).getByText("Spotify")).toBeInTheDocument(); // API order: next due first
    const netflix = within(cards[1]!);
    expect(netflix.getByText("Active")).toBeInTheDocument();
    expect(netflix.getByText(/Every month · 6 payments · Confidence 95%/)).toBeInTheDocument();
    expect(netflix.getByText(/Next due 06 Dec/)).toBeInTheDocument();
  });

  it("explains a paused series and a price change", async () => {
    list = {
      ...LIST,
      items: [
        series({
          status: "paused",
          amount_change: { previous_amount: "54000.00", latest_amount: "65000.00" },
        }),
      ],
    };
    await open();
    expect(await screen.findByText("Paused")).toBeInTheDocument();
    expect(screen.getByText("The payment is later than usual.")).toBeInTheDocument();
    expect(screen.getByText(/Charged Rp65\.000 last time, up from Rp54\.000/)).toBeInTheDocument();
  });

  it("says so when no series were found", async () => {
    list = { ...LIST, items: [], upcoming: [], monthly_expense_total: "0.00" };
    await open();
    expect(await screen.findByText(/No recurring payments found yet/)).toBeInTheDocument();
  });

  it("confirms a series", async () => {
    await open();
    const card = within((await screen.findAllByRole("article"))[1]!);
    await userEvent.click(card.getByRole("button", { name: "Yes, recurring" }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]).toEqual({
      url: expect.stringContaining("/intelligence/recurring/s1") as string,
      body: { status: "user_confirmed" },
    });
  });

  it("hides the confirm button once confirmed", async () => {
    list = { ...LIST, items: [series({ status: "user_confirmed" })] };
    await open();
    const card = within(await screen.findByRole("article"));
    expect(card.getByText("Confirmed")).toBeInTheDocument();
    expect(card.queryByRole("button", { name: "Yes, recurring" })).not.toBeInTheDocument();
  });

  it("marks a series as not recurring", async () => {
    await open();
    const card = within((await screen.findAllByRole("article"))[1]!);
    await userEvent.click(card.getByRole("button", { name: "Not recurring" }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]!.body).toEqual({ status: "user_rejected" });
  });

  it("edits the expected amount and clears it again", async () => {
    await open();
    let card = within((await screen.findAllByRole("article"))[1]!);
    await userEvent.click(card.getByRole("button", { name: "Edit amount" }));
    await userEvent.type(screen.getByLabelText(/Expected amount/), "60000");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]!.body).toEqual({ user_expected_amount: "60000" });

    card = within((await screen.findAllByRole("article"))[1]!);
    await userEvent.click(card.getByRole("button", { name: "Edit amount" }));
    await userEvent.clear(screen.getByLabelText(/Expected amount/));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(patches()[1]!.body).toEqual({ user_expected_amount: null });
  });

  it("shows the detected amount next to an edited one", async () => {
    list = {
      ...LIST,
      items: [series({ user_expected_amount: "60000.00", effective_amount: "60000.00" })],
    };
    await open();
    expect(await screen.findByText(/Detected amount Rp54\.000/)).toBeInTheDocument();
  });

  it("shows the API error when the update fails", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PATCH")
        return jsonResponse(
          { code: "VALIDATION_ERROR", title: "Validation failed", detail: "bad", status: 422 },
          422,
        );
      if (url.includes("/intelligence/recurring")) return jsonResponse(LIST);
      return jsonResponse({ items: [], next_cursor: null });
    });
    await open();
    const card = within((await screen.findAllByRole("article"))[1]!);
    await userEvent.click(card.getByRole("button", { name: "Not recurring" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
