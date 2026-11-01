#!/bin/bash
# Install the common development packages into the CUDA image's distribution Python.
# Run as root after python-install.sh; Ascend uses ascend-pip-packages.sh instead.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: cuda-pip-packages.sh --requirements <path>

Options:
  --requirements <path>  Common development requirements file (required)
  -h, --help             Show this help
EOF
}

REQUIREMENTS_FILE=""
if ! PARSED=$(getopt -o h -l help,requirements: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --requirements)
            REQUIREMENTS_FILE="$2"
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
    echo "cuda-pip-packages.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi

if [ -z "${REQUIREMENTS_FILE}" ] || [ ! -f "${REQUIREMENTS_FILE}" ] || [ ! -r "${REQUIREMENTS_FILE}" ]; then
    echo "cuda-pip-packages.sh: --requirements must name a readable file" >&2
    exit 64
fi

# Debian's psutil has no pip RECORD metadata. A pip-owned copy avoids uninstalling apt files.
python3 -m pip install --no-cache-dir --break-system-packages --ignore-installed psutil
python3 -m pip install --no-cache-dir --break-system-packages \
    --requirement "${REQUIREMENTS_FILE}"
