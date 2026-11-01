#!/bin/bash
# Developer shell setup: zsh, oh-my-zsh, neovim (NvChad), nvm, fzf, eza, starship, sheldon, zoxide.
# Run as the final image user. Root commands execute directly or through passwordless sudo.
# Option: --enabled (default: false).
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: devshell.sh [--enabled <boolean>]

Options:
  --enabled <value>  Install the developer shell: true/false, 1/0, yes/no,
                     on/off, or enabled/disabled (default: false)
  -h, --help         Show this help
EOF
}

ENABLED_VAL="false"
if ! PARSED=$(getopt -o h -l help,enabled: -n "$(basename "$0")" -- "$@"); then
    usage >&2
    exit 64
fi
eval set -- "$PARSED"
while true; do
    case "$1" in
        --enabled)
            ENABLED_VAL="$2"
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
    echo "devshell.sh: unexpected positional arguments: $*" >&2
    usage >&2
    exit 64
fi
case "${ENABLED_VAL,,}" in
    1 | true | yes | on | enabled) ;;
    0 | false | no | off | disabled)
        exit 0
        ;;
    *)
        echo "devshell.sh: unsupported --enabled value '${ENABLED_VAL}'" >&2
        exit 64
        ;;
esac

# Docker USER does not update HOME inherited from the base image.
CURRENT_USER="$(id -un)"
USER_HOME="$(getent passwd "${CURRENT_USER}" | cut -d: -f6)"
if [ -z "${USER_HOME}" ]; then
    echo "devshell.sh: cannot resolve home directory for '${CURRENT_USER}'" >&2
    exit 1
fi
export HOME="${USER_HOME}"

run_as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo -n "$@"
    fi
}

# ─── Init Apt ─────────────────────────────────────────────────────────────────

run_as_root apt-get update

# ── zsh ───────────────────────────────────────────────────────────────────────

run_as_root apt-get -y install zsh
run_as_root chsh -s /bin/zsh "$(whoami)"

# ── oh-my-zsh ────────────────────────────────────────────────────────────────

sh -c "$(wget https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh -O -)" "" --unattended

git clone https://github.com/zsh-users/zsh-completions \
    "${ZSH_CUSTOM:-${ZSH:-$HOME/.oh-my-zsh}/custom}/plugins/zsh-completions"
git clone https://github.com/zsh-users/zsh-autosuggestions \
    "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/zsh-autosuggestions"
git clone https://github.com/zsh-users/zsh-syntax-highlighting.git \
    "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting"

sed -i 's/ZSH_THEME="robbyrussell"/ZSH_THEME="ys"/g' "${HOME}/.zshrc"
sed -i 's/plugins=(git)/plugins=(git zsh-syntax-highlighting zsh-autosuggestions zsh-completions)/g' "${HOME}/.zshrc"

# ── vimrc ────────────────────────────────────────────────────────────────────

git clone --depth=1 https://github.com/amix/vimrc.git "${HOME}/.vim_runtime"
sh "${HOME}/.vim_runtime/install_awesome_vimrc.sh"
echo 'set mouse-=a' >>"${HOME}/.vim_runtime/my_configs.vim"

# ── misc shell config ─────────────────────────────────────────────────────────

# zsh configuration
cat >>"${HOME}/.zshrc" <<'ZSH_EOF'

setopt no_nomatch # disable * match

export PATH="$PATH:${HOME}/.local/bin"

export TERM=xterm-256color
export COLORTERM=truecolor

# Load uv completions only in images that install uv separately.
if command -v uv >/dev/null 2>&1; then
    eval "$(uv generate-shell-completion zsh)"
fi
if command -v uvx >/dev/null 2>&1; then
    eval "$(uvx --generate-shell-completion zsh)"
fi

ZSH_EOF

# bash color prompt
sed -i 's/#force_color_prompt=yes/force_color_prompt=yes/g' "${HOME}/.bashrc"

