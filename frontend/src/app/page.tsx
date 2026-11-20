import Link from "next/link";
import { t } from "@/lib/i18n";

export default function Landing() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-4 py-16">
      <p className="text-sm font-semibold tracking-wide text-primary">{t("app.name")}</p>
      <h1 className="text-4xl font-bold tracking-tight">{t("landing.title")}</h1>
      <p className="text-lg text-muted-foreground">{t("landing.body")}</p>
      <div className="flex flex-wrap gap-3">
        <Link
          href="/register"
          className="inline-flex min-h-11 items-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          {t("landing.register")}
        </Link>
        <Link
          href="/login"
          className="inline-flex min-h-11 items-center rounded-md border border-border bg-card px-5 text-sm font-medium hover:bg-muted"
        >
          {t("landing.login")}
        </Link>
      </div>
    </main>
  );
}
