import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "@/auth/token";
import { jsonResponse, renderWithQuery } from "@/test/utils";
import { SettingsView } from "./SettingsView";

const updateUser = vi.fn();
const replace = vi.fn();
const USER = {
  id: "u1",
  email: "a@b.id",
  display_name: "Sari",
  timezone: "Asia/Jakarta",
  budget_period_start_day: 1,
  pending_period_start_day: null,
  pending_period_start_effective: null,
  training_consent: false,
};
vi.mock("@/auth/AuthProvider", () => ({ useAuth: () => ({ user: USER, updateUser }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const CATEGORIES = [
  { id: "c1", slug: "food_beverage", name: "Food & Beverage", transaction_type: "expense" },
  { id: "c2", slug: "shopping", name: "Shopping", transaction_type: "expense" },
  { id: "c3", slug: "salary", name: "Salary", transaction_type: "income" },
];
const RULE = {
  id: "r1",
  merchant_key: "warung-a",
  merchant_display: "Warung A",
  category: { id: "c1", slug: "food_beverage", name: "Food & Beverage" },
  times_applied: 3,
  last_applied_at: "2026-11-10T03:00:00Z",
  created_at: "2026-10-01T03:00:00Z",
  updated_at: "2026-11-10T03:00:00Z",
};

describe("Settings", () => {
  const fetchMock = vi.fn();
  let rules: unknown[];

  beforeEach(() => {
    setToken("t");
    updateUser.mockReset();
    replace.mockReset();
    rules = [RULE];
    fetchMock.mockReset().mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url.includes("/merchant-rules") && method === "GET")
        return jsonResponse({ items: rules });
      if (url.includes("/merchant-rules/")) return jsonResponse(RULE);
      if (url.endsWith("/categories")) return jsonResponse(CATEGORIES);
      if (url.endsWith("/users/me") && method === "PATCH")
        return jsonResponse({ ...USER, ...JSON.parse(String(init?.body)) });
      if (url.endsWith("/users/me") && method === "DELETE")
        return new Response(null, { status: 204 });
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const calls = (method: string, part: string) =>
    fetchMock.mock.calls.filter(
      ([u, i]) => String(u).includes(part) && (i?.method ?? "GET") === method,
    );

  const sent = (method: string, part: string) =>
    JSON.parse(String((calls(method, part)[0]?.[1] as RequestInit | undefined)?.body));

  it("fr_15_01 lists merchant rules with times applied and lets the user change the category", async () => {
    renderWithQuery(<SettingsView />);
    expect(await screen.findByText("Warung A")).toBeInTheDocument();
    expect(screen.getByText(/Applied 3 times/)).toBeInTheDocument();
    const select = await screen.findByRole("combobox", { name: "Category for Warung A" });
    await waitFor(() =>
      expect(within(select).getByRole("option", { name: "Shopping" })).toBeInTheDocument(),
    );
    expect(within(select).queryByRole("option", { name: "Salary" })).not.toBeInTheDocument();
    await userEvent.selectOptions(select, "shopping");
    await waitFor(() => expect(calls("PATCH", "/merchant-rules/r1")).toHaveLength(1));
    expect(sent("PATCH", "/merchant-rules/r1")).toEqual({
      category: "shopping",
    });
  });

  it("fr_15_02 deletes a rule", async () => {
    renderWithQuery(<SettingsView />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete rule for Warung A" }));
    await waitFor(() => expect(calls("DELETE", "/merchant-rules/r1")).toHaveLength(1));
  });

  it("fr_01 saves the profile and reports it", async () => {
    renderWithQuery(<SettingsView />);
    const day = await screen.findByLabelText("Budget period starts on day");
    await userEvent.clear(day);
    await userEvent.type(day, "25");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(sent("PATCH", "/users/me").budget_period_start_day).toBe(25);
    expect(updateUser).toHaveBeenCalled();
  });

  it("fr_12 the training consent toggle sends only that field", async () => {
    renderWithQuery(<SettingsView />);
    await userEvent.click(await screen.findByRole("checkbox", { name: /Allow my corrections/ }));
    await waitFor(() => expect(calls("PATCH", "/users/me")).toHaveLength(1));
    expect(sent("PATCH", "/users/me")).toEqual({
      training_consent: true,
    });
  });

  it("fr_01_09 account deletion needs the word DELETE and then leaves for the login page", async () => {
    renderWithQuery(<SettingsView />);
    const button = await screen.findByRole("button", { name: "Delete my account" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Your password"), "secret-password");
    await userEvent.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    expect(button).toBeEnabled();
    await userEvent.click(button);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(sent("DELETE", "/users/me")).toEqual({
      password: "secret-password",
      confirm: "DELETE",
    });
  });
});
