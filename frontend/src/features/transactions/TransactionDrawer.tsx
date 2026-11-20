"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "@/api/errors";
import { PAYMENT_METHODS, type Transaction, type TransactionType } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { ErrorState } from "@/components/ui/states";
import { DEFAULT_TZ, localDate, nowLocalParts, toApiDate } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { t } from "@/lib/i18n";
import { formatIdr, parseMoney } from "@/lib/money";
import { CategoryChip } from "./CategoryChip";
import {
  useCategories,
  useCreateTransaction,
  usePreviewCategory,
  useUpdateTransaction,
} from "./hooks";

const schema = z.object({
  transaction_type: z.enum(["income", "expense", "transfer"]),
  amount: z.string().refine((v) => parseMoney(v) !== null, t("tx.amountInvalid")),
  description: z.string().trim().min(1, t("common.required")).max(200),
  merchant: z.string().trim().max(100),
  date: z.string().min(1, t("common.required")),
  time: z.string(),
  payment_method: z.string(),
  category: z.string(), // "" = let the model decide
  notes: z.string().max(500),
  apply_to_past: z.boolean(),
});
type Values = z.infer<typeof schema>;

function initialValues(tx: Transaction | null, tz: string): Values {
  if (!tx) {
    return {
      transaction_type: "expense",
      amount: "",
      description: "",
      merchant: "",
      date: nowLocalParts(tz).date,
      time: "",
      payment_method: "cash",
      category: "",
      notes: "",
      apply_to_past: false,
    };
  }
  const time = tx.has_time
    ? new Intl.DateTimeFormat("en-GB", {
        timeZone: tz,
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(tx.transaction_date))
    : "";
  return {
    transaction_type: tx.transaction_type as TransactionType,
    amount: tx.amount.replace(/\.00$/, ""),
    description: tx.description,
    merchant: tx.merchant ?? "",
    date: localDate(tx.transaction_date, tz),
    time,
    payment_method: tx.payment_method,
    category: tx.category.slug === "uncategorized" ? "" : tx.category.slug,
    notes: tx.notes ?? "",
    apply_to_past: false,
  };
}

export function TransactionDrawer({
  open,
  onOpenChange,
  transaction,
  timeZone = DEFAULT_TZ,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transaction: Transaction | null;
  timeZone?: string;
}) {
  // The drawer content unmounts when closed, so every opening starts from fresh form state.
  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title={transaction ? t("tx.editTitle") : t("tx.addTitle")}
    >
      <TransactionForm
        transaction={transaction}
        timeZone={timeZone}
        onDone={() => onOpenChange(false)}
      />
    </Drawer>
  );
}

