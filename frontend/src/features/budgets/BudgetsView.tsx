"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { History, Pencil, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "@/api/errors";
import type { Budget } from "@/api/types";
import { Button } from "@/components/ui/button";
import { BudgetStatusBadge, UtilizationBar } from "@/components/ui/budget-status";
import { Drawer } from "@/components/ui/drawer";
import { Field, Input, Select } from "@/components/ui/field";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { formatDay } from "@/lib/format";
import { t } from "@/lib/i18n";
import { formatIdr, parseMoney } from "@/lib/money";
import { useCategories } from "@/features/transactions/hooks";
import {
  useBudgetHistory,
  useBudgets,
  useCreateBudget,
  useDeleteBudget,
  useUpdateBudget,
} from "./hooks";

/** "80, 100" -> [80, 100]; null when invalid (FR-05.05: integers 1..200, at most 10). */
export function parseThresholds(input: string): number[] | null {
  const parts = input
    .split(/[,\s]+/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length > 10) return null;
  const out: number[] = [];
  for (const p of parts) {
    if (!/^\d{1,3}$/.test(p)) return null;
    const n = Number(p);
    if (n < 1 || n > 200) return null;
    out.push(n);
  }
  return [...new Set(out)].sort((a, b) => a - b);
}

export function BudgetsView() {
  const query = useBudgets();
  const [drawer, setDrawer] = useState<{ open: boolean; budget: Budget | null }>({
    open: false,
    budget: null,
  });
  const items = query.data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t("budget.title")}</h1>
        <Button onClick={() => setDrawer({ open: true, budget: null })}>
          <Plus aria-hidden className="size-4" />
          {t("budget.add")}
        </Button>
      </div>

      {query.data?.category_limits_exceed_overall ? (
        <p
          role="note"
          className="rounded-lg border border-warning/40 bg-warning-bg px-4 py-3 text-sm text-warning"
        >
          {t("budget.warnExceed")}
        </p>
      ) : null}

      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.isPending ? (
        <SkeletonRows rows={3} />
      ) : items.length === 0 ? (
        <EmptyState message={t("budget.empty")} />
      ) : (
        <ul className="grid gap-4 md:grid-cols-2">
          {items.map((b) => (
            <li key={b.id}>
              <BudgetCard budget={b} onEdit={() => setDrawer({ open: true, budget: b })} />
            </li>
          ))}
        </ul>
      )}

      <Drawer
        open={drawer.open}
        onOpenChange={(open) => setDrawer((d) => ({ ...d, open }))}
        title={drawer.budget ? t("budget.editTitle") : t("budget.addTitle")}
      >
        {drawer.open ? (
          <BudgetForm
            key={drawer.budget?.id ?? "new"}
            budget={drawer.budget}
            existing={items}
            onDone={() => setDrawer({ open: false, budget: null })}
          />
        ) : null}
      </Drawer>
    </div>
  );
}

function BudgetCard({ budget: b, onEdit }: { budget: Budget; onEdit: () => void }) {
  const [showHistory, setShowHistory] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteBudget();
  const name = b.category?.name ?? t("budget.overall");
  const over = b.remaining.startsWith("-");
  return (
    <article className="space-y-3 rounded-lg border border-border bg-card p-4">
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate font-semibold">{name}</h2>
          <p className="text-xs text-muted-foreground">
            {t("budget.period", { start: formatDay(b.period.start), end: formatDay(b.period.end) })}
          </p>
        </div>
        <BudgetStatusBadge status={b.status} />
      </header>
      <UtilizationBar percent={b.utilization} status={b.status} label={name} />
      <p className="text-sm">
        <strong className="tabular-nums">{formatIdr(b.spent)}</strong> {t("budget.of")}{" "}
        <span className="tabular-nums">{formatIdr(b.limit_amount)}</span> ·{" "}
        {t("budget.utilization", { percent: b.utilization })}
      </p>
      <p className="text-sm text-muted-foreground">
        {over
          ? `${t("budget.over")} ${formatIdr(b.remaining.replace("-", ""))}`
          : `${t("budget.remaining")} ${formatIdr(b.remaining)}`}
        {b.projected ? ` · ${t(`budget.projected.${b.projected}`)}` : ""}
      </p>
      <p className="text-xs text-muted-foreground">
        {t("budget.thresholds")}:{" "}
        {b.alert_thresholds.length ? b.alert_thresholds.join(", ") + "%" : t("common.none")}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={onEdit}>
          <Pencil aria-hidden className="size-4" />
          {t("common.edit")}
        </Button>
        <Button
          variant="ghost"
          onClick={() => setShowHistory((v) => !v)}
          aria-expanded={showHistory}
        >
          <History aria-hidden className="size-4" />
          {showHistory ? t("budget.historyHide") : t("budget.history")}
        </Button>
        {confirming ? (
          <>
            <Button
              variant="danger"
              disabled={remove.isPending}
              onClick={() => remove.mutate(b.id)}
              aria-label={`${t("budget.delete")}: ${name}`}
            >
              {t("common.confirm")}
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              {t("common.cancel")}
            </Button>
          </>
        ) : (
          <Button
            variant="ghost"
            onClick={() => setConfirming(true)}
            aria-label={`${t("budget.delete")}: ${name}`}
          >
            <Trash2 aria-hidden className="size-4" />
            {t("common.delete")}
          </Button>
        )}
      </div>
      {confirming ? (
        <p className="text-xs text-muted-foreground">{t("budget.deleteConfirm")}</p>
      ) : null}
      {remove.isError ? <ErrorState error={remove.error} /> : null}
      {showHistory ? <History_ id={b.id} /> : null}
    </article>
  );
}

