#!/usr/bin/env bash
# sysop installer — works on Raspbian, Ubuntu, Fedora (and most Linux).
# Usage: bash install.sh

set -euo pipefail

REPO_URL="https://github.com/Broikos-Nikos/sysop.git"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.local/share/sysop"
BIN_DIR="${HOME}/.local/bin"
BIN_LINK="${BIN_DIR}/sysop"

echo ""
echo "  sysop installer"
echo "  ───────────────"

# ── Check python3 ─────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo ""
    echo "  ERROR: python3 not found."
    echo "  Install it first:"
    echo "    Debian/Ubuntu/Raspbian : sudo apt install -y python3"
    echo "    Fedora                 : sudo dnf install -y python3"
    echo "    Arch                   : sudo pacman -S python"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))")
echo "  Python $PY_VER found."

# ── Install or update ─────────────────────────────────────────────────────────
if [ "${SCRIPT_DIR}" = "${INSTALL_DIR}" ]; then
    echo "  Already running from install directory — nothing to copy."
elif [ -f "${SCRIPT_DIR}/sysop.py" ]; then
    # Running from a local source directory — copy files directly.
    echo "  Copying from ${SCRIPT_DIR} to ${INSTALL_DIR}..."
    mkdir -p "${INSTALL_DIR}"
    cp -r "${SCRIPT_DIR}/." "${INSTALL_DIR}/"
elif [ -d "${INSTALL_DIR}/.git" ]; then
    echo "  Updating existing install in ${INSTALL_DIR}..."
    git -C "${INSTALL_DIR}" pull --ff-only
else
    echo "  Installing from ${REPO_URL}..."
    git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

# ── Create launcher ───────────────────────────────────────────────────────────
mkdir -p "${BIN_DIR}"
cat > "${BIN_LINK}" << EOF
#!/bin/bash
exec python3 "${INSTALL_DIR}/sysop.py" "\$@"
EOF
chmod +x "${BIN_LINK}"

# ── PATH check ────────────────────────────────────────────────────────────────
if ! echo "${PATH}" | tr ':' '\n' | grep -qx "${BIN_DIR}"; then
    # Try to detect which shell rc file to update.
    SHELL_RC=""
    if [ -n "${BASH_VERSION:-}" ] && [ -f "${HOME}/.bashrc" ]; then
        SHELL_RC="${HOME}/.bashrc"
    elif [ -n "${ZSH_VERSION:-}" ] && [ -f "${HOME}/.zshrc" ]; then
        SHELL_RC="${HOME}/.zshrc"
    elif [ -f "${HOME}/.profile" ]; then
        SHELL_RC="${HOME}/.profile"
    fi

    if [ -n "${SHELL_RC}" ]; then
        echo "" >> "${SHELL_RC}"
        echo '# sysop' >> "${SHELL_RC}"
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "${SHELL_RC}"
        echo "  Added ~/.local/bin to PATH in ${SHELL_RC}."
        echo "  Restart your shell or run: source ${SHELL_RC}"
    else
        echo "  WARNING: ${BIN_DIR} is not in PATH."
        echo "  Add this to your shell config:"
        echo '    export PATH="$HOME/.local/bin:$PATH"'
    fi
fi

echo ""
echo "  Done! Run 'sysop' to start (or: python3 ${INSTALL_DIR}/sysop.py)"
echo ""
