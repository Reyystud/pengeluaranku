import type { components } from "./schema";

type S = components["schemas"];

export type Transaction = S["TransactionOut"];
export type TransactionPage = S["TransactionPage"];
export type TransactionCreated = S["TransactionCreated"];
export type TransactionUpdated = S["TransactionUpdated"];
export type Categorization = S["Categorization"];
export type CategorizePreviewOut = S["CategorizePreviewOut"];
export type Category = S["CategoryOut"];
export type ImportPreview = S["ImportPreview"];
export type StagedRow = S["StagedRow"];
/** The commit endpoint has no response_model (it can replay a stored response), so this is typed by hand. */
export interface CommitResult {
  committed_count: number;
  skipped_invalid: number;
  skipped_duplicates: number;
}
export type User = S["UserOut"];
export type AuthResponse = S["AuthResponse"];

export type TransactionType = "income" | "expense" | "transfer";
export const PAYMENT_METHODS = [
  "cash",
  "bank_transfer",
  "debit_card",
  "credit_card",
  "e_wallet",
  "qris",
  "other",
] as const;
export type PaymentMethod = (typeof PAYMENT_METHODS)[number];
