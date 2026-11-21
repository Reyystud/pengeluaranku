"use client";

import { useState } from "react";
import type { RecurringSeries, RecurringStatus } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { formatDay } from "@/lib/format";
import { t } from "@/lib/i18n";
import { formatIdr } from "@/lib/money";
import { cn } from "@/lib/utils";
import { useRecurring, useRecurringUpdate } from "./recurring-hooks";

const STATUS_STYLE: Record<RecurringStatus, string> = {
  active: "bg-success-bg text-success",
  user_confirmed: "bg-success-bg text-success",
  paused: "bg-warning-bg text-warning",
  ended: "bg-muted text-muted-foreground",
  user_rejected: "bg-muted text-muted-foreground",
};

/** Status is never colour alone (PRD 8.2): the word is always shown. */
export function StatusBadge({ status }: { status: RecurringStatus }) {
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", STATUS_STYLE[status])}>
      {t(`recurring.status.${status}`)}
    </span>
  );
}

export function RecurringView() {
  const query = useRecurring();
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.isPending) return <SkeletonRows rows={3} />;
  const list = query.data;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("recurring.intro")}</p>
      {list.items.length === 0 ? (
        <EmptyState message={t("recurring.empty")} />
      ) : (
        <>
          <section className="space-y-1 rounded-lg border border-border bg-card p-4">
            <p className="text-lg font-semibold">
              {t("recurring.monthlyTotal", { amount: formatIdr(list.monthly_expense_total) })}
            </p>
            {list.monthly_income_total !== "0.00" ? (
              <p className="text-sm text-muted-foreground">
                {t("recurring.monthlyIncome", { amount: formatIdr(list.monthly_income_total) })}
              </p>
            ) : null}
          </section>
          <section aria-labelledby="recurring-upcoming" className="space-y-2">
            <h2 id="recurring-upcoming" className="font-semibold">
              {t("recurring.upcoming")}
            </h2>
            {list.upcoming.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("recurring.upcomingNone")}</p>
            ) : (
              <ul className="divide-y divide-border rounded-lg border border-border bg-card">
                {list.upcoming.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-3 px-4 py-2">
                    <span className="min-w-0 truncate">
                      {s.merchant_display}
                      <span className="ml-2 text-sm text-muted-foreground">
                        {formatDay(s.next_expected_date)}
                      </span>
                    </span>
                    <span className="font-semibold tabular-nums">
                      {formatIdr(s.effective_amount)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-labelledby="recurring-all" className="space-y-2">
            <h2 id="recurring-all" className="font-semibold">
              {t("recurring.all")}
            </h2>
            <ul className="space-y-3">
              {list.items.map((s) => (
                <li key={s.id}>
                  <SeriesCard series={s} />
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}

function SeriesCard({ series: s }: { series: RecurringSeries }) {
  const update = useRecurringUpdate();
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState(s.user_expected_amount ?? "");
  const id = `amount-${s.id}`;
  const change = s.amount_change;
  const wentUp = change ? Number(change.latest_amount) > Number(change.previous_amount) : false;
  const hint = s.status === "paused" || s.status === "ended" ? s.status : null;

  const save = () => {
    const trimmed = amount.trim();
    update.mutate(
      { id: s.id, user_expected_amount: trimmed === "" ? null : trimmed },
      { onSuccess: () => setEditing(false) },
    );
  };

  return (
    <article className="space-y-3 rounded-lg border border-border bg-card p-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-semibold">{s.merchant_display}</h3>
          <p className="text-xs text-muted-foreground">
            {s.category.name} ·{" "}
            {t("recurring.every", { frequency: t(`recurring.frequency.${s.frequency}`) })} ·{" "}
            {t("recurring.seen", { count: s.occurrences })} ·{" "}
            {t("recurring.confidence", { pct: Math.round(s.confidence * 100) })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {s.transaction_type === "income" ? (
            <span className="rounded-full bg-info-bg px-2 py-0.5 text-xs font-medium text-info">
              {t("recurring.income")}
            </span>
          ) : null}
          <StatusBadge status={s.status} />
        </div>
      </header>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-lg font-bold tabular-nums">{formatIdr(s.effective_amount)}</p>
        <p className="text-sm text-muted-foreground">
          {t("recurring.perMonth", { amount: formatIdr(s.monthly_equivalent) })}
        </p>
      </div>
      <p className="text-sm text-muted-foreground">
        {t("recurring.nextDue", { date: formatDay(s.next_expected_date) })} ·{" "}
        {t("recurring.lastSeen", { date: formatDay(s.last_date) })}
        {s.user_expected_amount !== null
          ? ` · ${t("recurring.detected", { amount: formatIdr(s.expected_amount) })}`
          : ""}
      </p>
      {hint ? (
        <p className="text-sm text-muted-foreground">{t(`recurring.statusHint.${hint}`)}</p>
      ) : null}
      {change ? (
        <p className="text-sm text-warning">
          {t(wentUp ? "recurring.priceChange" : "recurring.priceChangeDown", {
            latest: formatIdr(change.latest_amount),
            previous: formatIdr(change.previous_amount),
          })}
        </p>
      ) : null}

      {editing ? (
        <div className="space-y-2">
          <Field id={id} label={t("recurring.amountLabel")} hint={t("recurring.amountHint")}>
            <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
          <div className="flex gap-2">
            <Button disabled={update.isPending} onClick={save}>
              {t("recurring.save")}
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {s.status !== "user_confirmed" ? (
            <Button
              variant="secondary"
              disabled={update.isPending}
              onClick={() => update.mutate({ id: s.id, status: "user_confirmed" })}
            >
              {t("recurring.confirm")}
            </Button>
          ) : null}
          <Button variant="secondary" onClick={() => setEditing(true)}>
            {t("recurring.editAmount")}
          </Button>
          <Button
            variant="secondary"
            disabled={update.isPending}
            onClick={() => update.mutate({ id: s.id, status: "user_rejected" })}
          >
            {t("recurring.reject")}
          </Button>
        </div>
      )}
      {update.isError ? <ErrorState error={update.error} /> : null}
    </article>
  );
}
