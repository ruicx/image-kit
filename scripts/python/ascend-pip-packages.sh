#!/bin/bash
# Add development packages while preserving the Ascend vendor Python environment.
# Run as root after python-install.sh --mode existing and installing ascend-pip-check.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ascend-pip-packages.sh --requirements <path>

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
    echo "ascend-pip-packages.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi
if [ -z "${REQUIREMENTS_FILE}" ] || [ ! -f "${REQUIREMENTS_FILE}" ] || [ ! -r "${REQUIREMENTS_FILE}" ]; then
    echo "ascend-pip-packages.sh: --requirements must name a readable file" >&2
    exit 64
fi

# Preserve the complete vendor stack without importing driver-dependent torch_npu modules.
install -d /opt/image-python
python3 -m pip list --format=freeze >/opt/image-python/base-constraints.txt
echo "Preserving preinstalled Python package versions:"
cat /opt/image-python/base-constraints.txt

# Preserve vendor protobuf 3.20.0; the profiler's OTLP exporters require protobuf >=5.
python3 -m pip install --no-cache-dir --break-system-packages \
    --constraint /opt/image-python/base-constraints.txt \
    --requirement "${REQUIREMENTS_FILE}" \
    plotly ninja colorlog msguard
/usr/local/bin/ascend-pip-check
