#!/bin/bash
# Finalize persisted apt and pip sources after all package installation completes.
# Option: --mirror selects upstream (no changes) or aliyun.
#
# Why this is a separate, last step:
#   - Builds run on GitHub Actions runners (US/EU), where Aliyun mirrors are
#     often *slower* than the default Ubuntu / PyPI sources. We therefore keep
#     the default sources during the whole build so every `apt-get update` /
#     `pip install` in system.sh, ros2.sh, cuda-pip-packages.sh, … uses the fastest
#     upstream available to the builder.
#   - Only after all package installation is done do we flip the *persisted*
#     sources to Aliyun, so that end users pulling the image in China get fast
#     `apt install` / `pip install` without reconfiguring anything.
#
# What this script does:
#   1. Rewrites the apt sources to Aliyun (auto-detects deb822 `.sources`
#      vs classic `.list` format; auto-detects the Ubuntu codename).
#   2. Writes a system-wide pip config pointing at the Aliyun PyPI mirror.
#
# Idempotent: safe to run multiple times. Run as root.
# Currently called at the very end of every Tier 2 final image (dev + runtime),
# AFTER all apt/pip installs are finished.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: finalize-mirror.sh [--mirror <name>]

Options:
  --mirror <value>  Persisted package mirror: upstream or aliyun (default: upstream)
  -h, --help        Show this help
EOF
}

MIRROR="upstream"

if ! PARSED=$(getopt -o h -l help,mirror: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --mirror)
            MIRROR="$2"
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
    echo "finalize-mirror.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi

case "${MIRROR}" in
    upstream)
        echo "finalize-mirror.sh: keeping upstream package sources"
        exit 0
        ;;
    aliyun) ;;
    *)
        echo "finalize-mirror.sh: unsupported mirror '${MIRROR}'" >&2
        exit 64
        ;;
esac

ALIYUN_APT_HOST="mirrors.aliyun.com"
ALIYUN_PIP_URL="https://mirrors.aliyun.com/pypi/simple/"

# ─── Detect Ubuntu codename + CPU architecture ───────────────────────────────
# Aliyun (like Ubuntu upstream) splits packages:
#   - amd64 / i386  → mirrors.aliyun.com/ubuntu/         (mirror of archive.ubuntu.com)
#   - arm64 / …      → mirrors.aliyun.com/ubuntu-ports/   (mirror of ports.ubuntu.com)
# Writing the amd64 path on an arm64 image means apt-get update finds zero
# candidate packages for the host arch, hence failing. Detect via dpkg.
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
fi
if [ -z "${CODENAME:-}" ]; then
    echo "finalize-mirror.sh: could not determine Ubuntu codename; aborting" >&2
    exit 1
fi

DPKG_ARCH="$(dpkg --print-architecture 2>/dev/null || echo unknown)"
case "$DPKG_ARCH" in
    amd64 | i386)
        APT_ROOT="${ALIYUN_APT_HOST}/ubuntu"
        ;;
    arm64 | armhf | ppc64el | riscv64 | s390x)
        APT_ROOT="${ALIYUN_APT_HOST}/ubuntu-ports"
        ;;
    *)
        echo "finalize-mirror.sh: unhandled dpkg architecture '${DPKG_ARCH}'; leaving apt sources untouched" >&2
        # Skip the apt rewrite but still finish (pip mirror still applies below).
        APT_ROOT=""
        ;;
esac
echo "finalize-mirror.sh: detected codename='${CODENAME}' arch='${DPKG_ARCH}' apt_root='${APT_ROOT:-<none>}'"

# ─── 1. apt sources → Aliyun ──────────────────────────────────────────────────
#
# Ubuntu 24.04+ ships /etc/apt/sources.list.d/ubuntu.sources (deb822).
# Ubuntu 22.04  ships /etc/apt/sources.list (one-line) + optional .save.
# We detect which is in use and rewrite the corresponding file. The unused
# variant (if it exists) is emptied to avoid two conflicting upstreams.

deb822_file="/etc/apt/sources.list.d/ubuntu.sources"
classic_file="/etc/apt/sources.list"

write_deb822() {
    # Components present in modern Ubuntu main base image.
    cat >"$deb822_file" <<EOF
Types: deb
URIs: https://${APT_ROOT}/
Suites: ${CODENAME} ${CODENAME}-updates ${CODENAME}-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: https://${APT_ROOT}/
Suites: ${CODENAME}-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
}

write_classic() {
    cat >"$classic_file" <<EOF
deb https://${APT_ROOT}/ ${CODENAME} main restricted universe multiverse
deb https://${APT_ROOT}/ ${CODENAME}-updates main restricted universe multiverse
deb https://${APT_ROOT}/ ${CODENAME}-backports main restricted universe multiverse
deb https://${APT_ROOT}/ ${CODENAME}-security main restricted universe multiverse
EOF
}

apt_rewritten=0
if [ -n "$APT_ROOT" ]; then
    if [ -f "$deb822_file" ]; then
        echo "finalize-mirror.sh: rewriting deb822 source ($deb822_file) → Aliyun (${APT_ROOT})"
        write_deb822
        apt_rewritten=1
        # Ensure no conflicting classic file overrides us.
        if [ -f "$classic_file" ]; then
            cp "$classic_file" "${classic_file}.ubuntu-orig" 2>/dev/null || true
            : >"$classic_file"
        fi
    elif [ -f "$classic_file" ]; then
        echo "finalize-mirror.sh: rewriting classic source ($classic_file) → Aliyun (${APT_ROOT})"
        write_classic
        apt_rewritten=1
        # Back up the original (only first time) so the change is auditable.
        if [ ! -f "${classic_file}.ubuntu-orig" ]; then
            cp "$classic_file" "${classic_file}.ubuntu-orig" 2>/dev/null || true
        fi
    else
        echo "finalize-mirror.sh: neither $deb822_file nor $classic_file found; leaving apt sources untouched" >&2
    fi
fi

# Verify apt still parses and fetches the new config. If not, roll back and fail
# loudly so we never publish a broken-sources image. We do NOT silence apt's
# output on failure — the apt errors are exactly what tells us *why* it failed
# (e.g. wrong path for the host architecture, broken cert chain, wrong arch).
if [ "$apt_rewritten" = "1" ]; then
    if apt-get update 2>&1 | sed 's/^/    apt: /'; then
        rm -rf /var/lib/apt/lists/*
    else
        echo "finalize-mirror.sh: apt-get update failed on the new Aliyun sources; rolling back" >&2
        if [ -f "${classic_file}.ubuntu-orig" ]; then
            cp "${classic_file}.ubuntu-orig" "$classic_file"
        fi
        rm -f "$deb822_file"
        exit 1
    fi
fi

# ─── 2. pip → Aliyun PyPI mirror ──────────────────────────────────────────────
echo "finalize-mirror.sh: writing /etc/pip.conf → Aliyun PyPI mirror"
install -d -m 0755 /etc
cat >/etc/pip.conf <<EOF
[global]
index-url = ${ALIYUN_PIP_URL}
trusted-host = mirrors.aliyun.com
EOF
chmod 0644 /etc/pip.conf

echo "finalize-mirror.sh: done"
