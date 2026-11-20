"use client";

import { AlertOctagon, AlertTriangle, Info } from "lucide-react";
import { useMemo, useState } from "react";
import type {
  Anomaly,
  AnomalySeverity,
  AnomalyStatus,
  AnomalyType,
  DismissReason,
} from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/field";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { formatDate } from "@/lib/format";
import { t } from "@/lib/i18n";
import { formatIdr } from "@/lib/money";
import { cn } from "@/lib/utils";
import { NO_FILTERS, useAnomalies, useAnomalyFeedback, type AnomalyFilters } from "./hooks";

const STATUSES: AnomalyStatus[] = ["open", "confirmed", "dismissed", "historical"];
const SEVERITIES: AnomalySeverity[] = ["high", "medium", "low"];
const TYPES: AnomalyType[] = [
  "amount_spike",
  "frequency_burst",
  "new_merchant_high_value",
  "category_surge",
  "amount_low",
];
const REASONS: DismissReason[] = ["expected_purchase", "wrong_amount", "not_mine", "other"];

const SEVERITY_STYLE: Record<AnomalySeverity, { cls: string; Icon: typeof Info }> = {
  high: { cls: "bg-danger-bg text-danger", Icon: AlertOctagon },
  medium: { cls: "bg-warning-bg text-warning", Icon: AlertTriangle },
  low: { cls: "bg-info-bg text-info", Icon: Info },
};

/** Severity is never colour alone (PRD 8.2): icon plus the word. */
export function SeverityBadge({ severity }: { severity: AnomalySeverity }) {
  const { cls, Icon } = SEVERITY_STYLE[severity];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        cls,
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {t(`intel.severity.${severity}`)}
    </span>
  );
}

export function AnomaliesView() {
  const [filters, setFilters] = useState<AnomalyFilters>(NO_FILTERS);
  const query = useAnomalies(filters);
  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const filtered = filters.status !== "" || filters.severity !== "" || filters.type !== "";

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("intel.alertsIntro")}</p>

      <div className="grid gap-3 sm:grid-cols-3">
        <FilterSelect
          label={t("intel.filterStatus")}
          value={filters.status}
          options={STATUSES.map((v) => [v, t(`intel.status.${v}`)])}
          onChange={(status) => setFilters({ ...filters, status: status as AnomalyStatus | "" })}
        />
        <FilterSelect
          label={t("intel.filterSeverity")}
          value={filters.severity}
          options={SEVERITIES.map((v) => [v, t(`intel.severity.${v}`)])}
          onChange={(severity) =>
            setFilters({ ...filters, severity: severity as AnomalySeverity | "" })
          }
        />
        <FilterSelect
          label={t("intel.filterType")}
          value={filters.type}
          options={TYPES.map((v) => [v, t(`intel.type.${v}`)])}
          onChange={(type) => setFilters({ ...filters, type: type as AnomalyType | "" })}
        />
      </div>

      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.isPending ? (
        <SkeletonRows rows={3} />
      ) : items.length === 0 ? (
        <EmptyState message={filtered ? t("intel.emptyFiltered") : t("intel.empty")} />
      ) : (
        <ul className="space-y-3">
          {items.map((a) => (
            <li key={a.id}>
              <AnomalyCard anomaly={a} />
            </li>
          ))}
        </ul>
      )}
      {query.hasNextPage ? (
        <Button
          variant="secondary"
          onClick={() => void query.fetchNextPage()}
          disabled={query.isFetchingNextPage}
        >
          {t("common.loadMore")}
        </Button>
      ) : null}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  return (
    <label className="space-y-1 text-sm font-medium">
      <span className="block">{label}</span>
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("intel.all")}</option>
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </Select>
    </label>
  );
}

export function AnomalyCard({ anomaly: a }: { anomaly: Anomaly }) {
  const { timeZone } = useAuth();
  const tx = a.transaction;
  const title = tx ? (tx.merchant ?? tx.description) : (a.category?.name ?? t("intel.surgeNoTx"));
  return (
    <article className="space-y-3 rounded-lg border border-border bg-card p-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate font-semibold">{title}</h2>
          <p className="text-xs text-muted-foreground">
            {t(`intel.type.${a.anomaly_type}`)}
            {a.category && tx ? ` · ${a.category.name}` : ""}
            {tx ? ` · ${formatDate(tx.transaction_date, timeZone, true)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <SeverityBadge severity={a.severity} />
          {a.is_alert ? (
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
              {t("intel.alertBadge")}
            </span>
          ) : null}
          {a.history_level === "limited" ? (
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
              {t("intel.limitedBadge")}
            </span>
          ) : null}
          <span className="rounded-full border border-border px-2 py-0.5 text-xs">
            {t(`intel.status.${a.status}`)}
          </span>
        </div>
      </header>
      {tx ? <p className="text-lg font-bold tabular-nums">{formatIdr(tx.amount)}</p> : null}
      <section aria-label={t("intel.why")}>
        <h3 className="text-sm font-medium">{t("intel.why")}</h3>
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">
          {a.reasons.map((r) => (
            <li key={r.code}>{r.message}</li>
          ))}
        </ul>
      </section>
      {a.status === "open" || a.status === "historical" ? <FeedbackForm anomaly={a} /> : null}
      {a.status === "confirmed" || a.status === "dismissed" ? (
        <p className="text-sm text-muted-foreground">
          {t("intel.feedbackGiven", { status: t(`intel.status.${a.status}`).toLowerCase() })}
          {a.feedback_reason ? ` (${t(`intel.reason.${a.feedback_reason}`)})` : ""}
        </p>
      ) : null}
    </article>
  );
}

function FeedbackForm({ anomaly: a }: { anomaly: Anomaly }) {
  const feedback = useAnomalyFeedback();
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState<DismissReason | "">("");
  const id = `dismiss-${a.id}`;
  return (
    <div className="space-y-2">
      {dismissing ? (
        <div className="space-y-2">
          <label htmlFor={id} className="block text-sm font-medium">
            {t("intel.dismissWhy")}
          </label>
          <Select
            id={id}
            value={reason}
            onChange={(e) => setReason(e.target.value as DismissReason | "")}
          >
            <option value="">{t("common.optional")}</option>
            {REASONS.map((r) => (
              <option key={r} value={r}>
                {t(`intel.reason.${r}`)}
              </option>
            ))}
          </Select>
          <p className="text-xs text-muted-foreground">{t("intel.reasonHint")}</p>
          <div className="flex gap-2">
            <Button
              disabled={feedback.isPending}
              onClick={() =>
                feedback.mutate({ id: a.id, action: "dismiss", reason: reason || undefined })
              }
            >
              {t("intel.send")}
            </Button>
            <Button variant="ghost" onClick={() => setDismissing(false)}>
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            disabled={feedback.isPending}
            onClick={() => feedback.mutate({ id: a.id, action: "confirm" })}
          >
            {t("intel.confirm")}
          </Button>
          <Button variant="secondary" onClick={() => setDismissing(true)}>
            {t("intel.dismiss")}
          </Button>
        </div>
      )}
      {feedback.isError ? <ErrorState error={feedback.error} /> : null}
    </div>
  );
}
