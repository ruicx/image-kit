#!/bin/bash
# Install application packages without replacing the Ascend vendor Python stack.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ascend-python-packages.sh --requirements <path>

Options:
  --requirements <path>  Application requirements file (required)
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
    echo "ascend-python-packages.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi
if [ -z "${REQUIREMENTS_FILE}" ] || [ ! -f "${REQUIREMENTS_FILE}" ] || [ ! -r "${REQUIREMENTS_FILE}" ]; then
    echo "ascend-python-packages.sh: --requirements must name a readable file" >&2
    exit 64
fi

python3 -m pip install --break-system-packages \
    --constraint /opt/image-python/base-constraints.txt \
    --requirement "${REQUIREMENTS_FILE}"
/usr/local/bin/ascend-pip-check