# vscode-server
mkdir -p "${HOME}/.vscode-server/data/Machine"

# tmux
cat >>"${HOME}/.tmux.conf" <<'TMUX_EOF'
# ─── Vim Style ────────────────────────────────────────────────────────────────

# Vim style key bindings for tmux
set -g mode-keys vi
set -g status-keys vi

# copy mode
bind-key -T copy-mode-vi v send-keys -X begin-selection
bind-key -T copy-mode-vi y send-keys -X copy-selection-and-cancel

# Pane navigation
bind h select-pane -L
bind j select-pane -D
bind k select-pane -U
bind l select-pane -R

# Pane resize
bind -r H resize-pane -L 5
bind -r J resize-pane -D 5
bind -r K resize-pane -U 5
bind -r L resize-pane -R 5

# ─── History ──────────────────────────────────────────────────────────────────

set -g history-limit 1000000

# ─── Clipboard over SSH ───────────────────────────────────────────────────────
set -g set-clipboard external

# uncomment if tmux info window status shows Ms missing
# set -as terminal-features ',xterm-256color:clipboard'

TMUX_EOF

# ── nvm + Node.js LTS ────────────────────────────────────────────────────────

export PROFILE=$HOME/.zshrc
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.4/install.sh | bash

export NVM_DIR="$HOME/.nvm"
# nvm.sh uses unset variables internally; disable -u for the duration
set +u
# shellcheck disable=SC1091
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
nvm install --lts
nvm use --lts
npm install -g pnpm
set -u

# ── neovim (NvChad) ──────────────────────────────────────────────────────────

cd /tmp
ARCH=$(uname -m)
case $ARCH in
    x86_64) NVIM_ARCH="x86_64" ;;
    aarch64) NVIM_ARCH="arm64" ;;
    *) echo "Unsupported architecture: $ARCH" && exit 1 ;;
esac

curl -LO "https://github.com/neovim/neovim/releases/latest/download/nvim-linux-${NVIM_ARCH}.tar.gz"
tar -xf "nvim-linux-${NVIM_ARCH}.tar.gz"
rm "nvim-linux-${NVIM_ARCH}.tar.gz"
run_as_root rsync -av --ignore-existing "nvim-linux-${NVIM_ARCH}/" /usr/local
rm -rf "nvim-linux-${NVIM_ARCH}"

git clone https://github.com/NvChad/starter "${HOME}/.config/nvim" --depth 1

# disable mouse support
cat >>"${HOME}/.config/nvim/init.lua" <<'MOUSE_EOF'

-- disable mouse support
vim.opt.mouse = ""

MOUSE_EOF

# add custom plugins
cat >"${HOME}/.config/nvim/lua/plugins/custom.lua" <<'LUA'
return {
  {
    "ibhagwan/fzf-lua",
    dependencies = { "nvim-tree/nvim-web-devicons" },
    opts = {},
  },
  {
    "fei6409/log-highlight.nvim",
    opts = {},
  },
}
LUA

# Use the system-installed ty executable directly so Python LSP support remains
# available when the running container has no network access.
cat >"${HOME}/.config/nvim/lua/configs/lspconfig.lua" <<'LUA'
require("nvchad.configs.lspconfig").defaults()

vim.lsp.config("ty", {
  cmd = { "ty", "server" },
  filetypes = { "python" },
  root_markers = {
    "ty.toml",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    ".git",
  },
})

vim.lsp.enable({ "html", "cssls", "ty" })
LUA

nvim --headless "+Lazy! sync" +qa
nvim --headless "+Lazy load nvim-treesitter" "+TSInstallSync! lua vim vimdoc c cpp python javascript" +qa

