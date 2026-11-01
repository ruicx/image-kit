#!/bin/bash
# Shared container entrypoint. SSH supports disabled, key-only, and password modes.
# Reads DEFAULT_USER, SSH_MODE, and the optional SSH_PASSWORD_FILE.
# Passwordless sudo is used only when the image starts as a managed non-root user.
set -euo pipefail

SSH_MODE_VAL="${SSH_MODE:-disabled}"
DEFAULT_USER_VAL="${DEFAULT_USER:-root}"

run_as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo -n "$@"
    fi
}

RESOLVED_LOGIN_USER="${DEFAULT_USER_VAL}"
if ! id "${RESOLVED_LOGIN_USER}" >/dev/null 2>&1; then
    echo "[entrypoint] SSH login user '${RESOLVED_LOGIN_USER}' does not exist" >&2
    exit 64
fi

# Start sshd only after validating the explicit mode and public-key policy.
case "${SSH_MODE_VAL}" in
    disabled) ;;
    key-only)
        USER_HOME="$(getent passwd "${RESOLVED_LOGIN_USER}" | cut -d: -f6)"
        AUTHORIZED_KEYS="${USER_HOME}/.ssh/authorized_keys"
        if [ ! -s "${AUTHORIZED_KEYS}" ]; then
            if [ "${SSH_ALLOW_EMPTY_AUTHORIZED_KEYS:-false}" != "true" ]; then
                echo "[entrypoint] SSH_MODE=key-only requires a non-empty ${AUTHORIZED_KEYS}" >&2
                exit 64
            fi
            echo "[entrypoint] SSH awaits a public key in ${AUTHORIZED_KEYS}" >&2
        fi
        run_as_root mkdir -p /run/sshd
        run_as_root ssh-keygen -A >/dev/null
        run_as_root /usr/sbin/sshd \
            -o PasswordAuthentication=no \
            -o KbdInteractiveAuthentication=no \
            -o "PermitRootLogin=$([ "${RESOLVED_LOGIN_USER}" = "root" ] && echo prohibit-password || echo no)" \
            -o "AllowUsers=${RESOLVED_LOGIN_USER}"
        ;;
    password)
        # A mounted password file avoids exposing credentials in image layers or arguments.
        if [ "${RESOLVED_LOGIN_USER}" = "root" ] && [ -z "${SSH_PASSWORD_FILE:-}" ]; then
            echo "[entrypoint] root password SSH requires SSH_PASSWORD_FILE" >&2
            exit 64
        fi
        if [ -n "${SSH_PASSWORD_FILE:-}" ]; then
            if ! run_as_root test -s "${SSH_PASSWORD_FILE}"; then
                echo "[entrypoint] SSH_PASSWORD_FILE must reference a non-empty file" >&2
                exit 64
            fi
            # Expand positional parameters only inside the privileged child shell.
            # shellcheck disable=SC2016
            run_as_root /bin/bash -c '
                password=$(cat "$1")
                if [ -z "${password}" ]; then
                    echo "[entrypoint] SSH_PASSWORD_FILE must contain a non-empty password" >&2
                    exit 64
                fi
                printf "%s:%s\n" "$2" "${password}" | chpasswd
            ' _ "${SSH_PASSWORD_FILE}" "${RESOLVED_LOGIN_USER}"
        fi
        run_as_root mkdir -p /run/sshd
        run_as_root ssh-keygen -A >/dev/null
        run_as_root /usr/sbin/sshd \
            -o PasswordAuthentication=yes \
            -o KbdInteractiveAuthentication=no \
            -o PermitEmptyPasswords=no \
            -o "PermitRootLogin=$([ "${RESOLVED_LOGIN_USER}" = "root" ] && echo yes || echo no)" \
            -o "AllowUsers=${RESOLVED_LOGIN_USER}"
        ;;
    *)
        echo "[entrypoint] unsupported SSH_MODE '${SSH_MODE_VAL}'" >&2
        exit 64
        ;;
esac

# Preserve the user command as PID 1 so signals propagate directly.
exec "$@"
