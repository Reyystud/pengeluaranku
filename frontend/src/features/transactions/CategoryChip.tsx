import { Loader2, Sparkles } from "lucide-react";
import type { Category, CategorizePreviewOut } from "@/api/types";
import { t } from "@/lib/i18n";

/**
 * Live categorization preview (FR-03.07): "Food & Beverage · auto", "Suggest: Groceries? (or choose)"
 * with quick picks, or a plain prompt when the model is unsure or unavailable.
 */
export function CategoryChip({
  preview,
  loading,
  categories,
  onPick,
}: {
  preview: CategorizePreviewOut | undefined;
  loading: boolean;
  categories: Category[];
  onPick: (slug: string) => void;
}) {
  if (loading && !preview) {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 aria-hidden className="size-4 animate-spin" />
        {t("common.loading")}
      </p>
    );
  }
  if (!preview) return null;

  const name = (slug: string | null | undefined) =>
    categories.find((c) => c.slug === slug)?.name ?? slug ?? "";
  const c = preview.categorization;
  let text: string;
  if (c.ml_error) text = t("preview.unavailable");
  else if (preview.category_status === "rule")
    text = t("preview.rule", { category: preview.category.name });
  else if (preview.category_status === "auto")
    text = t("preview.auto", { category: preview.category.name });
  else if (preview.category_status === "suggested")
    text = t("preview.suggest", { category: preview.category.name });
  else text = t("preview.review");

  const picks = [c.predicted_category, ...c.alternatives.map((a) => String(a.category))]
    .filter((slug): slug is string => !!slug && slug !== preview.category.slug)
    .filter((slug, i, all) => all.indexOf(slug) === i)
    .slice(0, 3);
  const showPicks = preview.category_status !== "auto" && preview.category_status !== "rule";

  return (
    <div aria-live="polite" className="space-y-2 rounded-md bg-muted p-3 text-sm">
      <p className="flex items-center gap-2 font-medium">
        <Sparkles aria-hidden className="size-4 text-primary" />
        {text}
      </p>
      {showPicks && picks.length ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">{t("preview.quickPicks")}:</span>
          {preview.category_status === "suggested" ? (
            <button
              type="button"
              onClick={() => onPick(preview.category.slug)}
              className="min-h-9 rounded-full border border-border bg-card px-3 hover:bg-background"
            >
              {preview.category.name}
            </button>
          ) : null}
          {picks.map((slug) => (
            <button
              key={slug}
              type="button"
              onClick={() => onPick(slug)}
              className="min-h-9 rounded-full border border-border bg-card px-3 hover:bg-background"
            >
              {name(slug)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
