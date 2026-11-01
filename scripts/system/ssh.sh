#!/bin/bash
# Install and configure the optional SSH server (BUILD-TIME only).
#
# Runs during `docker build`. Everything here must be declarative / persisted
# to disk — a build layer **cannot** actually run a daemon. Starting sshd at
# runtime is the entrypoint's job (see assets/docker-entrypoint.sh).
#
# What this script does:
#   - Installs openssh-server.
#   - Uses the image's default user as the SSH login account.
#   - Configures key-only or password authentication for that account.
#   - Prepares the selected account's authorized_keys mount point.
# Host keys are generated at runtime only when SSH is enabled.
#
# Options: --default-user and --mode.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ssh.sh [--default-user <name>] [--mode <mode>]

Options:
  --default-user <value>  Existing image default user (default: root)
  --mode <value>          SSH policy: disabled, key-only, or password (default: disabled)
  -h, --help              Show this help
EOF
}

DEFAULT_USER_VAL="root"
SSH_MODE_VAL="disabled"

if ! PARSED=$(getopt -o h -l help,default-user:,mode: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --default-user)
            DEFAULT_USER_VAL="$2"
            shift 2
            ;;
        --mode)
            SSH_MODE_VAL="$2"
            shift 2
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
    esac
done
if [ "$#" -ne 0 ]; then
    echo "ssh.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi
case "${SSH_MODE_VAL}" in
    disabled | key-only | password) ;;
    *)
        echo "ssh.sh: unsupported mode '${SSH_MODE_VAL}'" >&2
        exit 64
        ;;
esac
if [[ ! "${DEFAULT_USER_VAL}" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
    echo "ssh.sh: invalid default user '${DEFAULT_USER_VAL}'" >&2
    exit 64
fi
RESOLVED_LOGIN_USER="${DEFAULT_USER_VAL}"

case "$(uname -m)" in
    x86_64 | aarch64) ;;
    *)
        echo "ssh.sh: unsupported architecture; expected x86_64 or aarch64" >&2
        exit 1
        ;;
esac

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssh-server
rm -rf /var/lib/apt/lists/*

# /run/sshd is where sshd chroots its priv-separated child at runtime.
# Create it here so the entrypoint doesn't need root-only mkdir work.
mkdir -p /run/sshd
chmod 0755 /run/sshd

if [ "${RESOLVED_LOGIN_USER}" = "root" ]; then
    if [ "${SSH_MODE_VAL}" = "password" ]; then
        PERMIT_ROOT_LOGIN="yes"
    elif [ "${SSH_MODE_VAL}" = "key-only" ]; then
        PERMIT_ROOT_LOGIN="prohibit-password"
    else
        PERMIT_ROOT_LOGIN="no"
    fi
else
    PERMIT_ROOT_LOGIN="no"
fi

cat >/etc/ssh/sshd_config.d/99-dev-image.conf <<EOF
PubkeyAuthentication yes
PasswordAuthentication $([ "${SSH_MODE_VAL}" = "password" ] && echo yes || echo no)
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin ${PERMIT_ROOT_LOGIN}
AllowUsers ${RESOLVED_LOGIN_USER}
EOF

# Seed authorized_keys only for the account selected by the SSH policy.
if ! id "${RESOLVED_LOGIN_USER}" >/dev/null 2>&1; then
    echo "ssh.sh: login user '${RESOLVED_LOGIN_USER}' does not exist" >&2
    exit 1
fi
USER_HOME="$(getent passwd "${RESOLVED_LOGIN_USER}" | cut -d: -f6)"
mkdir -p "${USER_HOME}/.ssh"
touch "${USER_HOME}/.ssh/authorized_keys"
chmod 0700 "${USER_HOME}/.ssh"
chmod 0600 "${USER_HOME}/.ssh/authorized_keys"
chown -R "${RESOLVED_LOGIN_USER}":"$(id -gn "${RESOLVED_LOGIN_USER}")" "${USER_HOME}/.ssh"

# NOTE: do NOT call `service ssh start` / `systemctl start ssh` here — a build
# layer has no init and the daemon would die the moment the layer commits.
# Starting sshd is the entrypoint's job at container runtime when explicitly enabled.
