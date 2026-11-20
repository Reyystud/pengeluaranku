"use client";

import { AlertTriangle, CheckCircle2, Copy, Download, Upload } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { api, request } from "@/api/client";
import type { CommitResult, ImportPreview, StagedRow } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/field";
import { ErrorState } from "@/components/ui/states";
import { useCategories } from "@/features/transactions/hooks";
import { formatDate } from "@/lib/format";
import { t } from "@/lib/i18n";
import { formatIdr } from "@/lib/money";

const STATUS_ICON = { valid: CheckCircle2, invalid: AlertTriangle, duplicate: Copy } as const;
const STATUS_STYLE = {
  valid: "bg-success-bg text-success",
  invalid: "bg-danger-bg text-danger",
  duplicate: "bg-warning-bg text-warning",
} as const;

function RowStatus({ status }: { status: StagedRow["status"] }) {
  const Icon = STATUS_ICON[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status]}`}
    >
      <Icon aria-hidden className="size-3.5" />
      {status}
    </span>
  );
}

export function ImportView() {
  const categories = useCategories().data ?? [];
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [rows, setRows] = useState<StagedRow[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [skipInvalid, setSkipInvalid] = useState(false);
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  const [result, setResult] = useState<CommitResult | null>(null);
  const idempotencyKey = useRef<string>(crypto.randomUUID());

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const upload = () =>
    run(async () => {
      if (!file) return;
      const form = new FormData();
      form.append("file", file);
      const data = await api.post<ImportPreview>("/transactions/imports", undefined, { form });
      setPreview(data);
      setRows(data.rows);
      setCursor(data.next_cursor);
      setOverrides({});
      idempotencyKey.current = crypto.randomUUID();
    });

  const loadMore = () =>
    run(async () => {
      if (!preview || !cursor) return;
      const page = await api.get<ImportPreview>(`/transactions/imports/${preview.import_id}`, {
        cursor,
      });
      setRows((r) => [...r, ...page.rows]);
      setCursor(page.next_cursor);
    });

  const downloadTemplate = () =>
    run(async () => {
      const csv = await request<string>("/transactions/imports/template.csv", { raw: true });
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "transactions-template.csv";
      a.click();
      URL.revokeObjectURL(url);
    });

  const summary = preview?.summary;
  const importable = useMemo(() => {
    if (!summary) return 0;
    return summary.valid + (skipDuplicates ? 0 : summary.duplicate);
  }, [summary, skipDuplicates]);
  const blocked = !!summary && summary.invalid > 0 && !skipInvalid;

  const commit = () =>
    run(async () => {
      if (!preview) return;
      const changed = Object.fromEntries(
        Object.entries(overrides).filter(
          ([n, slug]) => rows.find((r) => String(r.row_number) === n)?.values?.category !== slug,
        ),
      );
      const data = await api.post<CommitResult>(
        `/transactions/imports/${preview.import_id}/commit`,
        {
          mode: skipInvalid ? "skip_invalid" : "strict",
          skip_duplicates: skipDuplicates,
          category_overrides: changed,
        },
        { headers: { "Idempotency-Key": idempotencyKey.current } },
      );
      setResult(data);
    });

  if (result) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">{t("import.resultTitle")}</h1>
        <ul className="space-y-1" role="status">
          <li>{t("import.committed", { count: result.committed_count })}</li>
          <li>{t("import.skippedInvalid", { count: result.skipped_invalid })}</li>
          <li>{t("import.skippedDuplicates", { count: result.skipped_duplicates })}</li>
        </ul>
        <div className="flex gap-2">
          <Link
            href="/transactions"
            className="inline-flex min-h-11 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground sm:min-h-9"
          >
            {t("import.viewTransactions")}
          </Link>
          <Button
            variant="secondary"
            onClick={() => {
              setResult(null);
              setPreview(null);
              setRows([]);
              setFile(null);
            }}
          >
            {t("import.another")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">{t("import.title")}</h1>
        <Button variant="secondary" onClick={downloadTemplate} disabled={busy}>
          <Download aria-hidden className="size-4" />
          {t("import.template")}
        </Button>
      </div>

      {!preview ? (
        <div className="space-y-3 rounded-lg border border-border bg-card p-4">
          <label htmlFor="csv-file" className="block text-sm font-medium">
            {t("import.drop")}
          </label>
          <Input
            id="csv-file"
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <Button onClick={upload} disabled={!file || busy}>
            <Upload aria-hidden className="size-4" />
            {t("import.upload")}
          </Button>
        </div>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {preview.filename} ·{" "}
            {t("import.expires", { when: formatDate(preview.expires_at, undefined, true) })}
          </p>
          <p className="flex flex-wrap gap-3 text-sm font-medium" role="status">
            <span>{t("import.rowsValid", { count: summary?.valid ?? 0 })}</span>
            <span>{t("import.rowsInvalid", { count: summary?.invalid ?? 0 })}</span>
            <span>{t("import.rowsDuplicate", { count: summary?.duplicate ?? 0 })}</span>
          </p>
          {preview.warnings.map((w) => (
            <p key={w.code} className="rounded-md bg-warning-bg p-2 text-sm text-warning">
              {w.message}
            </p>
          ))}

          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <caption className="sr-only">{t("import.title")}</caption>
              <thead className="bg-muted text-left">
                <tr>
                  <th scope="col" className="p-2">
                    {t("import.row")}
                  </th>
                  <th scope="col" className="p-2">
                    {t("import.status")}
                  </th>
                  <th scope="col" className="p-2">
                    {t("tx.description")}
                  </th>
                  <th scope="col" className="p-2 text-right">
                    {t("tx.amount")}
                  </th>
                  <th scope="col" className="p-2">
                    {t("tx.category")}
                  </th>
                  <th scope="col" className="p-2">
                    {t("import.problems")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const v = row.values;
                  const n = String(row.row_number);
                  const type = v?.transaction_type;
                  const options = categories.filter(
                    (c) =>
                      c.slug !== "uncategorized" &&
                      (c.transaction_type === "any" || c.transaction_type === type),
                  );
                  return (
                    <tr key={row.row_number} className="border-t border-border align-top">
                      <td className="p-2 tabular-nums">{row.row_number}</td>
                      <td className="p-2">
                        <RowStatus status={row.status} />
                      </td>
                      <td className="p-2">{v?.description ?? "—"}</td>
                      <td className="p-2 text-right tabular-nums">
                        {v ? formatIdr(v.amount) : "—"}
                      </td>
                      <td className="p-2">
                        {v ? (
                          <Select
                            aria-label={`Category for row ${row.row_number}`}
                            value={overrides[n] ?? v.category}
                            onChange={(e) => setOverrides((o) => ({ ...o, [n]: e.target.value }))}
                            className="min-w-40"
                          >
                            {v.category === "uncategorized" ? (
                              <option value="uncategorized">{t("tx.status.needs_review")}</option>
                            ) : null}
                            {options.map((c) => (
                              <option key={c.slug} value={c.slug}>
                                {c.name}
                              </option>
                            ))}
                          </Select>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="p-2 text-xs">
                        {row.errors.map((e) => (
                          <div key={`${e.column}-${e.code}`} className="text-danger">
                            {e.column}: {e.message}
                          </div>
                        ))}
                        {row.status === "duplicate" ? (
                          <div className="text-warning">{t("tx.duplicateBanner")}</div>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {cursor ? (
            <div className="flex justify-center">
              <Button variant="secondary" onClick={loadMore} disabled={busy}>
                {t("common.loadMore")}
              </Button>
            </div>
          ) : null}

          <fieldset className="space-y-2 rounded-lg border border-border bg-card p-4">
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={skipInvalid}
                onChange={(e) => setSkipInvalid(e.target.checked)}
              />
              {t("import.modeSkip")}
            </label>
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={skipDuplicates}
                onChange={(e) => setSkipDuplicates(e.target.checked)}
              />
              {t("import.skipDuplicates")}
            </label>
            {blocked ? <p className="text-xs text-danger">{t("import.modeStrict")}</p> : null}
            <Button onClick={commit} disabled={busy || blocked || importable === 0}>
              {t("import.commit", { count: importable })}
            </Button>
          </fieldset>
        </>
      )}
      {error ? <ErrorState error={error} /> : null}
    </div>
  );
}
