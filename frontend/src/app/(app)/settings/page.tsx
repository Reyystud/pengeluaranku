import type { Metadata } from "next";
import { EmptyState } from "@/components/ui/states";
import { t } from "@/lib/i18n";

export const metadata: Metadata = { title: "Settings" };
export default function Page() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">{t("nav.settings")}</h1>
      <EmptyState message={t("page.settingsSoon")} />
    </div>
  );
}
