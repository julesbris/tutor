# Deploying Quest Lab — GitHub + a Kamatera server

Code lives on GitHub, the Kamatera box pulls it and runs it under systemd behind
nginx, with Postgres on the same machine. Roughly 20 minutes end to end.

Your setup:

- Repo: **https://github.com/julesbris/tutor**
- Server: **79.108.224.58**
- Domain: `learn.yourdomain.com` below is a placeholder — put your real one in.

---

## 1. The code is already on GitHub

It's pushed to `main` at <https://github.com/julesbris/tutor>. Nothing secret is in it:
passwords and the database URL only ever live in `/etc/questlab.env` on the server.

To work on it from your own machine:

```bash
git clone https://github.com/julesbris/tutor.git
cd tutor
```

If the repo is **private**, the server needs a deploy key to clone it — step 3b below.
If it's public, skip 3b.

---

## 2. Point the domain at the server

In your DNS provider, add an **A record**:

| Type | Name | Value |
|---|---|---|
| A | `learn` (or `@` for the bare domain) | `79.108.224.58` |

Check it has propagated before doing the HTTPS step:

```bash
dig +short learn.yourdomain.com
```

You want your server's IP back. It's usually a couple of minutes; occasionally longer.

---

## 3. Set the server up

SSH in as root (or a sudo user — then prefix things with `sudo`):

```bash
ssh root@79.108.224.58
```

### 3a. A quick sanity check on the box

```bash
lsb_release -d          # Ubuntu 22.04 or 24.04 is what the script expects
free -m                 # 1 GB RAM is enough; 2 GB is comfortable
df -h /                 # the app + database + backups is well under 2 GB
```

The setup script installs Postgres and nginx. If this server is already running
something else on port 80, sort that out first.

### 3b. Only if your repo is private — give the server a deploy key

```bash
ssh-keygen -t ed25519 -C "questlab-server" -f /root/.ssh/questlab_deploy -N ""
cat /root/.ssh/questlab_deploy.pub
```

Copy that public key into GitHub: your repo → **Settings → Deploy keys → Add deploy key**.
Paste it, leave "Allow write access" **unticked**, save.

Then tell SSH to use it for GitHub:

```bash
cat >> /root/.ssh/config <<'EOF'
Host github.com
    IdentityFile /root/.ssh/questlab_deploy
    IdentitiesOnly yes
EOF
chmod 600 /root/.ssh/config
ssh -T git@github.com     # should say: Hi julesbris/tutor! You've successfully authenticated
```

The clone URL is then `git@github.com:julesbris/tutor.git` (SSH form), not the `https://` one.

### 3c. Run the setup script

```bash
curl -fsSL https://raw.githubusercontent.com/julesbris/tutor/main/deploy/setup-server.sh -o setup-server.sh

REPO_URL=https://github.com/julesbris/tutor.git \
DOMAIN=learn.yourdomain.com \
HOUSEHOLD_PASSWORD='pick something the kids can remember' \
PARENT_PIN=4821 \
bash setup-server.sh
```

