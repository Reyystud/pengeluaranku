"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "@/api/errors";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { ErrorState } from "@/components/ui/states";
import { t } from "@/lib/i18n";

const loginSchema = z.object({
  email: z.string().trim().email(t("auth.invalidEmail")),
  password: z.string().min(1, t("common.required")),
});
const registerSchema = z.object({
  display_name: z.string().trim().min(1, t("auth.nameRequired")).max(60),
  email: z.string().trim().email(t("auth.invalidEmail")),
  password: z.string().min(10, t("auth.passwordShort")).max(128),
});

type LoginValues = z.infer<typeof loginSchema>;
type RegisterValues = z.infer<typeof registerSchema>;

function Shell({
  title,
  children,
  footer,
}: {
  title: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-6 px-4 py-12">
      <h1 className="text-2xl font-bold">{title}</h1>
      {children}
      <p className="text-sm text-muted-foreground">{footer}</p>
    </main>
  );
}

function useRedirectWhenSignedIn() {
  const { status } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (status === "authenticated") router.replace("/transactions");
  }, [status, router]);
}

export function LoginForm() {
  const { login } = useAuth();
  const [error, setError] = useState<unknown>(null);
  useRedirectWhenSignedIn();
  const form = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });
  const { errors, isSubmitting } = form.formState;

  return (
    <Shell
      title={t("auth.loginTitle")}
      footer={
        <>
          {t("auth.noAccount")}{" "}
          <Link href="/register" className="font-medium text-primary underline">
            {t("auth.submitRegister")}
          </Link>
        </>
      }
    >
      <form
        noValidate
        className="space-y-4"
        onSubmit={form.handleSubmit(async (values) => {
          setError(null);
          try {
            await login(values.email, values.password);
          } catch (e) {
            setError(e);
          }
        })}
      >
        <Field id="email" label={t("auth.email")} error={errors.email?.message}>
          <Input type="email" autoComplete="email" {...form.register("email")} />
        </Field>
        <Field id="password" label={t("auth.password")} error={errors.password?.message}>
          <Input type="password" autoComplete="current-password" {...form.register("password")} />
        </Field>
        {error ? <ErrorState error={error} /> : null}
        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {t("auth.submitLogin")}
        </Button>
      </form>
    </Shell>
  );
}

export function RegisterForm() {
  const { register: signUp } = useAuth();
  const [error, setError] = useState<unknown>(null);
  useRedirectWhenSignedIn();
  const form = useForm<RegisterValues>({ resolver: zodResolver(registerSchema) });
  const { errors, isSubmitting } = form.formState;

  return (
    <Shell
      title={t("auth.registerTitle")}
      footer={
        <>
          {t("auth.haveAccount")}{" "}
          <Link href="/login" className="font-medium text-primary underline">
            {t("auth.submitLogin")}
          </Link>
        </>
      }
    >
      <form
        noValidate
        className="space-y-4"
        onSubmit={form.handleSubmit(async (values) => {
          setError(null);
          try {
            await signUp(values.email, values.password, values.display_name);
          } catch (e) {
            // Server-side field errors (e.g. a common password) go next to the field.
            if (e instanceof ApiError && e.errors.length) {
              let placed = false;
              for (const fe of e.errors) {
                if (fe.field in values) {
                  form.setError(fe.field as keyof RegisterValues, { message: fe.message });
                  placed = true;
                }
              }
              if (placed) return;
            }
            setError(e);
          }
        })}
      >
        <Field id="display_name" label={t("auth.displayName")} error={errors.display_name?.message}>
          <Input autoComplete="name" {...form.register("display_name")} />
        </Field>
        <Field id="email" label={t("auth.email")} error={errors.email?.message}>
          <Input type="email" autoComplete="email" {...form.register("email")} />
        </Field>
        <Field
          id="password"
          label={t("auth.password")}
          hint={t("auth.passwordHint")}
          error={errors.password?.message}
        >
          <Input type="password" autoComplete="new-password" {...form.register("password")} />
        </Field>
        {error ? <ErrorState error={error} /> : null}
        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {t("auth.submitRegister")}
        </Button>
      </form>
    </Shell>
  );
}
