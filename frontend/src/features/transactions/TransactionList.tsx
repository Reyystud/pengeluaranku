"use client";

import { ArrowDownRight, ArrowLeftRight, ArrowUpRight, Copy } from "lucide-react";
import type { Transaction } from "@/api/types";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DEFAULT_TZ, formatDate } from "@/lib/format";
import { t } from "@/lib/i18n";
import { formatIdr } from "@/lib/money";
import { cn } from "@/lib/utils";

interface Props {
  items: Transaction[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  onEdit: (tx: Transaction) => void;
  onConfirm: (tx: Transaction) => void;
  onDismissDuplicate: (tx: Transaction) => void;
  timeZone?: string;
}

/** Sign and icon carry the direction, so color is never the only signal. */
export function Amount({ tx }: { tx: Transaction }) {
  const Icon =
    tx.transaction_type === "income"
      ? ArrowUpRight
      : tx.transaction_type === "expense"
        ? ArrowDownRight
        : ArrowLeftRight;
  const sign =
    tx.transaction_type === "income" ? "+" : tx.transaction_type === "expense" ? "−" : "";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap font-medium tabular-nums",
        tx.transaction_type === "income" && "text-success",
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      <span className="sr-only">{t(`tx.${tx.transaction_type}`)} </span>
      {sign}
      {formatIdr(tx.amount)}
    </span>
  );
}

function RowActions({
  tx,
  onConfirm,
  onDismissDuplicate,
}: Pick<Props, "onConfirm" | "onDismissDuplicate"> & { tx: Transaction }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {tx.category_status === "suggested" ? (
        <Button variant="secondary" className="min-h-9 px-3" onClick={() => onConfirm(tx)}>
          {t("tx.confirm")}
        </Button>
      ) : null}
      {tx.possible_duplicate_of && !tx.duplicate_dismissed ? (
        <Button variant="ghost" className="min-h-9 px-3" onClick={() => onDismissDuplicate(tx)}>
          <Copy aria-hidden className="size-4" />
          {t("tx.dismissDuplicate")}
        </Button>
      ) : null}
    </div>
  );
}

export function TransactionList({
  items,
  selected,
  onToggle,
  onToggleAll,
  onEdit,
  onConfirm,
  onDismissDuplicate,
  timeZone = DEFAULT_TZ,
}: Props) {
  const allSelected = items.length > 0 && items.every((tx) => selected.has(tx.id));
  const when = (tx: Transaction) => formatDate(tx.transaction_date, timeZone, tx.has_time);
  const duplicate = (tx: Transaction) => !!tx.possible_duplicate_of && !tx.duplicate_dismissed;

  return (
    <>
      <table className="hidden w-full text-sm md:table">
        <caption className="sr-only">{t("tx.title")}</caption>
        <thead className="text-left text-muted-foreground">
          <tr className="border-b border-border">
            <th scope="col" className="w-10 py-2">
              <input
                type="checkbox"
                aria-label="Select all"
                className="size-4"
                checked={allSelected}
                onChange={onToggleAll}
              />
            </th>
            <th scope="col" className="py-2">
              {t("tx.date")}
            </th>
            <th scope="col" className="py-2">
              {t("tx.description")}
            </th>
            <th scope="col" className="py-2">
              {t("tx.category")}
            </th>
            <th scope="col" className="py-2 text-right">
              {t("tx.amount")}
            </th>
            <th scope="col" className="py-2">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((tx) => (
            <tr key={tx.id} className="border-b border-border align-top hover:bg-muted/50">
              <td className="py-3">
                <input
                  type="checkbox"
                  aria-label={`Select ${tx.description}`}
                  className="size-4"
                  checked={selected.has(tx.id)}
                  onChange={() => onToggle(tx.id)}
                />
              </td>
              <td className="whitespace-nowrap py-3 pr-3">{when(tx)}</td>
              <td className="py-3 pr-3">
                <button
                  className="text-left font-medium hover:underline"
                  onClick={() => onEdit(tx)}
                >
                  {tx.description}
                </button>
                {tx.merchant ? (
                  <div className="text-xs text-muted-foreground">{tx.merchant}</div>
                ) : null}
                {duplicate(tx) ? (
                  <div className="text-xs text-warning">{t("tx.duplicateBanner")}</div>
                ) : null}
              </td>
              <td className="space-y-1 py-3 pr-3">
                <div>{tx.category.name}</div>
                <StatusBadge status={tx.category_status} />
              </td>
              <td className="py-3 text-right">
                <Amount tx={tx} />
              </td>
              <td className="py-3 pl-3">
                <RowActions tx={tx} onConfirm={onConfirm} onDismissDuplicate={onDismissDuplicate} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <ul className="space-y-3 md:hidden">
        {items.map((tx) => (
          <li key={tx.id} className="space-y-2 rounded-lg border border-border bg-card p-3">
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                aria-label={`Select ${tx.description}`}
                className="mt-1 size-5"
                checked={selected.has(tx.id)}
                onChange={() => onToggle(tx.id)}
              />
              <div className="min-w-0 flex-1">
                <button
                  className="block w-full truncate text-left font-medium"
                  onClick={() => onEdit(tx)}
                >
                  {tx.description}
                </button>
                <p className="text-xs text-muted-foreground">
                  {when(tx)}
                  {tx.merchant ? ` · ${tx.merchant}` : ""}
                </p>
              </div>
              <Amount tx={tx} />
            </div>
            <div className="flex flex-wrap items-center gap-2 pl-8">
              <span className="text-sm">{tx.category.name}</span>
              <StatusBadge status={tx.category_status} />
            </div>
            {duplicate(tx) ? (
              <p className="pl-8 text-xs text-warning">{t("tx.duplicateBanner")}</p>
            ) : null}
            <div className="pl-8">
              <RowActions tx={tx} onConfirm={onConfirm} onDismissDuplicate={onDismissDuplicate} />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
