#!/usr/bin/env bash
#
# Pull the latest code from GitHub and restart. Run as root:
#
#   bash /opt/questlab/app/deploy/update.sh
#
# Lessons are matched on their slug, so edited content is updated in place and
# the kids' profiles, scores, streaks and badges are left alone.
#
set -euo pipefail

APP_USER=questlab
APP_DIR=/opt/questlab/app
VENV=/opt/questlab/venv
ENV_FILE=/etc/questlab.env

say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Run this as root (sudo -i)."; exit 1; }

eval "$(grep -E '^[A-Z_]+=' "$ENV_FILE")"
export DATABASE_URL SECRET_KEY

say "Pulling from GitHub"
before="$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)"
sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
after="$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)"
echo "    $before -> $after"

say "Updating dependencies"
sudo -u "$APP_USER" "$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

say "Checking the content files"
sudo -u "$APP_USER" "$VENV/bin/python" "$APP_DIR/validate_content.py"

say "Backing up the database first"
mkdir -p /var/backups/questlab
stamp="$(date +%Y%m%d-%H%M%S)"
sudo -u postgres pg_dump questlab | gzip > "/var/backups/questlab/pre-update-$stamp.sql.gz"
echo "    /var/backups/questlab/pre-update-$stamp.sql.gz"

say "Loading content changes"
sudo -u "$APP_USER" DATABASE_URL="$DATABASE_URL" SECRET_KEY="$SECRET_KEY" \
    "$VENV/bin/python" "$APP_DIR/seed.py"

say "Restarting"
systemctl restart questlab
sleep 2
if systemctl is-active --quiet questlab && curl -fsS http://127.0.0.1:8000/healthz >/dev/null; then
    echo "    healthy"
else
    echo "    NOT healthy — rolling back to $before"
    sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard "$before"
    systemctl restart questlab
    journalctl -u questlab -n 30 --no-pager
    exit 1
fi

say "Done"
