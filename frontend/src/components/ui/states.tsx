"use client";

import { AlertCircle, Inbox } from "lucide-react";
import { useState } from "react";
import { ApiError } from "@/api/errors";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div role="status" aria-label={t("common.loading")} className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ message, action }: { message: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border p-10 text-center">
      <Inbox aria-hidden className="size-8 text-muted-foreground" />
      <p className="text-muted-foreground">{message}</p>
      {action}
    </div>
  );
}

/** Error state with the API request_id and a Copy button (PRD 8.2). */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const [copied, setCopied] = useState(false);
  const message = error instanceof Error ? error.message : t("errors.generic");
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div
      role="alert"
      className="space-y-3 rounded-lg border border-danger/40 bg-danger-bg p-4 text-danger"
    >
      <p className="flex items-center gap-2 font-medium">
        <AlertCircle aria-hidden className="size-5" />
        {message}
      </p>
      {requestId ? (
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <span>
            {t("common.requestId")}: <code>{requestId}</code>
          </span>
          <Button
            variant="secondary"
            className="min-h-8 px-2 text-xs"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(requestId);
                setCopied(true);
              } catch {
                /* clipboard may be blocked */
              }
            }}
          >
            {copied ? t("common.copied") : t("common.copy")}
          </Button>
        </p>
      ) : null}
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          {t("common.retry")}
        </Button>
      ) : null}
    </div>
  );
}
