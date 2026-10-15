"""Prevent deployment release scripts from making Python source root-only."""
from pathlib import Path


DEPLOY_SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "deploy" / "hexa-deploy.sh"


def test_production_deploy_keeps_git_checkout_readable_by_service_user():
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "umask 022" in source
    assert "umask 077" not in source
    assert 'git merge --ff-only "$TARGET"' in source
    assert 'git reset --hard "$OLD"' in source
    assert 'runuser -u hexa-studio -- test -r "$APP/app/web/server.py"' in source


def test_deployment_backup_remains_restricted():
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'install -d -m 700 "$BACKUP"' in source
    assert 'chmod 600 "$BACKUP/hexa.env"' in source
    assert 'chmod 600 "$BACKUP/jobs.sqlite3"' in source
