import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Category, CategorizePreviewOut } from "@/api/types";
import { CategoryChip } from "./CategoryChip";

const categories: Category[] = [
  { id: "1", slug: "food_beverage", name: "Food & Beverage", transaction_type: "expense" },
  { id: "2", slug: "groceries", name: "Groceries", transaction_type: "expense" },
  { id: "3", slug: "shopping", name: "Shopping", transaction_type: "expense" },
  { id: "9", slug: "uncategorized", name: "Uncategorized", transaction_type: "any" },
];

function preview(
  slug: string,
  status: string,
  over: Partial<CategorizePreviewOut["categorization"]> = {},
): CategorizePreviewOut {
  const c = categories.find((x) => x.slug === slug)!;
  return {
    category: { id: c.id, slug: c.slug, name: c.name },
    category_status: status,
    categorization: {
      decision: "auto_apply",
      source: "model",
      confidence: 0.9,
      alternatives: [
        { category: "groceries", confidence: 0.2 },
        { category: "shopping", confidence: 0.1 },
      ],
      model_version: "v1",
      predicted_category: "food_beverage",
      ml_error: null,
      ...over,
    },
  } as CategorizePreviewOut;
}

describe("CategoryChip (FR-03.07 live preview)", () => {
  it("auto: 'Food & Beverage · auto' with no quick picks", () => {
    render(
      <CategoryChip
        preview={preview("food_beverage", "auto")}
        loading={false}
        categories={categories}
        onPick={vi.fn()}
      />,
    );
    expect(screen.getByText("Food & Beverage · auto")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("rule: says it is the user's rule", () => {
    render(
      <CategoryChip
        preview={preview("groceries", "rule", { source: "rule" })}
        loading={false}
        categories={categories}
        onPick={vi.fn()}
      />,
    );
    expect(screen.getByText("Groceries · your rule")).toBeInTheDocument();
  });

  it("suggest: asks and offers quick picks that call onPick", async () => {
    const onPick = vi.fn();
    render(
      <CategoryChip
        preview={preview("groceries", "suggested")}
        loading={false}
        categories={categories}
        onPick={onPick}
      />,
    );
    expect(screen.getByText("Suggest: Groceries? (or choose)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Shopping" }));
    expect(onPick).toHaveBeenCalledWith("shopping");
  });

  it("needs review: shows the model's pick among the quick picks", async () => {
    const onPick = vi.fn();
    render(
      <CategoryChip
        preview={preview("uncategorized", "needs_review")}
        loading={false}
        categories={categories}
        onPick={onPick}
      />,
    );
    expect(screen.getByText("Not sure yet. Pick a category.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Food & Beverage" }));
    expect(onPick).toHaveBeenCalledWith("food_beverage");
  });

  it("ML down: says so instead of failing", () => {
    render(
      <CategoryChip
        preview={preview("uncategorized", "needs_review", {
          ml_error: "timeout",
          alternatives: [],
          predicted_category: null,
        })}
        loading={false}
        categories={categories}
        onPick={vi.fn()}
      />,
    );
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
  });

  it("renders nothing without a preview", () => {
    const { container } = render(
      <CategoryChip preview={undefined} loading={false} categories={categories} onPick={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
