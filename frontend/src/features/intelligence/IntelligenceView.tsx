"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { AnomaliesView } from "./AnomaliesView";
import { ForecastView } from "./ForecastView";

const TABS = [
  { id: "alerts", key: "intel.tabAlerts" },
  { id: "forecast", key: "intel.tabForecast" },
] as const;

export function IntelligenceView() {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("alerts");
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">{t("intel.title")}</h1>
      <div
        role="tablist"
        aria-label={t("intel.tabs")}
        className="flex gap-1 border-b border-border"
      >
        {TABS.map((x) => (
          <button
            key={x.id}
            role="tab"
            id={`tab-${x.id}`}
            aria-selected={tab === x.id}
            aria-controls={`panel-${x.id}`}
            onClick={() => setTab(x.id)}
            className={cn(
              "min-h-11 border-b-2 px-4 text-sm font-medium sm:min-h-9",
              tab === x.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t(x.key)}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "alerts" ? <AnomaliesView /> : <ForecastView />}
      </div>
    </div>
  );
}
