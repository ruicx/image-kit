#!/bin/bash
# Check Ascend Python dependencies, allowing only the three approved vendor issues.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ascend-pip-check

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
    echo "ascend-pip-check: unexpected positional arguments: $*" >&2
    exit 64
fi

status=0
output="$(python3 -m pip check 2>&1)" || status=$?
if [ "${status}" -eq 0 ]; then
    printf '%s\n' "${output}"
    exit 0
fi
if [ "${status}" -ne 1 ] || [ -z "${output}" ]; then
    printf '%s\n' "${output}" >&2
    exit "${status}"
fi

# Match the complete diagnostic so changed packages, versions, or requirements fail closed.
unexpected=0
while IFS= read -r issue; do
    case "${issue}" in
        'mindstudio-kl 26.2.0 has requirement numpy<=1.26.4, but you have numpy 2.5.4.')
            printf 'WARNING: allowing known upstream dependency conflict: %s\n' "${issue}" >&2
            ;;
        'ms-service-profiler 26.0.0 requires opentelemetry-exporter-otlp-proto-grpc, which is not installed.' | \
            'ms-service-profiler 26.0.0 requires opentelemetry-exporter-otlp-proto-http, which is not installed.')
            printf 'WARNING: allowing known upstream missing dependency: %s\n' "${issue}" >&2
            ;;
        *)
            printf '%s\n' "${issue}" >&2
            unexpected=1
            ;;
    esac
done <<<"${output}"
exit "${unexpected}"
