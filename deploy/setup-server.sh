#!/usr/bin/env bash
#
# Quest Lab — first-time setup on a fresh Ubuntu server (Kamatera or anywhere).
# Run once, as root:
#
#   REPO_URL=https://github.com/YOU/questlab.git \
#   DOMAIN=learn.yourdomain.com \
#   HOUSEHOLD_PASSWORD='the house password' \
#   PARENT_PIN=4821 \
#   bash setup-server.sh
#
# Safe to re-run: it keeps the existing database password and secret key, and
# never touches the kids' progress.
#
set -euo pipefail

REPO_URL="${REPO_URL:?Set REPO_URL to your GitHub repo, e.g. https://github.com/you/questlab.git}"
DOMAIN="${DOMAIN:?Set DOMAIN to the hostname this will serve, e.g. learn.yourdomain.com}"
HOUSEHOLD_PASSWORD="${HOUSEHOLD_PASSWORD:?Set HOUSEHOLD_PASSWORD — the shared password the kids type once}"
PARENT_PIN="${PARENT_PIN:-1234}"

APP_USER=questlab
APP_HOME=/opt/questlab
APP_DIR="$APP_HOME/app"
VENV="$APP_HOME/venv"
ENV_FILE=/etc/questlab.env
DB_NAME=questlab
DB_USER=questlab

say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run this as root (sudo -i)."; exit 1; }

# Recover anything a previous run already set, so re-running is harmless.
OLD_DATABASE_URL=""; OLD_SECRET_KEY=""
if [ -f "$ENV_FILE" ]; then
    eval "$(grep -E '^[A-Z_]+=' "$ENV_FILE" | sed 's/^/OLD_/')"
fi

say "Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-dev build-essential \
    postgresql postgresql-contrib libpq-dev \
    nginx git curl ufw certbot python3-certbot-nginx

say "Creating the $APP_USER system user"
id -u "$APP_USER" >/dev/null 2>&1 \
    || useradd --system --create-home --home-dir "$APP_HOME" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_HOME"
chown "$APP_USER:$APP_USER" "$APP_HOME"

say "Setting up PostgreSQL"
systemctl enable --now postgresql
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
    echo "    role $DB_USER exists — reusing its password"
    rest="${OLD_DATABASE_URL#*://$DB_USER:}"
    DB_PASS="${rest%%@*}"
    if [ -z "$DB_PASS" ] || [ "$DB_PASS" = "$OLD_DATABASE_URL" ]; then
        echo "    couldn't recover the password from $ENV_FILE — setting a new one"
        DB_PASS="$(openssl rand -hex 20)"
        sudo -u postgres psql -qc "ALTER ROLE $DB_USER PASSWORD '$DB_PASS';"
    fi
else
    DB_PASS="$(openssl rand -hex 20)"
    sudo -u postgres psql -qc "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASS';"
fi
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
    || sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"

say "Fetching the code from $REPO_URL"
if [ -d "$APP_DIR/.git" ]; then
    sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
else
    sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi

say "Building the virtualenv"
[ -d "$VENV" ] || sudo -u "$APP_USER" python3 -m venv "$VENV"
sudo -u "$APP_USER" "$VENV/bin/pip" install --quiet --upgrade pip wheel
sudo -u "$APP_USER" "$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

say "Writing $ENV_FILE"
SECRET_KEY="${OLD_SECRET_KEY:-$(openssl rand -hex 32)}"
DATABASE_URL="postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME"
cat > "$ENV_FILE" <<EOF
# Quest Lab configuration. Owned by root, readable by the $APP_USER group only.
DATABASE_URL="$DATABASE_URL"
SECRET_KEY="$SECRET_KEY"
HOUSEHOLD_PASSWORD="$HOUSEHOLD_PASSWORD"
PARENT_PIN="$PARENT_PIN"
HTTPS_ONLY="false"
EOF
chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

say "Loading the lessons into the database"
sudo -u "$APP_USER" \
    DATABASE_URL="$DATABASE_URL" SECRET_KEY="$SECRET_KEY" \
    "$VENV/bin/python" "$APP_DIR/seed.py"

say "Installing the systemd service"
cp "$APP_DIR/deploy/questlab.service" /etc/systemd/system/questlab.service
systemctl daemon-reload
systemctl enable --now questlab
sleep 2
systemctl is-active --quiet questlab || { journalctl -u questlab -n 30 --no-pager; exit 1; }

say "Configuring nginx for $DOMAIN"
sed "s/YOUR_DOMAIN/$DOMAIN/g" "$APP_DIR/deploy/nginx-questlab.conf" > /etc/nginx/sites-available/questlab
ln -sf /etc/nginx/sites-available/questlab /etc/nginx/sites-enabled/questlab
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

say "Firewall"
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null
ufw status | sed 's/^/    /'

cat <<EOF

------------------------------------------------------------------
Quest Lab is up at  http://$DOMAIN

Next, once $DOMAIN resolves to this server's IP, turn on HTTPS:

    certbot --nginx -d $DOMAIN
    sed -i 's/^HTTPS_ONLY=.*/HTTPS_ONLY="true"/' $ENV_FILE
    systemctl restart questlab

Then:
    Parent dashboard   https://$DOMAIN/parent   (PIN $PARENT_PIN)
    Update the app     bash $APP_DIR/deploy/update.sh
    Nightly backups    bash $APP_DIR/deploy/install-backup.sh
    Logs               journalctl -u questlab -f
------------------------------------------------------------------
EOF
