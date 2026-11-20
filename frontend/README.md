# frontend

Next.js (App Router) + TypeScript strict + Tailwind v4. PRD section 8.

```bash
make setup                 # installs uv and pnpm dependencies
make api                   # backend on :8000 (needs DATABASE_URL, JWT_SECRET; COOKIE_SECURE=false on plain http)
make web                   # frontend on :3000, proxies /api/v1/* to BACKEND_INTERNAL_URL
pnpm --dir frontend test   # Vitest + Testing Library
make openapi               # regenerate services/backend/openapi.json and src/api/schema.d.ts
```

- The browser only calls same-origin `/api/v1/*`; `next.config.ts` rewrites it to the backend, so the
  refresh cookie is first-party and no CORS is needed.
- The access token lives in memory (`src/auth/token.ts`). On a page load the refresh cookie restores
  the session; a 401 triggers one shared refresh and a retry, then a redirect to `/login`.
- Types come from the backend OpenAPI (`src/api/schema.d.ts`, generated, do not edit). `make openapi-check`
  fails when it is stale.
- UI strings are in `src/messages/en.json` (`t("tx.add")`). Money is a string end to end
  (`src/lib/money.ts`).
- `LIVE_API_URL=http://127.0.0.1:8000 pnpm --dir frontend test src/api/live.test.ts` runs the real client
  against a running backend (skipped otherwise).
