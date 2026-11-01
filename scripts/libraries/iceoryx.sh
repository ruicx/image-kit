#!/bin/bash

# Install iceoryx from source. Option: --version (default: v2.0.8).
# Used by both dev and runtime images.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: iceoryx.sh [--version <git-tag-or-commit>]

Options:
  --version <value>  iceoryx git tag or commit (default: v2.0.8)
  -h, --help         Show this help
EOF
}

ICEORYX_VERSION_VAL="v2.0.8"
if ! PARSED=$(getopt -o h -l help,version: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --version)
            ICEORYX_VERSION_VAL="$2"
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
    echo "iceoryx.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi

apt-get update
apt-get -y upgrade
apt-get install -y libacl1-dev libncurses5-dev

cd /tmp

git clone --depth 1 --branch "${ICEORYX_VERSION_VAL}" https://github.com/eclipse-iceoryx/iceoryx.git

cd iceoryx

cmake -B build -S iceoryx_meta -DBUILD_SHARED_LIBS=ON
cmake --build build -j"$(nproc)"
sudo cmake --build build --target install

rm -rf /var/lib/apt/lists/*
