import { expect, type Page } from "@playwright/test";

export const PASSWORD = "e2e-Passphrase-2026";

export async function register(page: Page): Promise<string> {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.test`;
  await page.goto("/register");
  await page.getByLabel("Display name").fill("E2E User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/(dashboard|transactions)/);
  return email;
}

/** Fill the drawer (ids from TransactionDrawer) and save. */
export async function addTransaction(
  page: Page,
  tx: { description: string; amount: string; merchant?: string; category?: string },
): Promise<void> {
  await page.goto("/transactions");
  await page.getByRole("button", { name: "Add transaction" }).click();
  await page.locator("#tx-amount").fill(tx.amount);
  await page.locator("#tx-description").fill(tx.description);
  if (tx.merchant) await page.locator("#tx-merchant").fill(tx.merchant);
  if (tx.category) await page.locator("#tx-category").selectOption({ label: tx.category });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(tx.description).first()).toBeVisible();
}
