#!/bin/bash
# Preserve the vendor CANN initialization and expose its environment to SSH and zsh sessions.
# Run as root in the Ascend image after the optional developer shell installation.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ascend-environment.sh

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
    echo "ascend-environment.sh: unexpected positional arguments: $*" >&2
    exit 64
fi

# Vendor scripts reference optional unset variables, so enable nounset only after sourcing them.
set +u
# shellcheck disable=SC1091
source /usr/local/Ascend/ascend-toolkit/set_env.sh
# shellcheck disable=SC1091
source "${ASCEND_HOME_PATH}/share/info/ascendnpu-ir/bin/set_env.sh"
# shellcheck disable=SC1091
source /usr/local/Ascend/nnal/atb/set_env.sh --cxx_abi="${ATB_CXX_ABI:-1}"
set -u

# SSH creates a fresh environment and Ubuntu login profiles reset PATH. Export only the vendor
# development variables, never device-selection or other Ascend container-runtime settings.
python3 - <<'PYTHON'
import os
from pathlib import Path
from shlex import quote

names = {
    "PATH", "LD_LIBRARY_PATH", "PYTHONPATH", "CMAKE_PREFIX_PATH", "TOOLCHAIN_HOME",
    "ASCEND_TOOLKIT_HOME", "ASCEND_TOOLKIT_LATEST_HOME", "ASCEND_AICPU_PATH",
    "ASCEND_OPP_PATH", "ASCEND_HOME_PATH", "ASCEND_CUSTOM_OPP_PATH",
}
names.update(name for name in os.environ if name.startswith(("ATB_", "LCCL_", "BISHENG_")))
lines = ["# Restore the pinned vendor development environment in login and zsh sessions."]
for name in sorted(names):
    if name in os.environ:
        suffix = ':"${PATH}"' if name == "PATH" else ""
        lines.append(f"export {name}={quote(os.environ[name])}{suffix}")
Path("/etc/profile.d/ascend-dev.sh").write_text("\n".join(lines) + "\n", encoding="utf-8")
PYTHON
# Creating this package-owned file before zsh-common is installed triggers a dpkg
# conffile prompt. Leave it absent when the optional shell has not been installed.
if [ -f /etc/zsh/zshenv ]; then
    printf '\n%s\n' '. /etc/profile.d/ascend-dev.sh' >>/etc/zsh/zshenv
fi
