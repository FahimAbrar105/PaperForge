#!/usr/bin/env bash
# =============================================================================
#  Paper Forge launcher for macOS and Linux.
#
#    ./run.sh           local mode if Python 3.11+ is installed (lightest: a private
#                       virtual environment and Tectonic inside ./runtime), otherwise
#                       Docker if it is installed.
#    ./run.sh local     force local mode.
#    ./run.sh docker    force Docker mode.
#    ./run.sh reset     delete ./runtime (private Python packages, Tectonic, caches).
#    ./run.sh zip       make paper-forge.zip next to this folder to share: no runtime,
#                       settings, API key or jobs.
#
#  First start needs internet; later starts work offline.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"
PF_HOME="$(pwd)"
RUNTIME="$PF_HOME/runtime"
TECT_VER="0.15.0"
PORT="${PAPERFORGE_PORT:-8000}"
URL="http://localhost:$PORT"

open_browser() {
  local opener=xdg-open
  [ "$(uname -s)" = "Darwin" ] && opener=open
  (sleep 4; "$opener" "$URL" >/dev/null 2>&1 || true) &
}

find_python() {
  for cand in python3.13 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        echo "$cand"; return 0
      fi
    fi
  done
  return 1
}

run_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] Docker is not installed. Install Docker Desktop (macOS) or Docker Engine (Linux),"
    echo "        or install Python 3.11+ and run ./run.sh local"; exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "[ERROR] Docker is installed but not running. Start Docker and try again."; exit 1
  fi
  echo "Starting Paper Forge with Docker (the first build takes a few minutes)..."
  docker compose up -d --build
  echo
  echo "Paper Forge is running at $URL"
  echo "Stop it with:  docker compose down"
  open_browser
}

tectonic_asset() {
  local os arch
  os="$(uname -s)"; arch="$(uname -m)"
  case "$os-$arch" in
    Linux-x86_64)            echo "tectonic-$TECT_VER-x86_64-unknown-linux-musl.tar.gz" ;;
    Linux-aarch64|Linux-arm64) echo "tectonic-$TECT_VER-aarch64-unknown-linux-musl.tar.gz" ;;
    Darwin-x86_64)           echo "tectonic-$TECT_VER-x86_64-apple-darwin.tar.gz" ;;
    Darwin-arm64)            echo "tectonic-$TECT_VER-aarch64-apple-darwin.tar.gz" ;;
    *) return 1 ;;
  esac
}

run_local() {
  local py
  py="$(find_python)" || { echo "[ERROR] Python 3.11 or newer was not found. Install it, or use ./run.sh docker"; exit 1; }
  mkdir -p "$RUNTIME/tmp"
  export TMPDIR="$RUNTIME/tmp" PIP_CACHE_DIR="$RUNTIME/pip-cache" PIP_DISABLE_PIP_VERSION_CHECK=1
  export TECTONIC_CACHE_DIR="$RUNTIME/tectonic-cache" PAPERFORGE_TECTONIC="$RUNTIME/tectonic/tectonic"
  export PAPERFORGE_TMP="$RUNTIME/tmp" PAPERFORGE_PORT="$PORT" PYTHONDONTWRITEBYTECODE=1

  echo
  echo " Paper Forge - local mode (files stay in $PF_HOME)"
  echo
  if [ ! -x "$RUNTIME/venv/bin/python" ]; then
    echo "[1/3] Creating a private Python environment..."
    "$py" -m venv "$RUNTIME/venv" || {
      rm -rf "$RUNTIME/venv"
      echo "[ERROR] Could not create a Python virtual environment."
      echo "        On Debian/Ubuntu install the venv module first: sudo apt install python3-venv"
      exit 1
    }
  fi
  local vpy="$RUNTIME/venv/bin/python"
  if ! cmp -s "$PF_HOME/requirements.txt" "$RUNTIME/requirements.installed" 2>/dev/null; then
    echo "[2/3] Installing Python packages (about 30 MB, first start only)..."
    "$vpy" -m pip install --no-cache-dir --only-binary :all: --find-links "$PF_HOME/vendor/wheels" -r "$PF_HOME/requirements.txt"
    cp "$PF_HOME/requirements.txt" "$RUNTIME/requirements.installed"
  fi
  if [ ! -x "$RUNTIME/tectonic/tectonic" ]; then
    if command -v tectonic >/dev/null 2>&1; then
      export PAPERFORGE_TECTONIC="$(command -v tectonic)"
    else
      local asset
      asset="$(tectonic_asset)" || { echo "[ERROR] No Tectonic build for $(uname -s) $(uname -m). Install Tectonic yourself or use Docker."; exit 1; }
      echo "[3/3] Downloading the Tectonic LaTeX compiler $TECT_VER..."
      mkdir -p "$RUNTIME/tectonic"
      curl -L --fail --retry 3 -o "$RUNTIME/tmp/tectonic.tar.gz" \
        "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40$TECT_VER/$asset"
      tar -xzf "$RUNTIME/tmp/tectonic.tar.gz" -C "$RUNTIME/tectonic"
      rm -f "$RUNTIME/tmp/tectonic.tar.gz"
      chmod +x "$RUNTIME/tectonic/tectonic"
    fi
  fi
  # warmup.ok lists the venues whose LaTeX packages are cached, so this is quick after the first start.
  if ! "$vpy" "$PF_HOME/scripts/warmup.py" "$RUNTIME/warmup.ok"; then
    echo "[WARNING] Warm-up did not finish; packages will download on first use."
  fi
  echo
  echo "============================================================"
  echo "  Paper Forge is starting at  $URL"
  echo "  Press Ctrl+C to stop."
  echo "============================================================"
  open_browser
  exec "$vpy" -m app.main
}

case "${1:-auto}" in
  docker) run_docker ;;
  local)  run_local ;;
  reset)  rm -rf "$RUNTIME"; echo "Removed $RUNTIME. Your jobs in ./output are kept." ;;
  zip)    "$(find_python)" scripts/make_zip.py ;;
  auto)
    if find_python >/dev/null; then run_local
    elif command -v docker >/dev/null 2>&1; then run_docker
    else
      echo "[ERROR] Paper Forge needs either Python 3.11+ or Docker. See SETUP.md."; exit 1
    fi ;;
  *) echo "Usage: ./run.sh [local|docker|reset|zip]"; exit 1 ;;
esac
