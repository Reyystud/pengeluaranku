import { expect, test, type Page } from "@playwright/test";
import { addTransaction, register } from "./helpers";

// The three flows of PRD 8.3, run in order on one page and one account: registration is limited to
// 5 per hour per IP and the refresh token rotates, so a saved session cannot be reused.
test.describe.configure({ mode: "serial" });

let page: Page;
test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
  await register(page);
});
test.afterAll(async () => {
  await page.close();
});

test("register, add a transaction, see it on the dashboard", async () => {
  await addTransaction(page, {
    description: "Makan siang",
    amount: "25.000",
    category: "Food & Beverage",
  });
  await page.goto("/dashboard");
  await expect(page.getByRole("term").filter({ hasText: "Expenses" })).toBeVisible();
  await expect(page.getByText(/25\.000/).first()).toBeVisible();
});

test("CSV import: preview, then commit", async () => {
  await page.goto("/transactions/import");
  const today = new Date();
  const day = (back: number) =>
    new Date(today.getTime() - back * 86_400_000).toISOString().slice(0, 10);
  const csv = [
    "date,description,amount,type,payment_method,merchant,category,notes",
    `${day(3)},Kopi Kenangan,25000,expense,e-wallet,Kopi Kenangan,,`,
    `${day(2)},Gaji,1500000,income,bank,,,`,
    `${day(1)},Grab Transport,18.000,expense,e-wallet,Grab,transportation,`,
  ].join("\n");
  await page.getByLabel(/Choose a CSV file/).setInputFiles({
    name: "e2e.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await page.getByRole("button", { name: "Upload and preview" }).click();
  await expect(page.getByText("3 valid")).toBeVisible();
  await page.getByRole("button", { name: "Import 3 transaction(s)" }).click();
  await expect(page.getByText("Import finished")).toBeVisible();
  await expect(page.getByText("3 imported")).toBeVisible();
});

test("correcting a category creates a rule that the next transaction uses", async () => {
  await addTransaction(page, {
    description: "Beli di Warung Bu Tini",
    amount: "40000",
    merchant: "Warung Bu Tini",
  });
  await page.getByText("Beli di Warung Bu Tini").first().click();
  await page.locator("#tx-category").selectOption({ label: "Groceries" });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await addTransaction(page, {
    description: "Warung Bu Tini lagi",
    amount: "35000",
    merchant: "Warung Bu Tini",
  });
  // The list renders a table and a card list (one is hidden by CSS); look at the visible one.
  const row = page
    .locator("tr:visible, li:visible")
    .filter({ hasText: "Warung Bu Tini lagi" })
    .first();
  await expect(row.getByText("Groceries")).toBeVisible();
  await expect(row.getByText("Rule", { exact: true })).toBeVisible();
});
