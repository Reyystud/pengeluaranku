"use client";

import { Bell, BellOff } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { useAuth } from "@/auth/AuthProvider";
import { formatDate } from "@/lib/format";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useMarkAllRead, useMarkRead, useNotifications, useUnreadCount } from "./hooks";

export function NotificationsView() {
  const { timeZone } = useAuth();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const query = useNotifications(unreadOnly);
  const unread = useUnreadCount().data?.count ?? 0;
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();
  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t("notif.title")}</h1>
        <Button
          variant="secondary"
          disabled={unread === 0 || markAll.isPending}
          onClick={() => markAll.mutate()}
        >
          {t("common.markAllRead")}
        </Button>
      </div>
      <div role="group" aria-label={t("notif.title")} className="flex gap-2">
        {[
          { value: false, label: t("notif.all") },
          { value: true, label: t("notif.unread") },
        ].map((o) => (
          <Button
            key={String(o.value)}
            variant={unreadOnly === o.value ? "primary" : "secondary"}
            aria-pressed={unreadOnly === o.value}
            onClick={() => setUnreadOnly(o.value)}
          >
            {o.label}
          </Button>
        ))}
      </div>

      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.isPending ? (
        <SkeletonRows rows={4} />
      ) : items.length === 0 ? (
        <EmptyState message={t("notif.empty")} />
      ) : (
        <ul className="space-y-2">
          {items.map((n) => (
            <li
              key={n.id}
              className={cn(
                "flex items-start gap-3 rounded-lg border border-border p-4",
                n.read_at ? "bg-card" : "bg-info-bg",
              )}
            >
              {n.read_at ? (
                <BellOff aria-hidden className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
              ) : (
                <Bell aria-hidden className="mt-0.5 size-5 shrink-0 text-info" />
              )}
              <div className="min-w-0 flex-1 space-y-1">
                <p className="font-medium">
                  {n.title}
                  {n.read_at ? null : <span className="sr-only"> ({t("notif.unread")})</span>}
                </p>
                <p className="text-sm text-muted-foreground">{n.body}</p>
                <p className="text-xs text-muted-foreground">
                  {formatDate(n.created_at, timeZone, true)}
                </p>
                <div className="flex flex-wrap gap-3 pt-1 text-sm">
                  {n.link ? (
                    <Link href={n.link} className="font-medium text-primary underline">
                      {t("notif.open")}
                    </Link>
                  ) : null}
                  {n.read_at ? null : (
                    <button
                      className="font-medium underline"
                      onClick={() => markRead.mutate(n.id)}
                      disabled={markRead.isPending}
                    >
                      {t("common.markRead")}
                    </button>
                  )}
                </div>
              </div>
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
