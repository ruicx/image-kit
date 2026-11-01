#!/bin/bash
# Initialize the same toolkits as the pinned vendor entrypoint, then apply shared SSH policy.
set -euo pipefail

# Vendor scripts read optional unset variables; keep strict handling outside their boundary.
set +u
# shellcheck disable=SC1091
source /usr/local/Ascend/ascend-toolkit/set_env.sh
# shellcheck disable=SC1091
source "${ASCEND_HOME_PATH}/share/info/ascendnpu-ir/bin/set_env.sh"
# shellcheck disable=SC1091
source /usr/local/Ascend/nnal/atb/set_env.sh --cxx_abi="${ATB_CXX_ABI:-1}"
set -u

exec /usr/local/bin/docker-entrypoint "$@"
