# syntax=docker/dockerfile:1.7
# Build from the repository root: docker build -f web/Dockerfile --build-arg SAHIFA_COMMIT=$(git rev-parse HEAD) .
# Stay on the LTS line: Node 25+ no longer ships Corepack, which provides the pinned pnpm.
FROM node:22-bookworm-slim AS build
RUN corepack enable
WORKDIR /app
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web ./
RUN pnpm build

# Caddy serves the static SPA (fonts included, nothing loaded from third parties) with security
# headers and proxies /api and /healthz to the API container.
FROM caddy:2-alpine AS web
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
# /version.json names the commit this image was built from; the release workflow reads it to
# confirm a deploy went live. After the SPA build so a new commit keeps the build cached.
ARG SAHIFA_COMMIT=unknown
RUN printf '{"commit":"%s"}\n' "$SAHIFA_COMMIT" > /srv/version.json
# Caddy runs as the unprivileged user sahifa (uid 10001, as in the api image; spec 019). The
# file capability lets it bind 80 and 443 without root; the base image sets it too, it is set
# again here so the image does not depend on that. It may write only its certificates (/data)
# and autosaved config (/config); /srv and the Caddyfile stay root's.
RUN addgroup -S -g 10001 sahifa \
 && adduser -S -D -H -u 10001 -G sahifa -s /sbin/nologin sahifa \
 && setcap cap_net_bind_service=+ep /usr/bin/caddy \
 && mkdir -p /data/caddy /config/caddy \
 && chown -R 10001:10001 /data /config
USER 10001:10001
EXPOSE 80 443
