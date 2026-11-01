#!/bin/bash
# Create the configured workspace directory and assign it to an existing user.
# Options: --path and --owner.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: workspace.sh [--path <absolute-path>] [--owner <username>]

Options:
  --path <value>   Workspace directory (default: /work)
  --owner <value>  Existing user that owns the directory (default: root)
  -h, --help       Show this help
EOF
}

WORKSPACE_PATH="/work"
WORKSPACE_OWNER="root"

if ! PARSED=$(getopt -o h -l help,path:,owner: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --path)
            WORKSPACE_PATH="$2"
            shift 2
            ;;
        --owner)
            WORKSPACE_OWNER="$2"
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
    echo "workspace.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi

if [[ ! "${WORKSPACE_PATH}" =~ ^/ ]] || [[ "${WORKSPACE_PATH}" =~ ^/+$ ]]; then
    echo "workspace.sh: path must be an absolute directory other than /" >&2
    exit 64
fi
if [[ "${WORKSPACE_PATH}" =~ (^|/)\.\.?(/|$) ]]; then
    echo "workspace.sh: path must not contain . or .. components" >&2
    exit 64
fi
if [[ ! "${WORKSPACE_OWNER}" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
    echo "workspace.sh: invalid owner '${WORKSPACE_OWNER}'" >&2
    exit 64
fi
if ! id -u "${WORKSPACE_OWNER}" >/dev/null 2>&1; then
    echo "workspace.sh: owner '${WORKSPACE_OWNER}' does not exist" >&2
    exit 64
fi

mkdir -p -- "${WORKSPACE_PATH}"
chown "${WORKSPACE_OWNER}:${WORKSPACE_OWNER}" "${WORKSPACE_PATH}"