# Mason LSP servers — MasonInstall is async; poll until all packages are installed
cat >/tmp/mason_install.lua <<'LUA'
local packages = {"lua-language-server", "stylua", "pyright", "clangd"}
vim.defer_fn(function()
    local registry = require("mason-registry")
    for _, name in ipairs(packages) do
        local ok, p = pcall(registry.get_package, name)
        if ok and not p:is_installed() then p:install() end
    end
    vim.wait(120000, function()
        for _, name in ipairs(packages) do
            local ok, p = pcall(registry.get_package, name)
            if not ok or not p:is_installed() then return false end
        end
        return true
    end, 2000)
    vim.cmd("qa!")
end, 5000)
LUA
nvim --headless -c "luafile /tmp/mason_install.lua"
rm /tmp/mason_install.lua

# ─── Fzf ──────────────────────────────────────────────────────────────────────

git clone --depth 1 https://github.com/junegunn/fzf.git "${HOME}/.fzf"
"${HOME}/.fzf/install" --all
cat >>"${HOME}/.zshrc" <<'FZF_EOF'
export FZF_CTRL_T_OPTS="
  --walker-skip .git,node_modules,target
  --preview 'bat -n --color=always {}'
  --bind 'ctrl-/:change-preview-window(down|hidden|)'"

FZF_EOF

# ─── Eza ──────────────────────────────────────────────────────────────────────

ARCH=$(uname -m)
case $ARCH in
    x86_64) EZA_ARCH="x86_64-unknown-linux-gnu" ;;
    aarch64) EZA_ARCH="aarch64-unknown-linux-gnu" ;;
    *) echo "Unsupported architecture: $ARCH" && exit 1 ;;
esac
wget -c "https://github.com/eza-community/eza/releases/latest/download/eza_${EZA_ARCH}.tar.gz" -O - | tar xz
run_as_root chmod +x eza
run_as_root chown root:root eza
run_as_root mv eza /usr/local/bin/eza

cat >>"${HOME}/.zshrc" <<'EZA_EOF'
alias l="eza -lah --color=auto --icons=auto"

EZA_EOF

# ─── Starship ─────────────────────────────────────────────────────────────────

curl -sS https://starship.rs/install.sh | POSIXLY_CORRECT=1 bash -s -- -y
starship preset catppuccin-powerline -o "${HOME}/.config/starship.toml"

# ─── Sheldon ──────────────────────────────────────────────────────────────────

curl --proto '=https' -fLsS https://rossmacarthur.github.io/install/crate.sh |
    bash -s -- --repo rossmacarthur/sheldon --to "${HOME}/.local/bin"

echo y | "${HOME}/.local/bin/sheldon" init --shell zsh

"${HOME}/.local/bin/sheldon" add omz-lib \
    --github ohmyzsh/ohmyzsh \
    --dir lib \
    --use history.zsh key-bindings.zsh clipboard.zsh completion.zsh directories.zsh git.zsh
"${HOME}/.local/bin/sheldon" add omz-git \
    --github ohmyzsh/ohmyzsh \
    --dir plugins/git
"${HOME}/.local/bin/sheldon" add zsh-autosuggestions \
    --github zsh-users/zsh-autosuggestions
"${HOME}/.local/bin/sheldon" add zsh-completions \
    --github zsh-users/zsh-completions
"${HOME}/.local/bin/sheldon" add zsh-syntax-highlighting \
    --github zsh-users/zsh-syntax-highlighting

"${HOME}/.local/bin/sheldon" lock

# ─── Zoxide ───────────────────────────────────────────────────────────────────

curl -sSfL https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | sh

cat >>"${HOME}/.zshrc" <<'ZOXIDE_EOF'
# zoxide initialization
eval "$(zoxide init zsh)"

ZOXIDE_EOF

# ─── Witr ─────────────────────────────────────────────────────────────────────

curl -fsSL https://raw.githubusercontent.com/pranshuparmar/witr/main/install.sh | bash

# ─── Apt Cache Clean ──────────────────────────────────────────────────────────

run_as_root rm -rf /var/lib/apt/lists/*
