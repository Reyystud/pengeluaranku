import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import { jsonResponse, renderWithQuery } from "@/test/utils";
import { TransactionDrawer } from "./TransactionDrawer";

const CATEGORIES = [
  { id: "1", slug: "food_beverage", name: "Food & Beverage", transaction_type: "expense" },
  { id: "2", slug: "groceries", name: "Groceries", transaction_type: "expense" },
  { id: "9", slug: "uncategorized", name: "Uncategorized", transaction_type: "any" },
];
const PREVIEW = {
  category: { id: "1", slug: "food_beverage", name: "Food & Beverage" },
  category_status: "auto",
  categorization: {
    decision: "auto_apply",
    source: "model",
    confidence: 0.95,
    alternatives: [],
    model_version: "v1",
    predicted_category: "food_beverage",
    ml_error: null,
  },
};

describe("TransactionDrawer", () => {
  const fetchMock = vi.fn();
  const calls = (path: string) =>
    fetchMock.mock.calls.filter(([url]) => String(url).includes(path));

  beforeEach(() => {
    setToken("t");
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/categories")) return jsonResponse(CATEGORIES);
      if (url.endsWith("/categorize-preview")) return jsonResponse(PREVIEW);
      if (url.endsWith("/transactions") && init?.method === "POST")
        return jsonResponse({ id: "new" }, 201);
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows a formatted amount preview and validates the amount (PRD 8.2)", async () => {
    const user = userEvent.setup();
    renderWithQuery(<TransactionDrawer open onOpenChange={vi.fn()} transaction={null} />);
    await user.type(screen.getByLabelText("Amount"), "25.000");
    expect(screen.getByText("Rp25.000")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Amount"));
    await user.type(screen.getByLabelText("Amount"), "abc");
    await user.type(screen.getByLabelText("Description"), "Kopi");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Enter an amount above zero/)).toBeInTheDocument();
    expect(
      calls("/transactions").filter(([, i]) => i?.method === "POST" && !String(i)).length,
    ).toBe(0);
  });

  it("asks for a live categorization after typing stops, and shows the chip", async () => {
    const user = userEvent.setup();
    renderWithQuery(<TransactionDrawer open onOpenChange={vi.fn()} transaction={null} />);
    await user.type(screen.getByLabelText("Description"), "Starbucks");
    await waitFor(() => expect(calls("/categorize-preview").length).toBeGreaterThan(0), {
      timeout: 2000,
    });
    expect(await screen.findByText("Food & Beverage · auto")).toBeInTheDocument();
    const body = JSON.parse(String(calls("/categorize-preview").at(-1)?.[1]?.body));
    expect(body).toMatchObject({ description: "Starbucks", transaction_type: "expense" });
    expect(Object.keys(body)).not.toContain("user_id");
  });

  it("saves with a normalized amount string and no category (let the model decide)", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithQuery(<TransactionDrawer open onOpenChange={onOpenChange} transaction={null} />);
    await user.type(screen.getByLabelText("Amount"), "25.000");
    await user.type(screen.getByLabelText("Description"), "Kopi susu");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    const post = calls("/transactions").find(
      ([url, i]) => String(url).endsWith("/transactions") && i?.method === "POST",
    );
    expect((post?.[1]?.headers as Record<string, string>)["Idempotency-Key"]).toMatch(
      /^[0-9a-f-]{36}$/,
    );
    const body = JSON.parse(String(post?.[1]?.body));
    expect(body).toMatchObject({
      amount: "25000.00",
      description: "Kopi susu",
      transaction_type: "expense",
      category: null,
    });
    expect(body.transaction_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("puts a server field error next to the field", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/categories")) return jsonResponse(CATEGORIES);
      if (url.endsWith("/categorize-preview")) return jsonResponse(PREVIEW);
      if (init?.method === "POST")
        return jsonResponse(
          {
            code: "VALIDATION_ERROR",
            detail: "bad",
            request_id: "r1",
            errors: [
              { field: "amount", code: "AMOUNT_TOO_LARGE", message: "Amount is too large." },
            ],
          },
          422,
        );
      return jsonResponse({});
    });
    const user = userEvent.setup();
    renderWithQuery(<TransactionDrawer open onOpenChange={vi.fn()} transaction={null} />);
    await user.type(screen.getByLabelText("Amount"), "5");
    await user.type(screen.getByLabelText("Description"), "x");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Amount is too large.")).toBeInTheDocument();
  });
});