function History_({ id }: { id: string }) {
  const query = useBudgetHistory(id, true);
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.isPending) return <SkeletonRows rows={2} />;
  if (query.data.items.length === 0)
    return <p className="text-sm text-muted-foreground">{t("budget.historyEmpty")}</p>;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-muted-foreground">
        <tr>
          <th className="py-1 font-medium">{t("budget.historyCol.period")}</th>
          <th className="py-1 text-right font-medium">{t("budget.historyCol.limit")}</th>
          <th className="py-1 text-right font-medium">{t("budget.historyCol.spent")}</th>
          <th className="py-1 text-right font-medium">{t("budget.historyCol.used")}</th>
        </tr>
      </thead>
      <tbody>
        {query.data.items.map((h) => (
          <tr key={h.period_id} className="border-t border-border">
            <td className="py-1">{formatDay(h.period_id)}</td>
            <td className="py-1 text-right tabular-nums">{formatIdr(h.limit_amount)}</td>
            <td className="py-1 text-right tabular-nums">{formatIdr(h.spent)}</td>
            <td className="py-1 text-right tabular-nums">{h.utilization}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const schema = z.object({
  category: z.string(), // "" = overall
  limit: z.string().refine((v) => parseMoney(v) !== null, t("budget.limitInvalid")),
  thresholds: z.string().refine((v) => parseThresholds(v) !== null, t("budget.thresholdsInvalid")),
});
type Values = z.infer<typeof schema>;

function BudgetForm({
  budget,
  existing,
  onDone,
}: {
  budget: Budget | null;
  existing: Budget[];
  onDone: () => void;
}) {
  const categories = useCategories().data ?? [];
  const create = useCreateBudget();
  const update = useUpdateBudget();
  const taken = useMemo(() => new Set(existing.map((b) => b.category?.slug ?? "")), [existing]);
  // Budgets only exist for expense categories; "" stands for the overall budget.
  const options = [
    { slug: "", name: t("budget.overall") },
    ...categories.filter((c) => c.transaction_type === "expense"),
  ].filter((o) => !taken.has(o.slug));
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      category: options[0]?.slug ?? "",
      limit: budget ? budget.limit_amount.replace(/\.00$/, "") : "",
      thresholds: (budget?.alert_thresholds ?? [80, 100]).join(", "),
    },
  });
  const mutation = budget ? update : create;
  const conflict = mutation.error instanceof ApiError && mutation.error.code === "BUDGET_EXISTS";

  const submit = handleSubmit(async (values) => {
    const limit_amount = parseMoney(values.limit);
    const alert_thresholds = parseThresholds(values.thresholds);
    if (!limit_amount || !alert_thresholds) return;
    try {
      if (budget)
        await update.mutateAsync({ id: budget.id, body: { limit_amount, alert_thresholds } });
      else
        await create.mutateAsync({
          category: values.category || null,
          limit_amount,
          alert_thresholds,
        });
    } catch {
      return; // the error is shown from the mutation state below; keep the drawer open
    }
    onDone();
  });

  if (!budget && options.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("budget.noMoreCategories")}</p>;
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      {budget ? (
        <p className="text-sm">
          <span className="text-muted-foreground">{t("budget.category")}: </span>
          <strong>{budget.category?.name ?? t("budget.overall")}</strong>
        </p>
      ) : (
        <Field id="budget-category" label={t("budget.category")}>
          <Select {...register("category")}>
            {options.map((o) => (
              <option key={o.slug} value={o.slug}>
                {o.name}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Field
        id="budget-limit"
        label={t("budget.limit")}
        hint={t("budget.limitHint")}
        error={errors.limit?.message}
      >
        <Input inputMode="decimal" autoComplete="off" {...register("limit")} />
      </Field>
      <Field
        id="budget-thresholds"
        label={t("budget.thresholds")}
        hint={t("budget.thresholdsHint")}
        error={errors.thresholds?.message}
      >
        <Input autoComplete="off" {...register("thresholds")} />
      </Field>
      {conflict ? (
        <p role="alert" className="text-sm text-danger">
          {t("budget.exists")}
        </p>
      ) : mutation.isError ? (
        <ErrorState error={mutation.error} />
      ) : null}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {t("common.save")}
        </Button>
      </div>
    </form>
  );
}
