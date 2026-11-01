#!/bin/bash
# Minimal system bootstrap: package metadata, timezone, and locale.
# Developer CLI tools are installed separately by dev-tools.sh, and GUI / WSLg
# deps by wslg.sh, to keep each layer's cache independent.
# Options: --timezone (default: Asia/Shanghai).
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: system.sh [--timezone <IANA timezone>]

Options:
  --timezone <value>  Container timezone (default: Asia/Shanghai)
  -h, --help          Show this help
EOF
}

TZ_VAL="Asia/Shanghai"

if ! PARSED=$(getopt -o h -l help,timezone: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --timezone)
            TZ_VAL="$2"
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
    echo "system.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi
if [[ ! "${TZ_VAL}" =~ ^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)+$ && "${TZ_VAL}" != "UTC" ]]; then
    echo "system.sh: invalid timezone name '${TZ_VAL}'" >&2
    exit 64
fi

case "$(uname -m)" in
    x86_64 | aarch64) ;;
    *)
        echo "system.sh: unsupported architecture; expected x86_64 or aarch64" >&2
        exit 1
        ;;
esac

chmod 777 /tmp

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
    ca-certificates tzdata lsb-release wget software-properties-common gnupg locales

if [ ! -e "/usr/share/zoneinfo/${TZ_VAL}" ]; then
    echo "system.sh: unknown timezone '${TZ_VAL}'" >&2
    exit 64
fi
ln -snf "/usr/share/zoneinfo/${TZ_VAL}" /etc/localtime
echo "${TZ_VAL}" >/etc/timezone
locale-gen en_US.UTF-8

rm -rf /var/lib/apt/lists/*
