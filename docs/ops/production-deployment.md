# HEXA production deployment — bayer only

## Release policy

- Develop and test on `montage`. Promote only an approved, tested commit to `bayer` with a fast-forward. Never force-push production.
- Only one automated GitHub workflow runs: **HEXA CI/CD (Bayer)** on a push to `bayer`. Its single Linux job runs the complete mandatory core, package, visual and real-package A-D test gates in sequence, then deploys the exact successful SHA. `montage` pushes never trigger GitHub Actions.
- `HEXA_AUTO_DEPLOY=true` enables the deploy stage; a missing or different value fails closed (tests may pass, but nothing deploys).
- An active rendering job or a recent resumable upload blocks deployment. Once the production version with the maintenance gate is installed, incoming writes are temporarily refused (503, Retry-After) during a deploy; existing reads/downloads remain available.
- The deployment script is copied to a **root-owned location outside the repository**, executed by a dedicated forced-command SSH user. Do not grant GitHub Actions unrestricted root SSH access.
- SQLite is backed up with Python's online backup API. Only `hexa-storyengine.service` is stopped/restarted; nginx, Redis, MySQL and other sites are untouched.

## GitHub settings

Go to **Settings → Secrets and variables → Actions**.

Secrets:

- `HEXA_DEPLOY_SSH_PRIVATE_KEY`: new dedicated ED25519 private key generated on a trusted laptop. **Never paste this in chat or commit it to Git.**
- `HEXA_DEPLOY_KNOWN_HOSTS`: pinned VPS host public key in OpenSSH known_hosts format, e.g. `62.84.188.239 ssh-ed25519 AAAA...`. Read and verify it from an already trusted SSH session (`/etc/ssh/ssh_host_ed25519_key.pub`). Do not blindly trust an unverified `ssh-keyscan`.

Variables:

- `HEXA_DEPLOY_HOST`: VPS SSH address (currently `62.84.188.239`).
- `HEXA_DEPLOY_PORT`: `22` unless customized.
- `HEXA_AUTO_DEPLOY`: initially `false`; switch to `true` only after manual validation.

Consider enabling branch protection for `bayer` and required reviewers for the `production` GitHub Environment.

## One-time VPS bootstrap (root SSH, no unrelated services touched)

The production checkout is `/var/www/hexa-storyengine`, service is `hexa-storyengine.service`, and storage is `/var/lib/hexa-storyengine`. Do this only while idle.

The repo might still be checked out on the previous release. You can fetch the new scripts without checking out or restarting the service:

```bash
cd /var/www/hexa-storyengine
git fetch origin bayer
git show origin/bayer:ops/deploy/hexa-deploy.sh > /root/hexa-deploy-staged.sh
git show origin/bayer:ops/deploy/hexa-ssh-gate.sh > /root/hexa-ssh-gate-staged.sh
bash -n /root/hexa-deploy-staged.sh /root/hexa-ssh-gate-staged.sh
install -o root -g root -m 0755 /root/hexa-deploy-staged.sh /usr/local/sbin/hexa-deploy
install -o root -g root -m 0755 /root/hexa-ssh-gate-staged.sh /usr/local/bin/hexa-ssh-gate

id hexa-deploy >/dev/null 2>&1 || useradd -m -s /bin/bash hexa-deploy
install -d -o hexa-deploy -g hexa-deploy -m 0700 /home/hexa-deploy/.ssh
printf 'hexa-deploy ALL=(root) NOPASSWD: /usr/local/sbin/hexa-deploy *\n' > /etc/sudoers.d/hexa-deploy
chmod 0440 /etc/sudoers.d/hexa-deploy
visudo -cf /etc/sudoers.d/hexa-deploy
```

Generate a **new** ED25519 SSH key on the laptop using `ssh-keygen -t ed25519`. Use a distinct path such as `~/.ssh/hexa_actions_deploy` (no passphrase because GitHub Actions is unattended; keep the local copy private). Put the **public** key on the VPS in `/home/hexa-deploy/.ssh/authorized_keys` as exactly one line:

```text
restrict,command="/usr/local/bin/hexa-ssh-gate" ssh-ed25519 AAAA... hexa-actions
```

Then:

```bash
chown hexa-deploy:hexa-deploy /home/hexa-deploy/.ssh/authorized_keys
chmod 0600 /home/hexa-deploy/.ssh/authorized_keys
```

The `restrict` option disables forwarding, agent forwarding and PTY, while `hexa-ssh-gate` accepts only `deploy <40-character-SHA>`. No SSH private key needs to come from the VPS, and no root credential belongs in GitHub.

## Normal workflow

1. Develop and inspect real local renders on `montage`. Claude's dedicated `cinematic/vnext2` worktree stays isolated.
2. After approval, fast-forward `bayer` to the tested `montage` commit and push `bayer` to GitHub.
3. Exactly one `HEXA CI/CD (Bayer)` run with one Linux job executes on the `bayer` push. Tests run sequentially; ANY failure prevents deployment.
4. This job compiles and lints, checks web/API/uploads, Test1/Test2/Test3, semantic certifications, package holdouts, visual gates, and all six real Final Packages (levels A-D). Corpus fingerprints and nonzero required test execution are mandatory.
5. The job rechecks that its SHA is still the latest on `bayer`, then calls the existing restricted SSH deploy script. A render or recent active upload blocks the deploy. The script backs up SQLite, stops only HEXA, verifies readiness and rolls back code on failure.
6. Verify `DEPLOY_SUCCESS` and the SHA in the VPS. If the server is busy, rerun this same workflow after it is idle. `montage` never directly deploys.

## Optional manual deeper checks

`Manual V2 Cross-platform Checks` retains the former dedicated Windows runner, but is no longer automatic. The single production Linux job exercises the same test source on Linux; this does NOT constitute Windows-runner certification. `Manual Real Package / Level E` retains optional full-length Level E encoding (explicit request with `level_e=true`). Normal automatic certification covers levels A-D, not Level E.

## Recovery notes

- Deploy backups are stored in `/root/hexa-backups/ci-*` with previous SHA, SQLite copy, environment file and systemd service unit.
- Failed readiness triggers an attempted rollback of **code only**. Restoring old SQLite blindly can erase newer job state; database rollback needs operator approval.
- If a killed/dead deployment leaves `/var/lib/hexa-storyengine/web/.deploy-maintenance`, investigate and confirm no deployment is still running before removing it manually.
- This uses controlled in-place Fast-forward updates with a short outage, matching today's VPS layout. Immutable release directories and atomic symlink cutover can be added as a separate upgrade. Do not claim zero downtime.

## Automatic delivery verification

Use a documentation-only change to validate the first automatic release safely.
Make the change on `montage` and confirm its checks without touching production.
Promote the exact reviewed commit to `bayer` with fast-forward (never force).
Wait for both `V2 CI` and `Real Package Certification` to pass on that SHA.
Verify the `HEXA Production Deploy` run was created by `workflow_run` (not manually dispatched)
and ended with `DEPLOY_SUCCESS` or `DEPLOY_NOOP`. Verify the target SHA and
`/ready` directly on the VPS. Never claim automatic deploy was tested solely
because a manually dispatched run succeeded. Recheck inactive jobs and uploads
immediately before promoting a release.
