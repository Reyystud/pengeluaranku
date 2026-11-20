"use client";

import { Landmark, LayoutDashboard, LogOut, Receipt, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/auth/AuthProvider";
import { SkeletonRows } from "@/components/ui/states";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", key: "nav.dashboard", Icon: LayoutDashboard },
  { href: "/transactions", key: "nav.transactions", Icon: Receipt },
  { href: "/settings", key: "nav.settings", Icon: Settings },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const { status, user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated") {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <SkeletonRows rows={4} />
      </div>
    );
  }

  return (
    <div className="min-h-screen md:grid md:grid-cols-[14rem_1fr]">
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-card focus:p-3"
      >
        {t("nav.skip")}
      </a>
      <aside className="hidden border-r border-border bg-card p-4 md:flex md:flex-col md:justify-between">
        <div className="space-y-6">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <Landmark aria-hidden className="size-5 text-primary" />
            {t("app.short")}
          </p>
          <nav aria-label="Main" className="space-y-1">
            {NAV.map(({ href, key, Icon }) => (
              <NavLink key={href} href={href} active={pathname.startsWith(href)}>
                <Icon aria-hidden className="size-4" />
                {t(key)}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="space-y-2 text-sm">
          <p className="truncate text-muted-foreground">{user?.display_name}</p>
          <button
            onClick={() => void logout()}
            className="flex min-h-9 w-full items-center gap-2 rounded-md px-3 hover:bg-muted"
          >
            <LogOut aria-hidden className="size-4" />
            {t("nav.logout")}
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-col pb-16 md:pb-0">
        <main id="content" className="mx-auto w-full max-w-5xl flex-1 p-4 md:p-6">
          {children}
        </main>
      </div>
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-border bg-card md:hidden"
      >
        {NAV.map(({ href, key, Icon }) => (
          <Link
            key={href}
            href={href}
            aria-current={pathname.startsWith(href) ? "page" : undefined}
            className={cn(
              "flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs",
              pathname.startsWith(href) ? "font-semibold text-primary" : "text-muted-foreground",
            )}
          >
            <Icon aria-hidden className="size-5" />
            {t(key)}
          </Link>
        ))}
        <button
          onClick={() => void logout()}
          className="flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground"
        >
          <LogOut aria-hidden className="size-5" />
          {t("nav.logout")}
        </button>
      </nav>
    </div>
  );
}

function NavLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-9 items-center gap-2 rounded-md px-3 text-sm",
        active ? "bg-muted font-semibold" : "hover:bg-muted",
      )}
    >
      {children}
    </Link>
  );
}
