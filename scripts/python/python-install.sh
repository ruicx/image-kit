#!/bin/bash
# Prepare the distribution Python or preserve a preinstalled development interpreter.
# Run as root after system.sh and dev-tools.sh.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: python-install.sh [--mode <system|existing>]

Options:
  --mode <value>  Bootstrap system Python or validate existing Python (default: system)
  -h, --help      Show this help
EOF
}

MODE_VAL="system"
if ! PARSED=$(getopt -o h -l help,mode: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --mode)
            MODE_VAL="$2"
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
    echo "python-install.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi

case "${MODE_VAL}" in
    system) ;;
    existing)
        # A vendor image owns this interpreter, its headers, and its pip. Never replace them.
        python3 - <<'PYTHON'
import pathlib
import sysconfig
import venv

assert pathlib.Path(sysconfig.get_path("include"), "Python.h").is_file()
PYTHON
        python3 -m pip --version
        exit 0
        ;;
    *)
        echo "python-install.sh: unsupported mode '${MODE_VAL}'" >&2
        exit 64
        ;;
esac

case "$(uname -m)" in
    x86_64 | aarch64) ;;
    *)
        echo "python-install.sh: unsupported architecture; expected x86_64 or aarch64" >&2
        exit 1
        ;;
esac

# Other apt capabilities may already have introduced the default interpreter. Installing these
# metapackages deliberately normalizes its headers, venv support, and unversioned `python` command.
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
    python-is-python3 \
    python3 \
    python3-dev \
    python3-venv
rm -rf /var/lib/apt/lists/*

PYTHON_BIN="$(command -v python3)"
PYTHON_VERSION="$("${PYTHON_BIN}" -c 'import platform; print(platform.python_version())')"
echo "Bootstrapping pip for ${PYTHON_BIN} (${PYTHON_VERSION})"

# This rolling installer is an explicit image-family exception documented in the bilingual README.
GET_PIP_SCRIPT="$(mktemp)"
trap 'rm -f "${GET_PIP_SCRIPT}"' EXIT
curl -LsSf https://bootstrap.pypa.io/get-pip.py -o "${GET_PIP_SCRIPT}"
"${PYTHON_BIN}" "${GET_PIP_SCRIPT}" --no-cache-dir --break-system-packages
"${PYTHON_BIN}" -m pip --version
