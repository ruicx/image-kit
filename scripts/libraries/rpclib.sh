#!/bin/bash

# Install rpclib from source. Option: --version (default: v2.3.0).
# Used by both dev and runtime images.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: rpclib.sh [--version <git-tag-or-commit>]

Options:
  --version <value>  rpclib git tag or commit (default: v2.3.0)
  -h, --help         Show this help
EOF
}

RPCLIB_VERSION_VAL="v2.3.0"
if ! PARSED=$(getopt -o h -l help,version: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --version)
            RPCLIB_VERSION_VAL="$2"
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
    echo "rpclib.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi

cd /tmp

git clone --depth 1 --branch "${RPCLIB_VERSION_VAL}" https://github.com/rpclib/rpclib.git
cd rpclib

git submodule update --init --recursive --depth 1

cmake -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DRPCLIB_CXX_STANDARD=14

cmake --build build -j"$(nproc)"
cmake --install build
