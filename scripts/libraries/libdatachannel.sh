#!/bin/bash

# Install libdatachannel from source. Option: --version (default: v0.24.5).
# Used by both dev and runtime images.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: libdatachannel.sh [--version <git-tag-or-commit>]

Options:
  --version <value>  libdatachannel git tag or commit (default: v0.24.5)
  -h, --help         Show this help
EOF
}

LIBDATACHANNEL_VERSION_VAL="v0.24.5"
if ! PARSED=$(getopt -o h -l help,version: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --version)
            LIBDATACHANNEL_VERSION_VAL="$2"
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
    echo "libdatachannel.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi

cd /tmp

git clone --depth 1 --branch "${LIBDATACHANNEL_VERSION_VAL}" https://github.com/paullouisageneau/libdatachannel.git
cd libdatachannel
git submodule update --init --recursive --depth 1

cmake -B build -DUSE_GNUTLS=0 -DUSE_NICE=0 -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
cmake --install build
