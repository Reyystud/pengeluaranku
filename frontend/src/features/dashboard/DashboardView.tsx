"use client";

import { ArrowDownRight, ArrowUpRight, Minus, Plus, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import type { Budget, RangeName, Summary } from "@/api/types";
import { BudgetStatusBadge, UtilizationBar } from "@/components/ui/budget-status";
import { Select } from "@/components/ui/field";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { formatDay, formatPercent } from "@/lib/format";
import { t } from "@/lib/i18n";
import { formatIdr } from "@/lib/money";
import { cn } from "@/lib/utils";
import { useBudgets } from "@/features/budgets/hooks";
import { SeverityBadge } from "@/features/intelligence/AnomaliesView";
import { useActiveAlerts } from "@/features/intelligence/hooks";
import { CategoryDonut, TrendChart } from "./charts";
import { useCategorySplit, useMerchants, useSummary, useTrend } from "./hooks";

const RANGES: { value: RangeName; key: string }[] = [
  { value: "current_period", key: "dash.rangeCurrent" },
  { value: "previous_period", key: "dash.rangePrevious" },
  { value: "last_3_periods", key: "dash.rangeThree" },
];

export function DashboardView() {
  const [range, setRange] = useState<RangeName>("current_period");
  const summary = useSummary(range);
  const categories = useCategorySplit(range);
  const trend = useTrend(range);
  const merchants = useMerchants(range);
  const budgets = useBudgets();
  const alerts = useActiveAlerts();

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{t("dash.title")}</h1>
          {summary.data ? <PeriodLine summary={summary.data} /> : null}
        </div>
        <label className="space-y-1 text-sm font-medium">
          <span className="block">{t("dash.range")}</span>
          <Select value={range} onChange={(e) => setRange(e.target.value as RangeName)}>
            {RANGES.map((r) => (
              <option key={r.value} value={r.value}>
                {t(r.key)}
              </option>
            ))}
          </Select>
        </label>
      </div>

      {summary.isError ? (
        <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
      ) : summary.isPending ? (
        <div
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
          role="status"
          aria-label={t("common.loading")}
        >
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : (
        <>
          {summary.data.review_queue_count > 0 ? (
            <ReviewBanner count={summary.data.review_queue_count} />
          ) : null}
          {isEmpty(summary.data) ? <Onboarding /> : null}
          <StatCards summary={summary.data} />
          <ComparisonTable summary={summary.data} />
        </>
      )}

      <BudgetProgress query={budgets} />
      <AlertsCard query={alerts} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel query={categories}>{(data) => <CategoryDonut data={data} />}</Panel>
        <Panel query={merchants}>
          {(data) => (
            <section className="space-y-3 rounded-lg border border-border bg-card p-4">
              <h2 className="font-semibold">{t("dash.merchants")}</h2>
              {data.items.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("dash.merchantsEmpty")}</p>
              ) : (
                <ol className="space-y-2 text-sm">
                  {data.items.map((m, i) => (
                    <li key={m.merchant_key} className="flex items-center justify-between gap-2">
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="w-5 text-muted-foreground">{i + 1}.</span>
                        <span className="truncate">{m.name}</span>
                        <span className="text-xs text-muted-foreground">
                          {t("dash.times", { count: m.count })}
                        </span>
                      </span>
                      <span className="shrink-0 tabular-nums">{formatIdr(m.amount)}</span>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          )}
        </Panel>
      </div>
      <Panel query={trend}>{(data) => <TrendChart data={data} />}</Panel>
    </div>
  );
}

function isEmpty(s: Summary): boolean {
  return s.income_count === 0 && s.expense_count === 0 && s.balance === "0.00";
}

function PeriodLine({ summary }: { summary: Summary }) {
  const p = summary.period;
  return (
    <p className="text-sm text-muted-foreground">
      {t("dash.periodLine", { start: formatDay(p.start), end: formatDay(p.end) })}
      {p.in_progress
        ? ` · ${t("dash.dayOf", { elapsed: p.days_elapsed, total: p.days_in_period })}`
        : ` · ${t("dash.ended")}`}
    </p>
  );
}

function ReviewBanner({ count }: { count: number }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warning/40 bg-warning-bg px-4 py-3 text-sm text-warning">
      <span>{count === 1 ? t("dash.reviewOne") : t("dash.review", { count })}</span>
      <Link href="/transactions" className="font-semibold underline">
        {t("dash.reviewLink")}
      </Link>
    </div>
  );
}

function Onboarding() {
  return (
    <EmptyState
      message={t("dash.empty")}
      action={
        <div className="flex flex-wrap justify-center gap-2">
          <Link
            href="/transactions"
            className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground sm:min-h-9"
          >
            <Plus aria-hidden className="size-4" />
            {t("dash.emptyAdd")}
          </Link>
          <Link
            href="/transactions/import"
            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-card px-4 text-sm font-medium sm:min-h-9"
          >
            <Upload aria-hidden className="size-4" />
            {t("dash.emptyImport")}
          </Link>
        </div>
      }
    />
  );
}

/** Which direction counts as good: more income and net is good, more spending is not. */
function Change({
  value,
  label,
  goodWhenUp,
}: {
  value: string | null;
  label: string;
  goodWhenUp: boolean;
}) {
  if (value === null) return <p className="text-xs text-muted-foreground">{t("dash.noChange")}</p>;
  const n = Number(value);
  const direction = n > 0 ? "up" : n < 0 ? "down" : "flat";
  const good = n === 0 ? null : n > 0 === goodWhenUp;
  const Icon = n > 0 ? ArrowUpRight : n < 0 ? ArrowDownRight : Minus;
  return (
    <p
      className={cn(
        "flex items-center gap-1 text-xs",
        good === null ? "text-muted-foreground" : good ? "text-success" : "text-danger",
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {t("dash.changeVs", {
        change: Math.abs(n).toFixed(1),
        direction: t(`dash.${direction}`),
        label,
      })}
    </p>
  );
}

function StatCards({ summary }: { summary: Summary }) {
  const { comparison: c } = summary;
  const cards: {
    label: string;
    value: string;
    hint?: string;
    change?: string | null;
    up?: boolean;
  }[] = [
    { label: t("dash.balance"), value: summary.balance, hint: t("dash.balanceHint") },
    { label: t("dash.income"), value: summary.income, change: c.change.income, up: true },
    { label: t("dash.expenses"), value: summary.expenses, change: c.change.expenses, up: false },
    { label: t("dash.net"), value: summary.net, change: c.change.net, up: true },
  ];
  return (
    <div>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <div key={card.label} className="space-y-1 rounded-lg border border-border bg-card p-4">
            <dt className="text-sm text-muted-foreground">{card.label}</dt>
            <dd className="text-xl font-bold tabular-nums">{formatIdr(card.value)}</dd>
            {card.up !== undefined ? (
              <Change value={card.change ?? null} label={c.label} goodWhenUp={card.up} />
            ) : (
              <p className="text-xs text-muted-foreground">{card.hint}</p>
            )}
          </div>
        ))}
      </dl>
      {summary.savings_rate !== null ? (
        <p className="mt-2 text-sm text-muted-foreground">
          {t("dash.savingsRate")}: <strong>{formatPercent(summary.savings_rate)}</strong>
        </p>
      ) : null}
    </div>
  );
}

function ComparisonTable({ summary }: { summary: Summary }) {
  const { comparison: c } = summary;
  const rows = [
    [t("dash.income"), c.current.income, c.previous.income],
    [t("dash.expenses"), c.current.expenses, c.previous.expenses],
    [t("dash.net"), c.current.net, c.previous.net],
  ] as const;
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-4">
      <h2 className="font-semibold">{t("dash.comparison", { label: c.label })}</h2>
      <p className="text-xs text-muted-foreground">
        {formatDay(c.current.start)} – {formatDay(c.current.end)} {t("common.vs")}{" "}
        {formatDay(c.previous.start)} – {formatDay(c.previous.end)}
      </p>
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="py-1 font-medium">{t("dash.colMetric")}</th>
            <th className="py-1 text-right font-medium">{t("dash.colCurrent")}</th>
            <th className="py-1 text-right font-medium">{t("dash.colPrevious")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, cur, prev]) => (
            <tr key={name} className="border-t border-border">
              <td className="py-1">{name}</td>
              <td className="py-1 text-right tabular-nums">{formatIdr(cur)}</td>
              <td className="py-1 text-right tabular-nums">{formatIdr(prev)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function BudgetProgress({ query }: { query: ReturnType<typeof useBudgets> }) {
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.isPending) return <Skeleton className="h-24" />;
  const items = query.data.items;
  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">{t("dash.budgets")}</h2>
        <Link href="/budgets" className="text-sm font-medium text-primary underline">
          {items.length ? t("dash.budgetsAll") : t("dash.budgetsAdd")}
        </Link>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("dash.budgetsEmpty")}</p>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {items.slice(0, 4).map((b: Budget) => (
            <li key={b.id} className="space-y-1.5">
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate font-medium">
                  {b.category?.name ?? t("budget.overall")}
                </span>
                <BudgetStatusBadge status={b.status} />
              </div>
              <UtilizationBar
                percent={b.utilization}
                status={b.status}
                label={b.category?.name ?? t("budget.overall")}
              />
              <p className="text-xs text-muted-foreground">
                {formatIdr(b.spent)} {t("budget.of")} {formatIdr(b.limit_amount)} ·{" "}
                {t("budget.utilization", { percent: b.utilization })}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Panel<T>({
  query,
  children,
}: {
  query: {
    isError: boolean;
    isPending: boolean;
    error: unknown;
    data: T | undefined;
    refetch: () => unknown;
  };
  children: (data: T) => React.ReactNode;
}) {
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.isPending || query.data === undefined) return <Skeleton className="h-64" />;
  return <>{children(query.data)}</>;
}

function AlertsCard({ query }: { query: ReturnType<typeof useActiveAlerts> }) {
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.isPending) return <Skeleton className="h-24" />;
  const items = query.data.items;
  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">{t("intel.dashTitle")}</h2>
        <Link href="/intelligence" className="text-sm font-medium text-primary underline">
          {t("intel.dashAll")}
        </Link>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("intel.dashEmpty")}</p>
      ) : (
        <ul className="space-y-2">
          {items.map((a) => (
            <li key={a.id} className="space-y-0.5">
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate font-medium">
                  {a.transaction
                    ? (a.transaction.merchant ?? a.transaction.description)
                    : (a.category?.name ?? "")}
                </span>
                <SeverityBadge severity={a.severity} />
              </div>
              <p className="text-xs text-muted-foreground">{a.reasons[0]?.message}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
