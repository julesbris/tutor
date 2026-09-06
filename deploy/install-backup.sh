#!/usr/bin/env bash
#
# Nightly database backups, kept for 30 days. Run once, as root:
#
#   bash /opt/questlab/app/deploy/install-backup.sh
#
# Restore one with:
#   gunzip -c /var/backups/questlab/questlab-YYYYMMDD.sql.gz | sudo -u postgres psql questlab
#
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run this as root (sudo -i)."; exit 1; }

mkdir -p /var/backups/questlab
chmod 750 /var/backups/questlab

cat > /usr/local/bin/questlab-backup <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
dest=/var/backups/questlab
sudo -u postgres pg_dump questlab | gzip > "$dest/questlab-$(date +%Y%m%d).sql.gz"
find "$dest" -name '*.sql.gz' -mtime +30 -delete
EOF
chmod 750 /usr/local/bin/questlab-backup

cat > /etc/systemd/system/questlab-backup.service <<'EOF'
[Unit]
Description=Quest Lab database backup

[Service]
Type=oneshot
ExecStart=/usr/local/bin/questlab-backup
EOF

cat > /etc/systemd/system/questlab-backup.timer <<'EOF'
[Unit]
Description=Nightly Quest Lab database backup

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now questlab-backup.timer
/usr/local/bin/questlab-backup

echo
echo "Nightly backup installed. Runs at 02:30, keeps 30 days."
ls -lh /var/backups/questlab | sed 's/^/    /'
