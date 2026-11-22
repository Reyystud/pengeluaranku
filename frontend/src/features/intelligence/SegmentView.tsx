"use client";

import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { formatDay } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useSegment } from "./segment-hooks";

/** FR-13.04: segment name, description and 2 to 3 traits ("higher than 70% of similar users"). */
export function SegmentView() {
  const query = useSegment();
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.isPending) return <SkeletonRows rows={3} />;
  const data = query.data;
  const seg = data.segment;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("segment.intro")}</p>
      {seg === null || seg === undefined ? (
        <EmptyState
          message={t(`segment.reason.${data.reason ?? "NOT_COMPUTED"}`, {
            required: data.required_periods,
            have: data.complete_periods,
          })}
        />
      ) : (
        <section className="space-y-3 rounded-lg border border-border bg-card p-4">
          <p className="text-xs font-medium uppercase text-muted-foreground">
            {t("segment.yourSegment")}
          </p>
          <h2 className="text-xl font-semibold">{seg.name}</h2>
          <p className="text-sm">{seg.description}</p>
          <div>
            <h3 className="text-sm font-semibold">{t("segment.traits")}</h3>
            {seg.traits.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("segment.noTraits")}</p>
            ) : (
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                {seg.traits.map((trait) => (
                  <li key={trait.feature}>{trait.message}</li>
                ))}
              </ul>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {t("segment.computedAt", {
              date: formatDay(seg.computed_at.slice(0, 10)),
              version: seg.model_version,
            })}
          </p>
        </section>
      )}
    </div>
  );
}
