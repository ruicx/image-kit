#!/bin/bash
# Install a version-pinned llama.cpp Ubuntu x64 CUDA binary release from GitHub.
# Options: --version and --cuda-version. The consuming image documents the checksum exception.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: llama-cpp.sh [--version <build>] [--cuda-version <major.minor>]

Options:
  --version <value>       llama.cpp release build (default: b11046)
  --cuda-version <value>  CUDA asset version (default: 12.8)
  -h, --help              Show this help
EOF
}

LLAMA_CPP_VERSION_VAL="b11046"
LLAMA_CPP_CUDA_VERSION_VAL="12.8"

if ! PARSED=$(getopt -o h -l help,version:,cuda-version: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --version)
            LLAMA_CPP_VERSION_VAL="$2"
            shift 2
            ;;
        --cuda-version)
            LLAMA_CPP_CUDA_VERSION_VAL="$2"
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
    echo "llama-cpp.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi
if [[ ! "${LLAMA_CPP_VERSION_VAL}" =~ ^b[0-9]+$ ]]; then
    echo "llama-cpp.sh: version must use the b<build-number> release format" >&2
    exit 64
fi
if [[ ! "${LLAMA_CPP_CUDA_VERSION_VAL}" =~ ^[0-9]+\.[0-9]+$ ]]; then
    echo "llama-cpp.sh: CUDA version must use numeric major.minor format" >&2
    exit 64
fi
case "$(uname -m)" in
    x86_64) ;;
    *)
        echo "llama-cpp.sh: unsupported architecture; expected x86_64" >&2
        exit 1
        ;;
esac

archive="llama-${LLAMA_CPP_VERSION_VAL}-bin-ubuntu-cuda-${LLAMA_CPP_CUDA_VERSION_VAL}-x64.tar.gz"
download_url="https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_CPP_VERSION_VAL}/${archive}"
install_directory="/opt/llama.cpp"
temporary_directory=$(mktemp -d)
trap 'rm -rf "${temporary_directory}"' EXIT

curl --fail --location --proto '=https' --tlsv1.2 \
    "${download_url}" \
    --output "${temporary_directory}/${archive}"

install -d -m 0755 "${install_directory}"
tar -xzf "${temporary_directory}/${archive}" --strip-components=1 -C "${install_directory}"
if [ ! -x "${install_directory}/llama-cli" ]; then
    echo "llama-cpp.sh: release archive did not contain an executable llama-cli" >&2
    exit 1
fi

# Keep upstream libraries beside the binaries for their $ORIGIN RPATH and expose only commands.
install -d -m 0755 /usr/local/bin
linked_executable=0
for executable in "${install_directory}"/llama-*; do
    if [ ! -f "${executable}" ] || [ ! -x "${executable}" ]; then
        continue
    fi
    ln -sfn "${executable}" "/usr/local/bin/$(basename "${executable}")"
    linked_executable=1
done
if [ "${linked_executable}" -ne 1 ]; then
    echo "llama-cpp.sh: release archive did not contain llama-* executables" >&2
    exit 1
fi
