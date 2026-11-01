#!/bin/bash
# Install a version-pinned CMake binary release for Linux amd64 or arm64.
# Options: --version and optional --sha256. Consumers document any checksum exception.
# Used by both dev and runtime images.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: cmake.sh [--version <version>] [--sha256 <checksum>]

Options:
  --version <value>  CMake release version (default: 4.3.2)
  --sha256 <value>   Expected archive SHA-256 (default: documented legacy exception)
  -h, --help         Show this help
EOF
}

CMAKE_VERSION_VAL="4.3.2"
CMAKE_SHA256_VAL=""
if ! PARSED=$(getopt -o h -l help,version:,sha256: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --version)
            CMAKE_VERSION_VAL="$2"
            shift 2
            ;;
        --sha256)
            CMAKE_SHA256_VAL="$2"
            if [[ ! "${CMAKE_SHA256_VAL}" =~ ^[a-f0-9]{64}$ ]]; then
                echo "cmake.sh: sha256 must contain 64 lowercase hexadecimal characters" >&2
                exit 64
            fi
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
    echo "cmake.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi
if [[ ! "${CMAKE_VERSION_VAL}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "cmake.sh: version must use numeric major.minor.patch format" >&2
    exit 64
fi
case "$(uname -m)" in
    x86_64 | aarch64) CMAKE_ARCH="$(uname -m)" ;;
    *)
        echo "cmake.sh: unsupported architecture; expected x86_64 or aarch64" >&2
        exit 1
        ;;
esac

CMAKE_ARCHIVE="cmake-${CMAKE_VERSION_VAL}-linux-${CMAKE_ARCH}.tar.gz"
TEMP_DIRECTORY=$(mktemp -d)
trap 'rm -rf "${TEMP_DIRECTORY}"' EXIT

curl --fail --location --proto '=https' --tlsv1.2 \
    "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION_VAL}/${CMAKE_ARCHIVE}" \
    --output "${TEMP_DIRECTORY}/${CMAKE_ARCHIVE}"
if [ -n "${CMAKE_SHA256_VAL}" ]; then
    printf '%s  %s\n' "${CMAKE_SHA256_VAL}" "${TEMP_DIRECTORY}/${CMAKE_ARCHIVE}" | sha256sum --check -
fi
tar -xzf "${TEMP_DIRECTORY}/${CMAKE_ARCHIVE}" --strip-components=1 -C /usr/local
