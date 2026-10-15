#!/usr/bin/env bash
# Root-owned copy at /usr/local/bin/hexa-ssh-gate; invoked as SSH forced command.
set -Eeuo pipefail
if [[ "${SSH_ORIGINAL_COMMAND:-}" =~ ^deploy[[:space:]]([0-9a-f]{40})$ ]]; then
  exec sudo -n /usr/local/sbin/hexa-deploy "${BASH_REMATCH[1]}"
fi
echo 'Only deploy <full SHA> is allowed' >&2
exit 64
