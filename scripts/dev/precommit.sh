#!/bin/bash
# Pre-cache pre-commit hook environments so they are available without network access.
# Must run as the target non-root user (USER directive before this RUN in the Dockerfile).
# Option: --config (default: /tmp/assets/.pre-commit-config.yaml).
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: precommit.sh [--config <path>]

Options:
  --config <value>  pre-commit config path (default: /tmp/assets/.pre-commit-config.yaml)
  -h, --help        Show this help
EOF
}

PRECOMMIT_CONFIG="/tmp/assets/.pre-commit-config.yaml"
if ! PARSED=$(getopt -o h -l help,config: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --config)
            PRECOMMIT_CONFIG="$2"
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
    echo "precommit.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi
if [ ! -f "${PRECOMMIT_CONFIG}" ]; then
    echo "precommit.sh: config file not found: ${PRECOMMIT_CONFIG}" >&2
    exit 66
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

git init "$TMPDIR"
cp "$PRECOMMIT_CONFIG" "$TMPDIR/.pre-commit-config.yaml"
cd "$TMPDIR"
pre-commit install-hooks
