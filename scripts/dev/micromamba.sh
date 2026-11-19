#!/bin/bash
# Install the checksum-verified upstream micromamba binary as root.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: micromamba.sh --version <release> [--sha256-amd64 <sha256>] [--sha256-arm64 <sha256>]

Installs micromamba in /usr/local/bin. Supply the SHA-256 for the build architecture.
Use the full upstream release tag, for example 2.10.0-0.
EOF
}

version=""
sha256_amd64=""
sha256_arm64=""
if ! parsed=$(getopt -o h -l help,version:,sha256-amd64:,sha256-arm64: -n micromamba.sh -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$parsed"
while true; do
    case "$1" in
        --version)
            version="$2"
            shift 2
            ;;
        --sha256-amd64)
            sha256_amd64="$2"
            shift 2
            ;;
        --sha256-arm64)
            sha256_arm64="$2"
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

if [[ $# -ne 0 || ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9]+)?$ ]]; then
    usage >&2
    exit 64
fi
case "$(uname -m)" in
    x86_64)
        asset=micromamba-linux-64
        checksum="$sha256_amd64"
        ;;
    aarch64)
        asset=micromamba-linux-aarch64
        checksum="$sha256_arm64"
        ;;
    *)
        echo "micromamba.sh: unsupported architecture; expected x86_64 or aarch64" >&2
        exit 1
        ;;
esac
if [[ ! "$checksum" =~ ^[a-f0-9]{64}$ ]]; then
    echo "micromamba.sh: supply a valid SHA-256 for ${asset}" >&2
    exit 64
fi

download_dir=$(mktemp -d)
trap 'rm -rf -- "$download_dir"' EXIT
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "https://github.com/mamba-org/micromamba-releases/releases/download/${version}/${asset}" \
    --output "${download_dir}/micromamba"
printf '%s  %s\n' "$checksum" "${download_dir}/micromamba" | sha256sum --check -
install -m 0755 "${download_dir}/micromamba" /usr/local/bin/micromamba
