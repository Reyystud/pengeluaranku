"use client";

import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CategorySplit, Trends } from "@/api/types";
import { ChartFrame } from "@/components/ui/chart-frame";
import { formatDay, formatPercent } from "@/lib/format";
import { t } from "@/lib/i18n";
import { formatIdr } from "@/lib/money";

// Non-text graphics need 3:1 against the card; every slice also appears in the legend table,
// so color is never the only way to tell categories apart.
export const PALETTE = [
  "#2563eb",
  "#d97706",
  "#059669",
  "#db2777",
  "#7c3aed",
  "#0891b2",
  "#65a30d",
  "#dc2626",
];
const OTHER = "#64748b";
const MAX_SLICES = 7;

export interface Slice {
  slug: string;
  name: string;
  amount: string;
  share: string;
  count: number;
}

/** Keep the biggest categories and fold the rest into "Other" so the donut stays readable. */
export function sliceCategories(items: CategorySplit["items"]): Slice[] {
  if (items.length <= MAX_SLICES + 1) return items;
  const head = items.slice(0, MAX_SLICES);
  const rest = items.slice(MAX_SLICES);
  // Sums on cents as integers, never floats (PRD 4.3).
  const cents = (v: string) => BigInt(v.replace(".", ""));
  const total = rest.reduce((a, i) => a + cents(i.amount), 0n);
  const whole = (total / 100n).toString();
  const frac = (total % 100n).toString().padStart(2, "0");
  const share = rest.reduce((a, i) => a + Math.round(Number(i.share) * 10), 0) / 10;
  const count = rest.reduce((a, i) => a + i.count, 0);
  return [
    ...head,
    {
      slug: "other",
      name: t("dash.other"),
      amount: `${whole}.${frac}`,
      share: share.toFixed(1),
      count,
    },
  ];
}

export function CategoryDonut({ data }: { data: CategorySplit }) {
  const slices = sliceCategories(data.items);
  const top = slices[0];
  const colorOf = (i: number, slug: string) =>
    slug === "other" ? OTHER : PALETTE[i % PALETTE.length];
  return (
    <ChartFrame
      title={t("dash.categories")}
      summary={
        top
          ? t("dash.categoriesSummary", {
              total: formatIdr(data.total_expenses),
              name: top.name,
              share: top.share,
            })
          : t("dash.categoriesEmpty")
      }
      chart={
        <div className="grid items-center gap-4 sm:grid-cols-2">
          <div className="h-52" aria-hidden>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={slices.map((s) => ({ name: s.name, value: Number(s.amount) }))}
                  dataKey="value"
                  innerRadius="55%"
                  outerRadius="90%"
                  paddingAngle={1}
                  isAnimationActive={false}
                >
                  {slices.map((s, i) => (
                    <Cell key={s.slug} fill={colorOf(i, s.slug)} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="space-y-1.5 text-sm">
            {slices.map((s, i) => (
              <li key={s.slug} className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden
                    className="size-3 shrink-0 rounded-sm"
                    style={{ background: colorOf(i, s.slug) }}
                  />
                  <span className="truncate">{s.name}</span>
                </span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {formatIdr(s.amount)} · {formatPercent(s.share)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      }
      table={
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 font-medium">{t("dash.col.category")}</th>
              <th className="py-1 text-right font-medium">{t("dash.col.amount")}</th>
              <th className="py-1 text-right font-medium">{t("dash.col.share")}</th>
              <th className="py-1 text-right font-medium">{t("dash.col.count")}</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((s) => (
              <tr key={s.slug} className="border-t border-border">
                <td className="py-1">{s.name}</td>
                <td className="py-1 text-right tabular-nums">{formatIdr(s.amount)}</td>
                <td className="py-1 text-right tabular-nums">{formatPercent(s.share)}</td>
                <td className="py-1 text-right tabular-nums">{s.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    />
  );
}

/** Millions as "1,5 jt" style short labels would need locale work; plain thousands keep it exact. */
const axis = (v: number) =>
  v >= 1_000_000 ? `${v / 1_000_000}M` : v >= 1000 ? `${v / 1000}k` : `${v}`;

export function TrendChart({ data }: { data: Trends }) {
  const rows = data.series.map((p) => ({
    label: formatDay(p.start),
    daily: Number(p.expenses),
    cumulative: p.cumulative === null ? null : Number(p.cumulative),
    pace: p.budget_pace === null ? null : Number(p.budget_pace),
  }));
  const spent = data.series.reduce((a, p) => a + BigInt(p.expenses.replace(".", "")), 0n);
  const total = `${spent / 100n}.${(spent % 100n).toString().padStart(2, "0")}`;
  const pace = data.budget_limit
    ? t("dash.trendPace", { limit: formatIdr(data.budget_limit) })
    : "";
  const empty = spent === 0n;
  return (
    <ChartFrame
      title={t("dash.trend")}
      summary={
        empty
          ? t("dash.trendEmpty")
          : t("dash.trendSummary", { total: formatIdr(total), days: data.series.length, pace })
      }
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
              <Bar
                dataKey="daily"
                name={t("dash.daily")}
                fill="#2563eb"
                isAnimationActive={false}
              />
              <Line
                dataKey="cumulative"
                name={t("dash.cumulative")}
                stroke="#d97706"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
              {data.budget_limit ? (
                <Line
                  dataKey="pace"
                  name={t("dash.pace")}
                  stroke="#64748b"
                  strokeWidth={2}
                  strokeDasharray="6 4"
                  dot={false}
                  isAnimationActive={false}
                />
              ) : null}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      }
      table={
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card text-left text-muted-foreground">
              <tr>
                <th className="py-1 font-medium">{t("dash.col.date")}</th>
                <th className="py-1 text-right font-medium">{t("dash.daily")}</th>
                <th className="py-1 text-right font-medium">{t("dash.col.cumulative")}</th>
                {data.budget_limit ? (
                  <th className="py-1 text-right font-medium">{t("dash.col.pace")}</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {data.series.map((p) => (
                <tr key={p.start} className="border-t border-border">
                  <td className="py-1">{formatDay(p.start)}</td>
                  <td className="py-1 text-right tabular-nums">{formatIdr(p.expenses)}</td>
                  <td className="py-1 text-right tabular-nums">
                    {p.cumulative === null ? "—" : formatIdr(p.cumulative)}
                  </td>
                  {data.budget_limit ? (
                    <td className="py-1 text-right tabular-nums">
                      {p.budget_pace === null ? "—" : formatIdr(p.budget_pace)}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      }
    />
  );
}