For a **private** repo, use the SSH clone URL instead:
`REPO_URL=git@github.com:julesbris/tutor.git`
(and download the script from your local copy with `scp` rather than `curl`, since
raw.githubusercontent.com won't serve a private file).

The script installs everything, creates a `questlab` system user and database with a
generated password, loads all 96 lessons and boss challenges, starts the service, and
configures nginx. It's safe to re-run — it keeps the existing database password and secret key.

When it finishes, `http://learn.yourdomain.com` should show the house password screen.

**No domain yet?** Set `DOMAIN=79.108.224.58` instead and it will serve on the bare IP over
plain HTTP. Skip 3d until you have a name pointed at the box — Let's Encrypt won't issue a
certificate for an IP address. When you do, re-run `setup-server.sh` with the real `DOMAIN`.

### 3d. Turn on HTTPS

```bash
certbot --nginx -d learn.yourdomain.com
sed -i 's/^HTTPS_ONLY=.*/HTTPS_ONLY="true"/' /etc/questlab.env
systemctl restart questlab
```

Certbot rewrites the nginx config to add the certificate and redirect port 80 to 443,
and installs its own renewal timer. `HTTPS_ONLY=true` tells Flask to only send the
session cookie over HTTPS.

### 3e. Nightly backups

```bash
bash /opt/questlab/app/deploy/install-backup.sh
```

Dumps the database to `/var/backups/questlab` at 2:30am, keeps 30 days.

---

## 4. First run

1. Open `https://learn.yourdomain.com`, type the house password.
2. Go to `/parent`, enter your PIN, rename **Kid One** and **Kid Two** and set their year levels.
3. Hand it to the kids.

The house password is remembered for 180 days per device, so they type it once on the
family laptop or tablet and not again.

---

## 5. Changing things later

Edit content or code on your computer, commit, push:

```bash
python validate_content.py    # catch mistakes before they leave your laptop
git add . && git commit -m "Add three fractions lessons" && git push
```

Then on the server:

```bash
sudo bash /opt/questlab/app/deploy/update.sh
```

That pulls, installs any new dependencies, validates the content, **backs the database up
first**, reloads the lessons, restarts, and checks the health endpoint — rolling back to
the previous commit automatically if the app doesn't come back up.

Because lessons are matched on their `slug`, editing a lesson updates it in place. Scores,
streaks, badges and profiles are never touched by an update.

### Want it to deploy itself on every push?

`.github/workflows/deploy.yml` does exactly that, once the tests pass. Set it up:

```bash
# on your own computer
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/questlab_ci -N ""
ssh-copy-id -i ~/.ssh/questlab_ci.pub root@79.108.224.58
cat ~/.ssh/questlab_ci        # the private key — copy the whole thing
```

In the repo: **Settings → Secrets and variables → Actions → New repository secret**, add

| Secret | Value |
|---|---|
| `SSH_HOST` | `79.108.224.58` |
| `SSH_USER` | `root` |
| `SSH_PRIVATE_KEY` | the whole private key, `-----BEGIN` line to `-----END` line |

If you'd rather deploy by hand, delete `.github/workflows/deploy.yml`. The test workflow
(`ci.yml`) is worth keeping either way — it spins up Postgres, loads the content and runs
the full smoke test on every push, so a broken lesson file gets caught before it reaches
the server.

---

## 6. Day to day

```bash
systemctl status questlab            # is it running
journalctl -u questlab -f            # live logs
systemctl restart questlab           # restart
nano /etc/questlab.env               # change the house password or parent PIN
systemctl restart questlab           #   (then restart to pick it up)
```

Look at the database directly:

```bash
sudo -u postgres psql questlab
\dt                                          -- tables
select name, year_level from kids;
select count(*) from lessons;
\q
```

Restore a backup:

```bash
sudo -u postgres dropdb questlab && sudo -u postgres createdb -O questlab questlab
gunzip -c /var/backups/questlab/questlab-20260901.sql.gz | sudo -u postgres psql questlab
systemctl restart questlab
```

---

## 7. When something's wrong

**"502 Bad Gateway"** — nginx is up but the app isn't.
`journalctl -u questlab -n 50` will say why. Usually a database connection problem or a
typo in `/etc/questlab.env`.

**The site loads but everything is unstyled** — nginx can't read `/opt/questlab/app/static/`.
Check `ls -la /opt/questlab/app/static/` and that the path in
`/etc/nginx/sites-available/questlab` matches.

**"No lessons here yet"** — the seed didn't run.
```bash
sudo -u questlab bash -c 'set -a; . /etc/questlab.env; set +a; /opt/questlab/venv/bin/python /opt/questlab/app/seed.py'
```

**Certbot fails** — the domain isn't resolving to this server yet (`dig +short learn.yourdomain.com`),
or port 80 is blocked (`ufw status` should show Nginx Full allowed).

**Locked out of the parent dashboard** — the PIN is in plain text in `/etc/questlab.env`.

**Forgot the house password** — same file. Change it, `systemctl restart questlab`.
Existing devices stay logged in; only new ones will need the new password.

---

## 8. What this costs to run

A 1 GB / 1 vCPU Kamatera instance is plenty — two kids doing quizzes is close to no load
at all, and the whole content library is under a megabyte. The database will take years to
reach a hundred megabytes at eight questions a night.

The only things that need looking after: Let's Encrypt renews itself (certbot's timer),
backups prune themselves at 30 days, and Ubuntu security updates are worth turning on:

```bash
apt-get install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```
