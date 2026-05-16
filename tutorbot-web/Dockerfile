# syntax=docker/dockerfile:1.7
#
# tutorbot-web frontend image.
#
# Build context expected at the tutorbot-web/ directory. Build args bake the
# browser-facing config into the Next.js standalone bundle (next.config.ts
# resolves these via /app/.env created below).
#
#   docker build \
#     --build-arg NEXT_PUBLIC_API_BASE=http://your-host:8001 \
#     --build-arg AUTH_ENABLED=true \
#     -t tutorbot-web:latest .

# ---------- Build stage ----------
FROM node:20-alpine AS builder

WORKDIR /app/tutorbot-web

# Install deps first to leverage layer caching.
COPY package.json package-lock.json* ./
RUN npm config set fetch-timeout 600000 \
 && npm ci --legacy-peer-deps

# Source.
COPY . .

# next.config.ts reads /app/.env (parent of the workdir). Write the build-time
# settings the browser will see at runtime.
ARG NEXT_PUBLIC_API_BASE=http://localhost:8001
ARG AUTH_ENABLED=false
RUN printf 'NEXT_PUBLIC_API_BASE_EXTERNAL=%s\nAUTH_ENABLED=%s\n' \
      "$NEXT_PUBLIC_API_BASE" "$AUTH_ENABLED" > /app/.env

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---------- Runtime stage ----------
FROM node:20-alpine AS runner

WORKDIR /app/tutorbot-web

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1

# Standalone output bundles server.js + the minimal node_modules subset.
COPY --from=builder /app/tutorbot-web/.next/standalone/. ./
COPY --from=builder /app/tutorbot-web/.next/static       ./.next/static
COPY --from=builder /app/tutorbot-web/public             ./public

EXPOSE 3000

CMD ["node", "server.js"]
