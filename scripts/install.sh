#!/usr/bin/env bash
# install.sh - install VortexVPN on a Linux server.
#
# Tested on: Debian 11/12, Ubuntu 22.04/24.04, Fedora 38/39, Rocky 9.
# Idempotent: re-running upgrades in place.

set -e

# -----------------------------------------------------------------------------
# Detect distro
# -----------------------------------------------------------------------------
if [ -f /etc/debian_version ]; then
    DISTRO="debian"
elif [ -f /etc/fedora-release ]; then
    DISTRO="fedora"
elif [ -f /etc/rocky-release ] || [ -f /etc/almalinux-release ]; then
    DISTRO="rhel"
else
    echo "[!] Unsupported distro. Please install dependencies manually:" >&2
    echo "    python3 >= 3.10, python3-pip, python3-venv, openjdk-17-jdk," >&2
    echo "    build-essential, python3-dev, pybind11-dev, libssl-dev, git" >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# System packages
# -----------------------------------------------------------------------------
install_pkgs() {
    case "$DISTRO" in
        debian)
            apt-get update -y
            apt-get install -y python3 python3-pip python3-venv \
                openjdk-17-jdk-headless build-essential python3-dev \
                pybind11-dev libssl-dev git curl socat
            ;;
        fedora)
            dnf install -y python3 python3-pip python3-devel java-17-openjdk-headless \
                gcc-c++ pybind11-devel openssl-devel git curl socat
            ;;
        rhel)
            dnf install -y python3 python3-pip python3-devel java-17-openjdk-headless \
                gcc-c++ openssl-devel git curl socat
            pip3 install --user pybind11
            ;;
    esac
}

echo "[1/6] Installing system packages ($DISTRO)..."
install_pkgs

# -----------------------------------------------------------------------------
# Project layout
# -----------------------------------------------------------------------------
HERE="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="${VORTEX_HOME:-/opt/vortexvpn}"
VENV_DIR="$INSTALL_DIR/venv"
LOG_DIR="/var/log/vortexvpn"
RUN_DIR="/var/run/vortexvpn"
CONF_DIR="/etc/vortexvpn"

echo "[2/6] Creating directories..."
sudo mkdir -p "$INSTALL_DIR" "$LOG_DIR" "$RUN_DIR" "$CONF_DIR" "$CONF_DIR/certs"
sudo chown -R "$USER":"$USER" "$INSTALL_DIR" "$LOG_DIR" "$RUN_DIR" "$CONF_DIR"

# Copy source
echo "[3/6] Installing source to $INSTALL_DIR..."
rsync -a --delete --exclude='.git' --exclude='venv' --exclude='__pycache__' \
    "$HERE/" "$INSTALL_DIR/"

# -----------------------------------------------------------------------------
# Python venv
# -----------------------------------------------------------------------------
echo "[4/6] Creating Python venv..."
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel setuptools
"$VENV_DIR/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt"

# -----------------------------------------------------------------------------
# C++ accelerator (optional but recommended)
# -----------------------------------------------------------------------------
echo "[5/6] Building C++ crypto accelerator..."
if command -v pybind11-config >/dev/null 2>&1; then
    ( cd "$INSTALL_DIR/cpp_module" && make test && make install ) || {
        echo "[!] C++ module build failed; Python will fall back to cryptography lib."
    }
else
    echo "[!] pybind11 not found; skipping C++ accelerator."
fi

# -----------------------------------------------------------------------------
# Java monitor
# -----------------------------------------------------------------------------
echo "[6/6] Compiling Java monitor..."
( cd "$INSTALL_DIR/java_monitor" && bash run.sh build ) || true

# -----------------------------------------------------------------------------
# Default config & admin user
# -----------------------------------------------------------------------------
if [ ! -f "$CONF_DIR/config.toml" ]; then
    cp "$INSTALL_DIR/configs/config.toml.example" "$CONF_DIR/config.toml"
    echo "[+] wrote default config -> $CONF_DIR/config.toml"
fi

echo ""
echo "=============================================================="
echo " VortexVPN installed to $INSTALL_DIR"
echo "=============================================================="
echo ""
echo "Next steps:"
echo "  1. Edit config:   sudo \$EDITOR $CONF_DIR/config.toml"
echo "  2. Create admin:  $INSTALL_DIR/venv/bin/python -m vortexvpn.bootstrap"
echo "  3. Start server:  $INSTALL_DIR/scripts/manage.sh start"
echo "  4. Open panel:    http://localhost:8080"
echo ""
echo "Logs:  $LOG_DIR/vortexvpn.log"
echo "Monitor: $INSTALL_DIR/java_monitor/run.sh start"
