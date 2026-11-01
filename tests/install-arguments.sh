#!/bin/bash
# Verify the non-mutating getopt interface of parameterized install scripts.
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

scripts=(
    "scripts/dev/cmake.sh|--version"
    "scripts/libraries/cpptrace.sh|--version"
    "scripts/dev/devshell.sh|--enabled"
    "scripts/system/finalize-mirror.sh|--mirror"
    "scripts/libraries/iceoryx.sh|--version"
    "scripts/libraries/libdatachannel.sh|--version"
    "scripts/integrations/llama-cpp.sh|--version"
    "scripts/dev/precommit.sh|--config"
    "scripts/integrations/ros2.sh|--distro"
    "scripts/libraries/rpclib.sh|--version"
    "scripts/system/ssh.sh|--default-user"
    "scripts/system/system.sh|--timezone"
    "scripts/system/user.sh|--username"
    "scripts/system/workspace.sh|--path"
    "scripts/python/python-install.sh|--mode"
    "scripts/python/cuda-pip-packages.sh|--requirements"
    "scripts/python/ascend-pip-packages.sh|--requirements"
)

no_argument_scripts=(
    "scripts/dev/dev-tools.sh"
    "scripts/python/cuda-pip-packages.sh"
    "scripts/python/python-install.sh"
    "scripts/integrations/ascend-environment.sh"
    "assets/ascend-pip-check.sh"
)

expect_usage_error() {
    local script="$1"
    shift
    local status

    set +e
    bash "${script}" "$@" >/dev/null 2>&1
    status=$?
    set -e
    if [ "${status}" -ne 64 ]; then
        echo "expected exit 64 from ${script} $*, got ${status}" >&2
        exit 1
    fi
}

for specification in "${scripts[@]}"; do
    script="${REPOSITORY_ROOT}/${specification%%|*}"
    required_option="${specification##*|}"
    bash "${script}" --help >/dev/null
    expect_usage_error "${script}" --unknown-option
    expect_usage_error "${script}" "${required_option}"
    expect_usage_error "${script}" unexpected-positional
done

# Reject the removed account selector and exercise the remaining mode option.
ssh_script="${REPOSITORY_ROOT}/scripts/system/ssh.sh"
expect_usage_error "${ssh_script}" --login-user default
expect_usage_error "${ssh_script}" --mode

# New architecture support must not relax configuration validation before installation begins.
expect_usage_error "${REPOSITORY_ROOT}/scripts/dev/cmake.sh" --sha256
expect_usage_error "${REPOSITORY_ROOT}/scripts/dev/cmake.sh" --sha256 invalid
expect_usage_error "${REPOSITORY_ROOT}/scripts/dev/cmake.sh" --sha256 ''
expect_usage_error "${REPOSITORY_ROOT}/scripts/python/python-install.sh" --mode unsupported
for script_name in cuda-pip-packages.sh ascend-pip-packages.sh; do
    script="${REPOSITORY_ROOT}/scripts/python/${script_name}"
    expect_usage_error "${script}"
    expect_usage_error "${script}" --requirements ''
    expect_usage_error "${script}" --requirements "${REPOSITORY_ROOT}/AGENTS.md/missing.txt"
    expect_usage_error "${script}" --requirements "${REPOSITORY_ROOT}"
    expect_usage_error "${script}" --profile ascend
    expect_usage_error "${script}" --preserve-existing
done

# YAML booleans are stringified by the Python planner, so the script owns normalization.
devshell_script="${REPOSITORY_ROOT}/scripts/dev/devshell.sh"
for disabled_value in false False FALSE 0 no NO off disabled; do
    bash "${devshell_script}" --enabled "${disabled_value}"
done
expect_usage_error "${devshell_script}" --enabled sometimes

# Upstream is a non-mutating success path; mirror selection owns value validation.
mirror_script="${REPOSITORY_ROOT}/scripts/system/finalize-mirror.sh"
bash "${mirror_script}" --mirror upstream >/dev/null
expect_usage_error "${mirror_script}" --mirror unsupported

# Exercise every value-taking option and format guard added to the llama.cpp capability.
llama_cpp_script="${REPOSITORY_ROOT}/scripts/integrations/llama-cpp.sh"
expect_usage_error "${llama_cpp_script}" --cuda-version
expect_usage_error "${llama_cpp_script}" --version latest
expect_usage_error "${llama_cpp_script}" --cuda-version 12

# Selecting root must be a non-mutating success path owned by the user capability.
user_script="${REPOSITORY_ROOT}/scripts/system/user.sh"
bash "${user_script}" --username root --uid 1000 --gid 1000
bash "${user_script}" --username root --groups ""
expect_usage_error "${user_script}" --groups
expect_usage_error "${user_script}" --username root --groups video
expect_usage_error "${user_script}" --username root --groups video,,render

# Reject paths that could assign ownership to the filesystem root or escape lexically.
workspace_script="${REPOSITORY_ROOT}/scripts/system/workspace.sh"
expect_usage_error "${workspace_script}" --path / --owner root
expect_usage_error "${workspace_script}" --path /work/../other --owner root
expect_usage_error "${workspace_script}" --path relative --owner root
expect_usage_error "${workspace_script}" --path /work --owner "Invalid Owner"
expect_usage_error "${workspace_script}" --path /work --owner user-that-does-not-exist

for script_name in "${no_argument_scripts[@]}"; do
    script="${REPOSITORY_ROOT}/${script_name}"
    bash "${script}" --help >/dev/null
    expect_usage_error "${script}" --unknown-option
    expect_usage_error "${script}" unexpected-positional
done
