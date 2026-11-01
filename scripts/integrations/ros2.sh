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

apt-get update
apt-get -y install software-properties-common curl
add-apt-repository universe
apt-get update

ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest |
    grep -F "tag_name" | awk -F'"' '{print $4}')

# shellcheck disable=SC1091
. /etc/os-release
UBUNTU_CODENAME_VAL="${UBUNTU_CODENAME:-${VERSION_CODENAME}}"
curl -L -o /tmp/ros2-apt-source.deb \
    "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.${UBUNTU_CODENAME_VAL}_all.deb"
dpkg -i /tmp/ros2-apt-source.deb
rm /tmp/ros2-apt-source.deb

apt-get update
apt-get -y install "ros-${ROS_DISTRO_VAL}-${ROS_TARGET_VAL}"
apt-get -y install ros-dev-tools
rm -rf /var/lib/apt/lists/*
