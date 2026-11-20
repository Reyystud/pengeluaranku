"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";

/**
 * A chart with a plain-text summary and a data-table toggle (PRD 8.2: charts have a textual
 * summary and a table view). The summary is visible, not hidden, so it helps everyone.
 */
export function ChartFrame({
  title,
  summary,
  chart,
  table,
}: {
  title: string;
  summary: string;
  chart: React.ReactNode;
  table: React.ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  const id = useId();
  return (
    <section aria-labelledby={id} className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={id} className="font-semibold">
          {title}
        </h2>
        <Button
          variant="ghost"
          className="min-h-8 px-2 text-xs"
          onClick={() => setShowTable((v) => !v)}
        >
          {showTable ? t("common.showChart") : t("common.showTable")}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">{summary}</p>
      {showTable ? table : chart}
    </section>
  );
}
