#!/usr/bin/env bash
# Install as root-owned /usr/local/sbin/hexa-deploy. Do not sudo-execute writable checkout files.
set -Eeuo pipefail
# Git checkout, merge and rollback create tracked files. The app runs as
# hexa-studio, not root, so these files must be readable and dirs traversable.
# Keep sensitive backups private through their root-only directory and file modes.
umask 022
APP=/var/www/hexa-storyengine
DB=/var/lib/hexa-storyengine/web/jobs.sqlite3
MAINTENANCE=/var/lib/hexa-storyengine/web/.deploy-maintenance
SERVICE=hexa-storyengine.service
BACKUPS=/root/hexa-backups

fail() { echo "DEPLOY_BLOCKED: $*" >&2; exit 1; }
[[ $(id -u) -eq 0 ]] || fail 'Restricted root sudo required'
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || fail 'Expected full 40-character SHA'
TARGET="$1"
exec 9>/run/lock/hexa-storyengine-deploy.lock
flock -n 9 || fail 'Another deployment is in progress'

cd "$APP"
[[ $(git branch --show-current) == bayer ]] || fail 'Server not on bayer'
[[ -z $(git status --porcelain) ]] || fail 'Server worktree is dirty'
[[ $(systemctl is-active "$SERVICE") == active ]] || fail 'HEXA service is not active'

idle() {
  curl -fsS --max-time 10 http://127.0.0.1:8787/ready |
    python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("ready") is True and d.get("active_job") is None, d' || return 1
  python3 - "$DB" <<'PY' || return 1
import sqlite3, sys, time
from pathlib import Path
p = Path(sys.argv[1])
if not p.is_file(): raise SystemExit('Jobs database missing')
with sqlite3.connect(f'file:{p}?mode=ro', uri=True, timeout=20) as db:
    has = db.execute("SELECT 1 FROM sqlite_master WHERE name='uploads' AND type='table'").fetchone()
    if has:
        n = db.execute("SELECT COUNT(*) FROM uploads WHERE state='validating' OR (state='uploading' AND updated >= ?)", (time.time()-3600,)).fetchone()[0]
        if n: raise SystemExit(f'DEPLOY_BLOCKED: {n} active/recent uploads')
PY
}

idle || fail 'Render or upload active, or service not ready'
git fetch --quiet origin bayer
[[ $(git rev-parse origin/bayer) == "$TARGET" ]] || fail 'Target is not latest origin/bayer'
OLD="$(git rev-parse HEAD)"
if [[ "$OLD" == "$TARGET" ]]; then
  echo "DEPLOY_NOOP: $TARGET already live"
  exit 0
fi
git merge-base --is-ancestor "$OLD" "$TARGET" || fail 'Non-fast-forward update refused'

BACKUP="$BACKUPS/ci-$(date -u +%Y%m%dT%H%M%SZ)-${OLD:0:8}"
install -d -m 700 "$BACKUP"
printf '%s\n' "$OLD" > "$BACKUP/previous-sha.txt"
cp -p /etc/systemd/system/hexa-storyengine.service "$BACKUP/service.unit"
cp -p /etc/hexa-storyengine/hexa.env "$BACKUP/hexa.env"
chmod 600 "$BACKUP/hexa.env"
python3 - "$DB" "$BACKUP/jobs.sqlite3" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as src:
    with sqlite3.connect(sys.argv[2]) as dst: src.backup(dst)
with sqlite3.connect(sys.argv[2]) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
print('SQLITE_BACKUP_OK')
PY
chmod 600 "$BACKUP/jobs.sqlite3"

# New requests get 503 with Retry-After; status and existing downloads stay accessible.
touch "$MAINTENANCE"
trap 'rm -f "$MAINTENANCE"' EXIT
sleep 5
idle || fail 'Activity during drain; no service was stopped'

STOPPED=0
rollback() {
  code=$1
  trap - ERR INT TERM
  if [[ $STOPPED -eq 1 ]]; then
    echo "DEPLOY_FAILED: rolling back $OLD" >&2
    systemctl stop "$SERVICE" || true
    git reset --hard "$OLD" || true
    systemctl start "$SERVICE" || true
    echo "ROLLBACK: $(git rev-parse HEAD); backup: $BACKUP" >&2
    # DB backup retained; never restore blindly over potentially newer job data.
  fi
  exit "$code"
}
trap 'rollback "$?"' ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM

echo "DEPLOY_START: $OLD -> $TARGET"
STOPPED=1
systemctl stop "$SERVICE"
git merge --ff-only "$TARGET"
[[ $(git rev-parse HEAD) == "$TARGET" ]]
# Catch the failure mode that previously left the site unavailable.
runuser -u hexa-studio -- test -r "$APP/app/web/server.py"
systemctl start "$SERVICE"

READY=0
for _ in $(seq 1 60); do
  if [[ $(systemctl is-active "$SERVICE") == active ]] &&
     curl -fsS --max-time 3 http://127.0.0.1:8787/ready 2>/dev/null |
       python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("ready") is True' 2>/dev/null; then
    READY=1
    break
  fi
  sleep 2
done
[[ "$READY" -eq 1 ]]
HTTP="$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/api/uploads/config)"
[[ "$HTTP" == 200 || "$HTTP" == 401 ]]
[[ $(git rev-parse HEAD) == "$TARGET" ]]
trap - ERR INT TERM
rm -f "$MAINTENANCE"
trap - EXIT
echo "DEPLOY_SUCCESS: $TARGET"
echo "BACKUP: $BACKUP"