function TransactionForm({
  transaction,
  timeZone,
  onDone,
}: {
  transaction: Transaction | null;
  timeZone: string;
  onDone: () => void;
}) {
  const open = true;
  const editing = transaction !== null;
  const categoryList = useCategories().data;
  const categories = useMemo(() => categoryList ?? [], [categoryList]);
  const create = useCreateTransaction();
  const update = useUpdateTransaction();
  const preview = usePreviewCategory();
  const [error, setError] = useState<unknown>(null);
  // One key per form attempt; a failed attempt gets a new one because its payload may change.
  const [idemKey, setIdemKey] = useState(() => crypto.randomUUID());

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: initialValues(transaction, timeZone),
  });
  const { errors } = form.formState;

  const [type, amountText, description, merchant, method, date, time, category] = useWatch({
    control: form.control,
    name: [
      "transaction_type",
      "amount",
      "description",
      "merchant",
      "payment_method",
      "date",
      "time",
      "category",
    ],
  });
  const amount = parseMoney(amountText ?? "");

  // Live categorization preview once the user stops typing for 400 ms (FR-03.07).
  const draft = useDebounced(
    {
      type,
      description: description?.trim(),
      merchant: merchant?.trim(),
      method,
      amount,
      date,
      time,
    },
    400,
  );
  const mutatePreview = preview.mutate;
  useEffect(() => {
    if (!open || editing || category || !draft.description) return;
    mutatePreview({
      description: draft.description,
      merchant: draft.merchant || null,
      amount: draft.amount,
      payment_method: draft.method,
      transaction_type: draft.type,
      transaction_date: draft.date ? toApiDate(draft.date, draft.time ?? "", timeZone) : null,
    });
  }, [open, editing, category, draft, mutatePreview, timeZone]);

  const options = useMemo(
    () =>
      categories.filter(
        (c) =>
          c.slug !== "uncategorized" &&
          (c.transaction_type === "any" || c.transaction_type === type),
      ),
    [categories, type],
  );

  const saving = create.isPending || update.isPending;

  async function submit(values: Values) {
    setError(null);
    const body = {
      transaction_type: values.transaction_type,
      amount: parseMoney(values.amount) as string,
      description: values.description.trim(),
      merchant: values.merchant.trim() || null,
      transaction_date: toApiDate(values.date, values.time, timeZone),
      payment_method: values.payment_method,
      notes: values.notes.trim() || null,
    };
    try {
      if (transaction) {
        const categoryChanged =
          values.category !== "" && values.category !== transaction.category.slug;
        await update.mutateAsync({
          id: transaction.id,
          body: {
            ...body,
            ...(categoryChanged ? { category: values.category } : {}),
            ...(categoryChanged && values.apply_to_past
              ? { apply_to_past_merchant_transactions: true }
              : {}),
          },
        });
      } else {
        await create.mutateAsync({
          body: { ...body, category: values.category || null },
          key: idemKey,
        });
      }
      onDone();
    } catch (e) {
      setIdemKey(crypto.randomUUID());
      if (e instanceof ApiError && e.errors.length) {
        let placed = false;
        for (const fe of e.errors) {
          const field = fe.field === "transaction_date" ? "date" : fe.field;
          if (field in values) {
            form.setError(field as keyof Values, { message: fe.message });
            placed = true;
          }
        }
        if (placed) return;
      }
      setError(e);
    }
  }

  const categoryChanged = editing && !!category && category !== transaction?.category.slug;

  return (
    <>
      <form noValidate onSubmit={form.handleSubmit(submit)} className="space-y-4">
        <Field id="tx-type" label={t("tx.type")}>
          <Select {...form.register("transaction_type")}>
            <option value="expense">{t("tx.expense")}</option>
            <option value="income">{t("tx.income")}</option>
            <option value="transfer">{t("tx.transfer")}</option>
          </Select>
        </Field>
        <Field
          id="tx-amount"
          label={t("tx.amount")}
          hint={amount ? formatIdr(amount) : t("tx.amountHint")}
          error={errors.amount?.message}
        >
          <Input inputMode="decimal" autoComplete="off" {...form.register("amount")} />
        </Field>
        <Field id="tx-description" label={t("tx.description")} error={errors.description?.message}>
          <Input maxLength={200} {...form.register("description")} />
        </Field>
        <Field id="tx-merchant" label={t("tx.merchant")} optional error={errors.merchant?.message}>
          <Input maxLength={100} {...form.register("merchant")} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field id="tx-date" label={t("tx.date")} error={errors.date?.message}>
            <Input type="date" {...form.register("date")} />
          </Field>
          <Field id="tx-time" label={t("tx.time")} optional>
            <Input type="time" {...form.register("time")} />
          </Field>
        </div>
        <Field id="tx-method" label={t("tx.paymentMethod")}>
          <Select {...form.register("payment_method")}>
            {PAYMENT_METHODS.map((m) => (
              <option key={m} value={m}>
                {m.replace("_", " ")}
              </option>
            ))}
          </Select>
        </Field>
        <Field id="tx-category" label={t("tx.category")} optional={!editing}>
          <Select {...form.register("category")}>
            <option value="">{editing ? t("tx.chooseCategory") : "Auto"}</option>
            {options.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
        {!editing && !category ? (
          <CategoryChip
            preview={preview.data}
            loading={preview.isPending && preview.isIdle === false}
            categories={categories}
            onPick={(slug) => form.setValue("category", slug, { shouldDirty: true })}
          />
        ) : null}
        {categoryChanged ? (
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <input type="checkbox" className="size-4" {...form.register("apply_to_past")} />
            {t("tx.applyToPast")}
          </label>
        ) : null}
        <Field id="tx-notes" label={t("tx.notes")} optional error={errors.notes?.message}>
          <Textarea maxLength={500} {...form.register("notes")} />
        </Field>
        {error ? <ErrorState error={error} /> : null}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onDone}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={saving}>
            {t("common.save")}
          </Button>
        </div>
      </form>
    </>
  );
}
