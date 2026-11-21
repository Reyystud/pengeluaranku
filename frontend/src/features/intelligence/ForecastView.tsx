"use client";

import { useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ExceedBand, ForecastOut } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { ChartFrame } from "@/components/ui/chart-frame";
import { Select } from "@/components/ui/field";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { formatDate, formatDay } from "@/lib/format";
import { t } from "@/lib/i18n";
import { formatIdr } from "@/lib/money";
import { cn } from "@/lib/utils";
import { useCategories } from "@/features/transactions/hooks";
import { useForecast } from "./forecast-hooks";

const BAND_STYLE: Record<ExceedBand, string> = {
  low: "bg-success-bg text-success",
  medium: "bg-warning-bg text-warning",
  high: "bg-danger-bg text-danger",
};

/** Band is never colour alone (PRD 8.2): the words are always shown. */
export function BandBadge({ band }: { band: ExceedBand }) {
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", BAND_STYLE[band])}>
      {t(`forecast.band.${band}`)}
    </span>
  );
}

export function ForecastView() {
  const [category, setCategory] = useState("");
  const categories = (useCategories().data ?? []).filter((c) => c.transaction_type === "expense");
  const query = useForecast(category);

  return (
    <div className="space-y-4">
      <label className="block max-w-xs space-y-1 text-sm font-medium">
        <span className="block">{t("forecast.category")}</span>
        <Select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">{t("forecast.overall")}</option>
          {categories.map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.name}
            </option>
          ))}
        </Select>
      </label>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.isPending ? (
        <SkeletonRows rows={3} />
      ) : query.data.available ? (
        <ForecastDetail f={query.data} />
      ) : (
        <EmptyState
          message={
            category
              ? [
                  t("forecast.needCategory"),
                  query.data.days_needed > 0
                    ? t("forecast.needMoreDays", { days: query.data.days_needed })
                    : "",
                  query.data.transactions_needed > 0
                    ? t("forecast.needMoreTx", { count: query.data.transactions_needed })
                    : "",
                ]
                  .filter(Boolean)
                  .join(" · ")
              : t("forecast.needDays", { days: query.data.days_needed })
          }
        />
      )}
    </div>
  );
}

function ForecastDetail({ f }: { f: ForecastOut }) {
  const { timeZone } = useAuth();
  const direction = f.budget?.predicted_over_budget.startsWith("-") ? "under" : "over";
  return (
    <div className="space-y-4">
      <section className="space-y-3 rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">{t("forecast.title")}</h2>
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
            {t("forecast.estimate")}
          </span>
          {f.history_level === "limited" ? (
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
              {t("forecast.rough")}
            </span>
          ) : null}
        </div>
        <p className="text-3xl font-bold tabular-nums">{formatIdr(f.predicted_total)}</p>
        <p className="text-sm text-muted-foreground">
          {t("forecast.range", {
            low: formatIdr(f.interval_low),
            high: formatIdr(f.interval_high),
          })}
        </p>
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted-foreground">{t("forecast.spent")}</dt>
            <dd className="font-semibold tabular-nums">{formatIdr(f.spent_to_date)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("forecast.remaining")}</dt>
            <dd className="font-semibold tabular-nums">{formatIdr(f.predicted_remaining)}</dd>
          </div>
          {f.estimated_period_end_balance !== null ? (
            <div>
              <dt className="text-muted-foreground">{t("forecast.endBalance")}</dt>
              <dd className="font-semibold tabular-nums">
                {formatIdr(f.estimated_period_end_balance)}
              </dd>
            </div>
          ) : null}
        </dl>
        {f.budget ? (
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <BandBadge band={f.budget.exceed_band} />
            {t("forecast.bandNote", {
              limit: formatIdr(f.budget.limit_amount),
              diff: formatIdr(f.budget.predicted_over_budget.replace("-", "")),
              direction: t(`forecast.${direction}`),
            })}
          </p>
        ) : null}
        <details className="text-sm">
          <summary className="cursor-pointer font-medium">{t("forecast.how")}</summary>
          <div className="mt-2 space-y-1 text-muted-foreground">
            <p>{f.method === "run_rate" ? t("forecast.howRunRate") : t("forecast.howSeasonal")}</p>
            <p>{t("forecast.howRange")}</p>
            <p>
              {t("forecast.howRecurring", { value: formatIdr(f.expected_recurring_remaining) })}
            </p>
            <p>{t("forecast.howBaseline", { value: formatIdr(f.baseline_prediction) })}</p>
          </div>
        </details>
        <p className="text-xs text-muted-foreground">
          {t("forecast.generated", { when: formatDate(f.generated_at, timeZone, true) })}
        </p>
      </section>
      <CurveChart f={f} />
    </div>
  );
}

const axis = (v: number) => (v >= 1_000_000 ? `${v / 1_000_000}jt` : `${Math.round(v / 1000)}rb`);

function CurveChart({ f }: { f: ForecastOut }) {
  const rows = f.daily_curve.map((p) => ({
    label: formatDay(p.date),
    low: Number(p.p10),
    band: Number(p.p90) - Number(p.p10),
    mid: Number(p.p50),
  }));
  const summary =
    rows.length === 0
      ? t("forecast.chartNoDays", { total: formatIdr(f.predicted_total) })
      : t("forecast.chartSummary", {
          total: formatIdr(f.predicted_total),
          low: formatIdr(f.interval_low),
          high: formatIdr(f.interval_high),
          days: rows.length,
        });
  return (
    <ChartFrame
      title={t("forecast.chart")}
      summary={summary}
      chart={
        <div className="h-64" aria-hidden>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.4} />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={24} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={axis} width={44} />
              <Tooltip
                formatter={(v) => (typeof v === "number" ? formatIdr(v.toFixed(2)) : String(v))}
              />
              <Legend />
              <Area
                dataKey="low"
                stackId="range"
                stroke="none"
                fill="transparent"
                legendType="none"
                isAnimationActive={false}
              />
              <Area
                dataKey="band"
                stackId="range"
                name={t("forecast.range80")}
                stroke="none"
                fill="#2563eb"
                fillOpacity={0.2}
                isAnimationActive={false}
              />
              <Line
                dataKey="mid"
                name={t("forecast.p50")}
                stroke="#2563eb"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      }
      table={
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 font-medium">{t("forecast.colDate")}</th>
              <th className="py-1 text-right font-medium">{t("forecast.colLow")}</th>
              <th className="py-1 text-right font-medium">{t("forecast.colMid")}</th>
              <th className="py-1 text-right font-medium">{t("forecast.colHigh")}</th>
            </tr>
          </thead>
          <tbody>
            {f.daily_curve.map((p) => (
              <tr key={p.date} className="border-t border-border">
                <td className="py-1">{formatDay(p.date)}</td>
                <td className="py-1 text-right tabular-nums">{formatIdr(p.p10)}</td>
                <td className="py-1 text-right tabular-nums">{formatIdr(p.p50)}</td>
                <td className="py-1 text-right tabular-nums">{formatIdr(p.p90)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  );
}
