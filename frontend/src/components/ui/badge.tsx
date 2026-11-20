import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  HelpCircle,
  Sparkles,
  UserCheck,
} from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const STYLE: Record<string, { cls: string; Icon: typeof CheckCircle2 }> = {
  auto: { cls: "bg-success-bg text-success", Icon: Sparkles },
  rule: { cls: "bg-info-bg text-info", Icon: CheckCircle2 },
  suggested: { cls: "bg-warning-bg text-warning", Icon: HelpCircle },
  needs_review: { cls: "bg-danger-bg text-danger", Icon: AlertTriangle },
  user_set: { cls: "bg-muted text-foreground", Icon: UserCheck },
  user_confirmed: { cls: "bg-muted text-foreground", Icon: UserCheck },
};

/** Category status: always an icon plus text, never color alone. */
export function StatusBadge({ status }: { status: string }) {
  const { cls, Icon } = STYLE[status] ?? { cls: "bg-muted text-foreground", Icon: CircleDashed };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        cls,
      )}
    >
      <Icon aria-hidden className="size-3.5" />
      {t(`tx.status.${status}`)}
    </span>
  );
}
