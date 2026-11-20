import { notifyAuthLost, getToken, setToken } from "@/auth/token";
import { t } from "@/lib/i18n";
import { ApiError, type FieldError } from "./errors";

const BASE = "/api/v1";

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

function withQuery(path: string, query?: Query): string {
  if (!query) return `${BASE}${path}`;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, String(v)));
    else params.set(key, String(value));
  }
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function toError(response: Response): Promise<ApiError> {
  let body: {
    code?: string;
    detail?: string;
    title?: string;
    request_id?: string;
    errors?: FieldError[];
  } = {};
  try {
    body = await response.json();
  } catch {
    // Not JSON: a proxy error page (backend down gives 500/502/503/504 text from Next).
    if (response.status >= 500)
      return new ApiError(response.status, "BACKEND_UNREACHABLE", t("errors.network"));
  }
  return new ApiError(
    response.status,
    body.code ?? "HTTP_ERROR",
    body.detail ?? body.title ?? t("errors.generic"),
    body.request_id ?? response.headers.get("x-request-id"),
    body.errors ?? [],
  );
}

let refreshing: Promise<boolean> | null = null;

/** One refresh at a time; every waiting request retries with the new token (PRD 8.3). */
export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const response = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        credentials: "same-origin",
      });
      if (!response.ok) return false;
      const body = (await response.json()) as { access_token: string };
      setToken(body.access_token);
      return true;
    } catch {
      return false;
    } finally {
      queueMicrotask(() => {
        refreshing = null;
      });
    }
  })();
  return refreshing;
}

export interface RequestOptions {
  method?: string;
  query?: Query;
  json?: unknown;
  form?: FormData;
  headers?: Record<string, string>;
  /** Auth endpoints must not trigger the refresh-and-retry flow. */
  anonymous?: boolean;
  signal?: AbortSignal;
  raw?: boolean;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  const token = getToken();
  if (token && !options.anonymous) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (options.form) body = options.form;
  else if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  try {
    return await fetch(withQuery(path, options.query), {
      method: options.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      credentials: "same-origin",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "NETWORK_ERROR", t("errors.network"));
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await send(path, options);
  if (response.status === 401 && !options.anonymous) {
    if (await refreshSession()) response = await send(path, options);
    if (response.status === 401) {
      notifyAuthLost();
      throw new ApiError(401, "UNAUTHENTICATED", t("errors.session"));
    }
  }
  if (!response.ok) throw await toError(response);
  if (response.status === 204) return undefined as T;
  if (options.raw) return (await response.text()) as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) =>
    request<T>(path, { query, signal }),
  post: <T>(path: string, json?: unknown, options: RequestOptions = {}) =>
    request<T>(path, { ...options, method: "POST", json }),
  patch: <T>(path: string, json: unknown, options: RequestOptions = {}) =>
    request<T>(path, { ...options, method: "PATCH", json }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
