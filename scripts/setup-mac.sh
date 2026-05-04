#!/usr/bin/env bash
# TuriX-CUA Mac Intel one-shot setup.
#
# Usage:    bash setup-mac.sh
# Idempotent: safe to re-run. Only unpacks env on first run.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$DIR/.turix_env"
ENV_TARBALL="$DIR/turix_env-mac-intel.tar.gz"
CONFIG="$DIR/examples/config.json"
CONFIG_TEMPLATE="$DIR/examples/config.example.json"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
warn() { printf "\033[33m%s\033[0m\n" "$*"; }
err()  { printf "\033[31m%s\033[0m\n" "$*" >&2; }

bold "==> TuriX-CUA Mac Intel setup"
echo "    bundle dir: $DIR"
echo

# 1. Arch sanity check
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)
    echo "✓ Intel x86_64 detected"
    ;;
  arm64)
    warn "⚠ Apple Silicon detected. This bundle is built for Intel."
    warn "  Either rebuild for arm64, or run via Rosetta:"
    warn "    arch -x86_64 bash setup-mac.sh"
    exit 1
    ;;
  *)
    err "✗ Unsupported arch: $ARCH"
    exit 1
    ;;
esac

# 2. macOS version
OS_MAJOR=$(sw_vers -productVersion | cut -d. -f1)
if [ "$OS_MAJOR" -lt 13 ]; then
  warn "⚠ macOS $OS_MAJOR detected. TuriX is tested on macOS 13+."
fi

# 3. Unpack env (one-time)
if [ ! -d "$ENV_DIR" ] || [ ! -x "$ENV_DIR/bin/python" ]; then
  if [ ! -f "$ENV_TARBALL" ]; then
    err "✗ Missing env tarball: $ENV_TARBALL"
    exit 1
  fi
  bold "==> Unpacking conda env (first run, ~600 MB)..."
  rm -rf "$ENV_DIR"
  mkdir -p "$ENV_DIR"
  tar xzf "$ENV_TARBALL" -C "$ENV_DIR"
  echo "==> Fixing env paths..."
  "$ENV_DIR/bin/conda-unpack"
  echo "✓ Env ready at $ENV_DIR"
else
  echo "✓ Env already unpacked: $ENV_DIR"
fi

# 4. Bootstrap config if missing
if [ ! -f "$CONFIG" ]; then
  if [ ! -f "$CONFIG_TEMPLATE" ]; then
    err "✗ Missing $CONFIG_TEMPLATE — bundle is incomplete."
    exit 1
  fi
  cp "$CONFIG_TEMPLATE" "$CONFIG"
  bold "==> Created examples/config.json from template"
fi

# 5. API key check
if grep -q "YOUR_DASHSCOPE_API_KEY" "$CONFIG"; then
  warn "⚠ examples/config.json still has the placeholder API key."
  warn "  Edit and fill in your DashScope (or compatible) key, then re-run."
  if command -v open >/dev/null 2>&1; then
    open -e "$CONFIG" || true
  fi
  exit 0
fi

# 6. Permission reminder + open System Settings
bold "==> macOS permissions required"
cat <<'EOF'
   The agent needs:
     • Privacy & Security → Accessibility       (to send mouse/keyboard events)
     • Privacy & Security → Screen Recording    (to capture the screen)

   Add Terminal (or your IDE) to BOTH lists.
   Opening System Settings panes...
EOF
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"   2>/dev/null || true
sleep 1
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"   2>/dev/null || true

echo
bold "Press Enter to launch the agent (Cmd+Shift+2 to force-stop at runtime)."
read -r _

# 7. Launch
cd "$DIR"
exec "$ENV_DIR/bin/python" examples/main.py
