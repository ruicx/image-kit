#!/bin/bash
# Install the shared C/C++, debugging, and command-line development toolset.
# Run as root after system.sh. This script has no configuration options.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: dev-tools.sh

Options:
  -h, --help  Show this help
EOF
}

if ! PARSED=$(getopt -o h -l help -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
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
    echo "dev-tools.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi

case "$(uname -m)" in
    x86_64 | aarch64) ;;
    *)
        echo "dev-tools.sh: unsupported architecture; expected x86_64 or aarch64" >&2
        exit 1
        ;;
esac

# Keep the package set in one layer because development dependencies are large.
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
    acl \
    bat \
    build-essential \
    clangd \
    cloc \
    curl \
    fd-find \
    ffmpeg \
    gdb \
    git \
    git-lfs \
    graphviz \
    htop \
    iputils-ping \
    less \
    libgflags-dev \
    libgoogle-glog-dev \
    libgmock-dev \
    libgtest-dev \
    libopencv-dev \
    libssl-dev \
    man-db \
    nfs-common \
    ninja-build \
    openssl \
    parallel \
    ripgrep \
    rsync \
    screen \
    systemd-coredump \
    tmux \
    trash-cli \
    tree \
    unzip \
    vim \
    zip \
    zstd

# Debian and Ubuntu use alternative executable names for fd and bat.
ln -sfn "$(command -v fdfind)" /usr/local/bin/fd
ln -sfn "$(command -v batcat)" /usr/local/bin/bat

# sudo may discard EDITOR and VISUAL, so set the system editor explicitly.
if [ -x /usr/bin/vim.basic ]; then
    update-alternatives --set editor /usr/bin/vim.basic
fi

git lfs install --system

rm -rf /var/lib/apt/lists/*
