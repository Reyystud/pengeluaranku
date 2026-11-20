import { AlertOctagon, AlertTriangle, CheckCircle2, CircleDot } from "lucide-react";
import type { BudgetStatus } from "@/api/types";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const STYLE: Record<BudgetStatus, { cls: string; bar: string; Icon: typeof CheckCircle2 }> = {
  healthy: { cls: "bg-success-bg text-success", bar: "bg-success", Icon: CheckCircle2 },
  normal: { cls: "bg-info-bg text-info", bar: "bg-info", Icon: CircleDot },
  warning: { cls: "bg-warning-bg text-warning", bar: "bg-warning", Icon: AlertTriangle },
  exceeded: { cls: "bg-danger-bg text-danger", bar: "bg-danger", Icon: AlertOctagon },
};

/** Status is never color alone (PRD 8.2): icon plus the words Healthy / Normal / Warning / Exceeded. */
export function BudgetStatusBadge({ status }: { status: BudgetStatus }) {
  const { cls, Icon } = STYLE[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        cls,
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {t(`budget.status.${status}`)}
    </span>
  );
}

/** Utilization bar. The bar stops at 100% but the label keeps the real number. */
export function UtilizationBar({
  percent,
  status,
  label,
}: {
  percent: string;
  status: BudgetStatus;
  label: string;
}) {
  const value = Math.min(Math.max(Number(percent), 0), 100);
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value)}
      aria-valuetext={t("budget.utilization", { percent })}
      className="h-2.5 w-full overflow-hidden rounded-full bg-muted"
    >
      <div
        className={cn("h-full rounded-full", STYLE[status].bar)}
        style={{ width: `${value}%` }}
      />
    </div>
  );
}
