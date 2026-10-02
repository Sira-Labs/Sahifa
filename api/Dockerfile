# syntax=docker/dockerfile:1.7
# Sahifa API image. Build from the repository root: docker build -f api/Dockerfile .
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app
COPY core/pyproject.toml core/README.md ./core/
COPY core/src ./core/src
COPY api/pyproject.toml api/uv.lock ./api/
COPY api/src ./api/src
COPY --chmod=755 api/docker-entrypoint.sh /usr/local/bin/sahifa-api
# Runtime deps from the lock (without the path dependency), then the core and the API
# themselves without re-resolving: their deps are already installed.
RUN cd api && uv export --no-dev --no-emit-project --no-emit-package sahifa-core --frozen -o /tmp/req.txt \
 && uv pip install --no-cache -r /tmp/req.txt \
 && uv pip install --no-cache --no-deps ../core . \
 && rm -rf /app/core /app/api/src
RUN useradd --system --uid 10001 --create-home sahifa \
 && mkdir -p /data/uploads && chown -R sahifa /data
USER sahifa
ENV SAHIFA_ENV=prod SAHIFA_DATA_DIR=/data
# The commit this image was built from, reported by /api/version; declared last so a new
# commit does not invalidate the cached layers above.
ARG SAHIFA_COMMIT=unknown
ENV SAHIFA_COMMIT=${SAHIFA_COMMIT}
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["sahifa-api", "healthcheck"]
CMD ["sahifa-api"]
