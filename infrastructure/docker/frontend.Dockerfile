# Next.js frontend (PRD 8). Runs the dev server, as in PRD 19.1: the API proxy target is read at
# runtime from BACKEND_INTERNAL_URL.
FROM node:22-slim
ENV NEXT_TELEMETRY_DISABLED=1 CI=true
RUN npm install -g pnpm@12.21.0
WORKDIR /app
COPY pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json frontend/
RUN pnpm install --frozen-lockfile
COPY frontend ./frontend
RUN chown -R node:node /app
USER node
WORKDIR /app/frontend
EXPOSE 3000
CMD ["pnpm", "exec", "next", "dev", "--hostname", "0.0.0.0", "--port", "3000"]
