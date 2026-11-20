import type { NextConfig } from "next";

// PRD 8.3: the browser calls same-origin /api/v1/*; Next proxies to the backend so the
// SameSite=Strict refresh cookie keeps working and no CORS is needed.
const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  reactStrictMode: true,
  // `next dev` otherwise writes an AGENTS.md into the app folder.
  agentRules: false,
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` }];
  },
};

export default config;
