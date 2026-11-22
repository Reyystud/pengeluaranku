"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { MerchantRule } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { setToken } from "@/auth/token";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { formatDay } from "@/lib/format";
import { t } from "@/lib/i18n";
import {
  useChangePassword,
  useDeleteAccount,
  useMerchantRules,
  useProfileUpdate,
  useRuleCategories,
  useRuleDelete,
  useRuleUpdate,
} from "./hooks";

const card = "space-y-3 rounded-lg border border-border bg-card p-4";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : t("errors.generic");
}

function ProfileSection() {
  const { user } = useAuth();
  const update = useProfileUpdate();
  const [name, setName] = useState(user?.display_name ?? "");
  const [zone, setZone] = useState(user?.timezone ?? "Asia/Jakarta");
  const [day, setDay] = useState(String(user?.budget_period_start_day ?? 1));
  const [saved, setSaved] = useState(false);
  if (!user) return null;
  const consent = user.training_consent;
  return (
    <section className={card} aria-labelledby="set-profile">
      <h2 id="set-profile" className="text-lg font-semibold">
        {t("settings.profile")}
      </h2>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          setSaved(false);
          update.mutate(
            { display_name: name, timezone: zone, budget_period_start_day: Number(day) },
            { onSuccess: () => setSaved(true) },
          );
        }}
      >
        <Field id="set-name" label={t("settings.displayName")}>
          <Input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <Field id="set-tz" label={t("settings.timezone")} hint={t("settings.timezoneHint")}>
          <Input value={zone} onChange={(e) => setZone(e.target.value)} required />
        </Field>
        <Field id="set-day" label={t("settings.startDay")} hint={t("settings.startDayHint")}>
          <Input
            type="number"
            min={1}
            max={28}
            value={day}
            onChange={(e) => setDay(e.target.value)}
            required
          />
        </Field>
        {user.pending_period_start_day && user.pending_period_start_effective ? (
          <p className="text-sm text-muted-foreground">
            {t("settings.pendingStartDay", {
              day: user.pending_period_start_day,
              date: formatDay(user.pending_period_start_effective),
            })}
          </p>
        ) : null}
        {update.isError ? (
          <p role="alert" className="text-sm text-danger">
            {errorText(update.error)}
          </p>
        ) : null}
        {saved ? (
          <p role="status" className="text-sm text-success">
            {t("settings.saved")}
          </p>
        ) : null}
        <Button type="submit" disabled={update.isPending}>
          {t("common.save")}
        </Button>
      </form>
      <div className="border-t border-border pt-3">
        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            className="mt-1 size-4"
            checked={consent}
            disabled={update.isPending}
            onChange={(e) => update.mutate({ training_consent: e.target.checked })}
          />
          <span>
            <span className="block font-medium">{t("settings.consent")}</span>
            <span className="block text-muted-foreground">{t("settings.consentHint")}</span>
          </span>
        </label>
      </div>
    </section>
  );
}

function RuleRow({ rule }: { rule: MerchantRule }) {
  const categories = useRuleCategories();
  const update = useRuleUpdate();
  const remove = useRuleDelete();
  const options = (categories.data ?? []).filter((c) => c.transaction_type !== "income");
  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <div className="min-w-40 flex-1">
        <p className="font-medium">{rule.merchant_display}</p>
        <p className="text-xs text-muted-foreground">
          {rule.times_applied === 0
            ? t("settings.ruleNever")
            : `${t("settings.ruleApplied", { count: rule.times_applied })}${
                rule.last_applied_at
                  ? `, ${t("settings.ruleLastApplied", { date: formatDay(rule.last_applied_at.slice(0, 10)) })}`
                  : ""
              }`}
        </p>
      </div>
      <Select
        aria-label={t("settings.ruleChange", { merchant: rule.merchant_display })}
        className="w-48"
        value={rule.category.slug}
        disabled={update.isPending}
        onChange={(e) => update.mutate({ id: rule.id, category: e.target.value })}
      >
        {options.map((c) => (
          <option key={c.id} value={c.slug}>
            {c.name}
          </option>
        ))}
        {options.some((c) => c.slug === rule.category.slug) ? null : (
          <option value={rule.category.slug}>{rule.category.name}</option>
        )}
      </Select>
      <Button
        variant="secondary"
        aria-label={t("settings.ruleDelete", { merchant: rule.merchant_display })}
        disabled={remove.isPending}
        onClick={() => remove.mutate(rule.id)}
      >
        {t("common.delete")}
      </Button>
    </li>
  );
}

function RulesSection() {
  const query = useMerchantRules();
  return (
    <section className={card} aria-labelledby="set-rules">
      <h2 id="set-rules" className="text-lg font-semibold">
        {t("settings.rules")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("settings.rulesIntro")}</p>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.isPending ? (
        <SkeletonRows rows={2} />
      ) : query.data.items.length === 0 ? (
        <EmptyState message={t("settings.rulesEmpty")} />
      ) : (
        <ul className="divide-y divide-border">
          {query.data.items.map((r) => (
            <RuleRow key={r.id} rule={r} />
          ))}
        </ul>
      )}
    </section>
  );
}

function PasswordSection() {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [done, setDone] = useState(false);
  return (
    <section className={card} aria-labelledby="set-pw">
      <h2 id="set-pw" className="text-lg font-semibold">
        {t("settings.password")}
      </h2>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          setDone(false);
          change.mutate(
            { current_password: current, new_password: next },
            {
              onSuccess: () => {
                setDone(true);
                setCurrent("");
                setNext("");
              },
            },
          );
        }}
      >
        <Field id="set-cur" label={t("settings.currentPassword")}>
          <Input
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </Field>
        <Field id="set-new" label={t("settings.newPassword")} hint={t("settings.passwordHint")}>
          <Input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
        </Field>
        {change.isError ? (
          <p role="alert" className="text-sm text-danger">
            {errorText(change.error)}
          </p>
        ) : null}
        {done ? (
          <p role="status" className="text-sm text-success">
            {t("settings.passwordChanged")}
          </p>
        ) : null}
        <Button type="submit" disabled={change.isPending}>
          {t("settings.password")}
        </Button>
      </form>
    </section>
  );
}

function DeleteSection() {
  const remove = useDeleteAccount();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  return (
    <section className={`${card} border-danger/40`} aria-labelledby="set-del">
      <h2 id="set-del" className="text-lg font-semibold text-danger">
        {t("settings.danger")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("settings.dangerIntro")}</p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          remove.mutate(
            { password, confirm },
            {
              onSuccess: () => {
                setToken(null);
                queryClient.clear();
                router.replace("/login");
              },
            },
          );
        }}
      >
        <Field id="del-pw" label={t("settings.dangerPassword")}>
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>
        <Field id="del-confirm" label={t("settings.dangerConfirm")}>
          <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </Field>
        {remove.isError ? (
          <p role="alert" className="text-sm text-danger">
            {errorText(remove.error)}
          </p>
        ) : null}
        <Button type="submit" variant="danger" disabled={remove.isPending || confirm !== "DELETE"}>
          {t("settings.dangerButton")}
        </Button>
      </form>
    </section>
  );
}

export function SettingsView() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">{t("settings.title")}</h1>
      <ProfileSection />
      <RulesSection />
      <PasswordSection />
      <p className="text-sm text-muted-foreground">{t("settings.exportNote")}</p>
      <DeleteSection />
    </div>
  );
}
