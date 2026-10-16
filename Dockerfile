FROM node:22-bookworm-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN python3 -c "import sys; assert sys.version_info[:2] == (3, 11), sys.version" \
    && node -e "const [major, minor] = process.versions.node.split('.').map(Number); if (major < 22 || (major === 22 && minor < 12)) process.exit(1)"

COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --requirement requirements.txt \
    && /opt/venv/bin/pip check

# The root postinstall builds the UI. Disable every lifecycle script here so
# this layer contains only the two locked Steam runtime packages.
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev \
    && node -e "require('steam-user'); require('steam-session')"

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm --prefix frontend ci
COPY frontend ./frontend
RUN npm --prefix frontend run build \
    && test -f frontend/dist/index.html


FROM node:22-bookworm-slim AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" manhattancafe \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" \
        --home-dir /state --no-create-home --shell /usr/sbin/nologin manhattancafe \
    && install -d -o "${APP_UID}" -g "${APP_GID}" -m 0700 /state

ENV PATH="/opt/venv/bin:${PATH}" \
    HOME=/state \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    UMA_RUNTIME_DIR=/state \
    UMA_API_TOKEN_FILE=/run/secrets/uma_api_token \
    UMA_SECRET_PASSPHRASE_FILE=/run/secrets/uma_secret_passphrase \
    SWEEPY_HOST=0.0.0.0 \
    SWEEPY_PORT=1616

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY --from=build /build/node_modules ./node_modules
COPY . .
COPY --from=build /build/frontend/dist ./frontend/dist

# Runtime code and dependencies are root-owned and immutable even when the
# container is run as another non-root uid for a host-owned bind mount.
RUN chown -R root:root /app /opt/venv \
    && chmod -R a-w /app /opt/venv

EXPOSE 1616
VOLUME ["/state"]
USER ${APP_UID}:${APP_GID}
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "main.py"]
