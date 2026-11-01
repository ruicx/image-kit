#!/bin/bash

# Install cpptrace from source. Option: --version (default: v1.0.4).
# Used by both dev and runtime images.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: cpptrace.sh [--version <git-tag-or-commit>]

Options:
  --version <value>  cpptrace git tag or commit (default: v1.0.4)
  -h, --help         Show this help
EOF
}

CPPTRACE_VERSION_VAL="v1.0.4"
if ! PARSED=$(getopt -o h -l help,version: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --version)
            CPPTRACE_VERSION_VAL="$2"
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
    echo "cpptrace.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi

git clone --depth 1 --branch "${CPPTRACE_VERSION_VAL}" https://github.com/jeremy-rifkin/cpptrace.git

cd cpptrace

cmake -B build -S . -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
cmake --install build
