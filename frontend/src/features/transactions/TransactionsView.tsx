"use client";

import { Plus, Upload } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { Transaction } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/field";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { useDebounced } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import {
  EMPTY_FILTERS,
  useCategories,
  useConfirmCategory,
  useDeleteTransactions,
  useDismissDuplicate,
  useReviewCount,
  useTransactions,
  type Filters,
} from "./hooks";
import { TransactionDrawer } from "./TransactionDrawer";
import { TransactionList } from "./TransactionList";

export function TransactionsView() {
  const { timeZone } = useAuth();
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const q = useDebounced(filters.q, 300);
  const applied = useMemo(() => ({ ...filters, q }), [filters, q]);
  const query = useTransactions(applied);
  const categories = useCategories().data ?? [];
  const reviewCount = useReviewCount().data?.count;
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drawer, setDrawer] = useState<{ open: boolean; tx: Transaction | null }>({
    open: false,
    tx: null,
  });
  const remove = useDeleteTransactions();
  const confirm = useConfirmCategory();
  const dismiss = useDismissDuplicate();

  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => {
    setSelected(new Set());
    setFilters((f) => ({ ...f, [key]: value }));
  };
  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t("tx.title")}</h1>
        <div className="flex gap-2">
          <Link
            href="/transactions/import"
            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-card px-4 text-sm font-medium hover:bg-muted sm:min-h-9"
          >
            <Upload aria-hidden className="size-4" />
            {t("tx.import")}
          </Link>
          <Button onClick={() => setDrawer({ open: true, tx: null })}>
            <Plus aria-hidden className="size-4" />
            {t("tx.add")}
          </Button>
        </div>
      </div>

      <div role="tablist" aria-label={t("tx.title")} className="flex gap-1 border-b border-border">
        {[
          { review: false, label: t("tx.tabAll") },
          { review: true, label: t("tx.tabReview") },
        ].map((tab) => (
          <button
            key={String(tab.review)}
            role="tab"
            aria-selected={filters.review === tab.review}
            onClick={() => set("review", tab.review)}
            className={cn(
              "min-h-11 border-b-2 px-4 text-sm font-medium sm:min-h-9",
              filters.review === tab.review
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground",
            )}
          >
            {tab.label}
            {tab.review && reviewCount ? (
              <span className="ml-2 rounded-full bg-danger-bg px-2 py-0.5 text-xs text-danger">
                {reviewCount}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <Input
          type="search"
          aria-label={t("tx.searchPlaceholder")}
          placeholder={t("tx.searchPlaceholder")}
          value={filters.q}
          onChange={(e) => set("q", e.target.value)}
          className="lg:col-span-2"
        />
        <Select
          aria-label={t("tx.type")}
          value={filters.type}
          onChange={(e) => set("type", e.target.value as Filters["type"])}
        >
          <option value="">{t("tx.allTypes")}</option>
          <option value="expense">{t("tx.expense")}</option>
          <option value="income">{t("tx.income")}</option>
          <option value="transfer">{t("tx.transfer")}</option>
        </Select>
        <Select
          aria-label={t("tx.category")}
          value={filters.category}
          onChange={(e) => set("category", e.target.value)}
        >
          <option value="">{t("tx.allCategories")}</option>
          {categories.map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.name}
            </option>
          ))}
        </Select>
        <div className="grid grid-cols-2 gap-2">
          <Input
            type="date"
            aria-label="From"
            value={filters.from}
            onChange={(e) => set("from", e.target.value)}
          />
          <Input
            type="date"
            aria-label="To"
            value={filters.to}
            onChange={(e) => set("to", e.target.value)}
          />
        </div>
      </div>

      {selected.size > 0 ? (
        <div className="flex items-center gap-3 rounded-md bg-muted p-2 text-sm">
          <span>{t("tx.selected", { count: selected.size })}</span>
          <Button
            variant="danger"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(t("tx.confirmDelete", { count: selected.size }))) {
                remove.mutate([...selected], { onSuccess: () => setSelected(new Set()) });
              }
            }}
          >
            {t("tx.deleteSelected")}
          </Button>
        </div>
      ) : null}

      {remove.isError ? <ErrorState error={remove.error} /> : null}
      {confirm.isError ? <ErrorState error={confirm.error} /> : null}
      {dismiss.isError ? <ErrorState error={dismiss.error} /> : null}

      {query.isPending ? (
        <SkeletonRows />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState message={filters.review ? t("tx.emptyReview") : t("tx.empty")} />
      ) : (
        <>
          <TransactionList
            items={items}
            selected={selected}
            timeZone={timeZone}
            onToggle={toggle}
            onToggleAll={() =>
              setSelected((s) =>
                items.every((tx) => s.has(tx.id)) ? new Set() : new Set(items.map((tx) => tx.id)),
              )
            }
            onEdit={(tx) => setDrawer({ open: true, tx })}
            onConfirm={(tx) => confirm.mutate(tx.id)}
            onDismissDuplicate={(tx) => dismiss.mutate(tx.id)}
          />
          {query.hasNextPage ? (
            <div className="flex justify-center">
              <Button
                variant="secondary"
                disabled={query.isFetchingNextPage}
                onClick={() => void query.fetchNextPage()}
              >
                {t("common.loadMore")}
              </Button>
            </div>
          ) : null}
        </>
      )}

      <TransactionDrawer
        open={drawer.open}
        transaction={drawer.tx}
        timeZone={timeZone}
        onOpenChange={(open) => setDrawer((d) => ({ ...d, open }))}
      />
    </div>
  );
}
