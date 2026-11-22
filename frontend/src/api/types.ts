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
export type MerchantRule = S["MerchantRuleOut"];
export type MerchantRuleList = S["MerchantRuleList"];
export type ProfileUpdate = S["UpdateProfileRequest"];
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

export type Summary = S["SummaryOut"];
export type CategorySplit = S["CategoriesOut"];
export type Trends = S["TrendsOut"];
export type TrendPoint = S["TrendPoint"];
export type Merchants = S["MerchantsOut"];
export type Budget = S["BudgetOut"];
export type BudgetList = S["BudgetList"];
export type BudgetHistory = S["BudgetHistory"];
export type BudgetStatus = Budget["status"];
export type AppNotification = S["NotificationOut"];
export type NotificationPage = S["NotificationPage"];
export type RangeName = "current_period" | "previous_period" | "last_3_periods";

export type Anomaly = S["AnomalyOut"];
export type AnomalyPage = S["AnomalyPage"];
export type AnomalyStatus = Anomaly["status"];
export type AnomalySeverity = Anomaly["severity"];
export type AnomalyType = Anomaly["anomaly_type"];
export type DismissReason = NonNullable<Anomaly["feedback_reason"]>;

export type ForecastOut = S["ForecastOut"];
export type ForecastUnavailable = S["ForecastUnavailable"];
export type ForecastResponse = ForecastOut | ForecastUnavailable;
export type ExceedBand = NonNullable<ForecastOut["budget"]>["exceed_band"];

export type SegmentResponse = S["SegmentOut"];
export type SegmentTrait = S["TraitOut"];

export type RecurringSeries = S["RecurringOut"];
export type RecurringList = S["RecurringList"];
export type RecurringStatus = RecurringSeries["status"];
export type RecurringFrequency = RecurringSeries["frequency"];
