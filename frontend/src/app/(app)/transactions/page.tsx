import type { Metadata } from "next";
import { TransactionsView } from "@/features/transactions/TransactionsView";

export const metadata: Metadata = { title: "Transactions" };
export default function Page() {
  return <TransactionsView />;
}
