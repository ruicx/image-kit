#!/bin/bash
# Install ROS2. Options: --distro (default: jazzy), --target (default: ros-base).
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ros2.sh [--distro <name>] [--target <metapackage>]

Options:
  --distro <value>  ROS distribution (default: jazzy)
  --target <value>   ROS metapackage suffix (default: ros-base)
  -h, --help         Show this help
EOF
}

ROS_DISTRO_VAL="jazzy"
ROS_TARGET_VAL="ros-base"
if ! PARSED=$(getopt -o h -l help,distro:,target: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --distro)
            ROS_DISTRO_VAL="$2"
            shift 2
            ;;
        --target)
            ROS_TARGET_VAL="$2"
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
    echo "ros2.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi
if [[ ! "${ROS_DISTRO_VAL}" =~ ^[a-z0-9-]+$ || ! "${ROS_TARGET_VAL}" =~ ^[a-z0-9-]+$ ]]; then
    echo "ros2.sh: distro and target must contain only lowercase letters, digits, and hyphens" >&2
    exit 64
fi

# Pin the repository bootstrap package so builds can fetch its release asset directly.
# shellcheck disable=SC1091
. /etc/os-release
UBUNTU_CODENAME_VAL="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
ROS_APT_SOURCE_VERSION=1.3.0
case "${UBUNTU_CODENAME_VAL}" in
    bookworm) ROS_APT_SOURCE_SHA256=d5fdc7050221ab0983a4faf572590fca265c3ffd3f23650fff7a0d62297d81d7 ;;
    bullseye) ROS_APT_SOURCE_SHA256=5877c610f8f220b84a85d0582dda77475b8b7bdd6e8e72508b6dba1a54020231 ;;
    focal) ROS_APT_SOURCE_SHA256=14c22046f6aae248a37a7bb52000ad1fae29aa1d7ae9fb7aead90bb01ad99355 ;;
    jammy) ROS_APT_SOURCE_SHA256=110b9a462d55252decb8b7c816f61c2ba0d9890ce5fb93ac504e97cae5860d76 ;;
    noble) ROS_APT_SOURCE_SHA256=f31d84adf5054c7d60ded0e82c0f776a77ea33af53d08f40b9ad7c94cca55296 ;;
    resolute) ROS_APT_SOURCE_SHA256=e70bc980395f4a3b366b9c5e7f8f9b4d63a4064fb115f6ff3bc52f7faa02ef69 ;;
    trixie) ROS_APT_SOURCE_SHA256=1339b4eb887d81aa561dd56e6e047685765492e383e29ff4bc2f8cff3c6506ed ;;
    *)
        echo "ros2.sh: no pinned ROS apt source for ${UBUNTU_CODENAME_VAL:-unknown distribution}" >&2
        exit 1
        ;;
esac

apt-get update
apt-get -y install software-properties-common curl
add-apt-repository universe
apt-get update

TEMP_DIRECTORY=$(mktemp -d)
trap 'rm -rf -- "${TEMP_DIRECTORY}"' EXIT
ROS_APT_SOURCE_DEB="${TEMP_DIRECTORY}/ros2-apt-source.deb"
curl --fail --silent --show-error --location --retry 3 --proto '=https' --tlsv1.2 \
    --output "${ROS_APT_SOURCE_DEB}" \
    "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.${UBUNTU_CODENAME_VAL}_all.deb"
printf '%s  %s\n' "${ROS_APT_SOURCE_SHA256}" "${ROS_APT_SOURCE_DEB}" | sha256sum --check -
dpkg -i "${ROS_APT_SOURCE_DEB}"

apt-get update
apt-get -y install "ros-${ROS_DISTRO_VAL}-${ROS_TARGET_VAL}"
apt-get -y install ros-dev-tools
rm -rf /var/lib/apt/lists/*
