#!/usr/bin/env bash
# Atualiza o app no servidor e volta à versão anterior se ele não subir.
# Uso (na VM): sudo bash /srv/tcghub/app/deploy/deploy.sh [ref]   ex.: origin/main, v1.2.0
set -euo pipefail

REF="${1:-origin/main}"
APP=/srv/tcghub/app
VENV=/srv/tcghub/venv
ENV_FILE=/etc/tcghub/tcghub.env
as_app() { sudo -u tcghub -H "$@"; }

HOST=$(grep '^APP_HOSTS=' "$ENV_FILE" | cut -d= -f2 | cut -d, -f1)
PREVIOUS=$(as_app git -C "$APP" rev-parse HEAD)

healthy() {
    for _ in $(seq 1 20); do
        if curl -fsS -H "Host: $HOST" http://127.0.0.1:8000/healthz >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    return 1
}

install() {
    as_app git -C "$APP" checkout --quiet --detach "$1"
    as_app "$VENV/bin/pip" install --quiet -r "$APP/requirements.txt"
    systemctl restart tcghub
}

echo "Versão atual: $PREVIOUS"
as_app git -C "$APP" fetch --quiet --prune --tags origin
install "$REF"
if healthy; then
    echo "OK: $(as_app git -C "$APP" log -1 --format='%h %s') no ar."
else
    echo "O app não respondeu em /healthz. Voltando para $PREVIOUS." >&2
    journalctl -u tcghub -n 30 --no-pager >&2 || true
    install "$PREVIOUS"
    healthy && echo "Versão anterior restaurada." >&2 || echo "A versão anterior também não subiu: veja journalctl -u tcghub." >&2
    exit 1
fi