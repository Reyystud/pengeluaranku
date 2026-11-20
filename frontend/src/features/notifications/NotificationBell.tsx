"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { t } from "@/lib/i18n";
import { useUnreadCount } from "./hooks";

/** Bell with the unread count; the count is in the accessible name, not only in the badge. */
export function NotificationBell() {
  const count = useUnreadCount().data?.count ?? 0;
  return (
    <Link
      href="/notifications"
      aria-label={count > 0 ? t("notif.bellUnread", { count }) : t("notif.bell")}
      className="relative grid size-11 place-items-center rounded-md hover:bg-muted sm:size-9"
    >
      <Bell aria-hidden className="size-5" />
      {count > 0 ? (
        <span
          aria-hidden
          className="absolute right-0.5 top-0.5 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-bold leading-4 text-background"
        >
          {count > 99 ? "99+" : count}
        </span>
      ) : null}
    </Link>
  );
}
