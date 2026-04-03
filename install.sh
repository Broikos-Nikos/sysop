#!/usr/bin/env bash
# sysop installer/updater — works on Raspbian, Ubuntu, Fedora (and most Linux).
# Usage: bash <(curl -fsSL https://raw.githubusercontent.com/Broikos-Nikos/sysop/main/install.sh)

set -euo pipefail

TARBALL_URL="https://github.com/Broikos-Nikos/sysop/archive/refs/heads/main.tar.gz"
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

# ── Download and extract ───────────────────────────────────────────────────────
echo "  Downloading..."

TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT

if command -v curl &>/dev/null; then
    curl -fsSL "${TARBALL_URL}" -o "${TMP}/sysop.tar.gz"
elif command -v wget &>/dev/null; then
    wget -qO "${TMP}/sysop.tar.gz" "${TARBALL_URL}"
else
    echo "  ERROR: curl or wget is required."
    exit 1
fi

tar -xzf "${TMP}/sysop.tar.gz" -C "${TMP}"
EXTRACTED=$(find "${TMP}" -maxdepth 1 -mindepth 1 -type d | head -1)

rm -rf "${INSTALL_DIR}"
mkdir -p "$(dirname "${INSTALL_DIR}")"
mv "${EXTRACTED}" "${INSTALL_DIR}"

echo "  Installed to ${INSTALL_DIR}."

# ── Create launcher ───────────────────────────────────────────────────────────
mkdir -p "${BIN_DIR}"
cat > "${BIN_LINK}" << EOF
#!/bin/bash
exec python3 "${INSTALL_DIR}/sysop.py" "\$@"
EOF
chmod +x "${BIN_LINK}"

# ── PATH check ────────────────────────────────────────────────────────────────
if ! echo "${PATH}" | tr ':' '\n' | grep -qx "${BIN_DIR}"; then
    SHELL_RC=""
    if [ -f "${HOME}/.bashrc" ]; then
        SHELL_RC="${HOME}/.bashrc"
    elif [ -f "${HOME}/.zshrc" ]; then
        SHELL_RC="${HOME}/.zshrc"
    elif [ -f "${HOME}/.profile" ]; then
        SHELL_RC="${HOME}/.profile"
    fi

    if [ -n "${SHELL_RC}" ]; then
        if ! grep -q '.local/bin' "${SHELL_RC}"; then
            echo '' >> "${SHELL_RC}"
            echo 'export PATH="$HOME/.local/bin:$PATH"  # sysop' >> "${SHELL_RC}"
        fi
        echo "  Added ~/.local/bin to PATH in ${SHELL_RC}."
        echo "  Run: source ${SHELL_RC}"
    else
        echo "  WARNING: ${BIN_DIR} is not in PATH."
        echo "  Add to your shell config: export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
fi

echo ""
echo "  Done! Run: sysop"
echo ""
