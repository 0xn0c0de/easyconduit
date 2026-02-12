#!/usr/bin/env bash
#
# EasyConduit installer
# One-command setup for Conduit CLI + Telegram dashboard bot.
#
# Usage (as root on the VPS):
#   curl -sSL https://raw.githubusercontent.com/0xn0c0de/easyconduit/main/install.sh | bash
#

set -euo pipefail

EASY_PREFIX="/opt/easyconduit"
BIN_DIR="$EASY_PREFIX/bin"
DATA_DIR="$EASY_PREFIX/data"
STATE_DIR="$EASY_PREFIX/state"
BOT_DIR="$EASY_PREFIX/bot"

CONDUIT_USER="conduit"
CONDUIT_SERVICE="conduit.service"
BOT_SERVICE="easyconduit-bot.service"

RESET=$'\033[0m'
WHITE=$'\033[38;2;255;255;255m'

banner_small_iran_flag() {
    # Simplified Iranian flag banner.
    # Top band (▓ only): green 124A3F
    # Middle band (contains ▒): ▒ white FFFFFF, ▓/█ emblem gold FFBB26
    # Bottom band (█ only): red AB0104
    local line ch r g b hex in_white_band
    while IFS= read -r line; do
        in_white_band=0
        [[ "$line" == *▒* ]] && in_white_band=1
        local out=""
        local i
        for ((i = 0; i < ${#line}; i++)); do
            ch="${line:$i:1}"
            if (( in_white_band )); then
                case "$ch" in
                    '▓'|'█') hex="FFBB26" ;;  # gold emblem
                    '▒')     hex="FFFFFF" ;;  # white
                    *)       hex="FFFFFF" ;;
                esac
            else
                case "$ch" in
                    '▓') hex="124A3F" ;;  # green
                    '▒') hex="FFFFFF" ;;
                    '█') hex="AB0104" ;;  # red
                    *)   hex="FFFFFF" ;;
                esac
            fi
            r=$((16#${hex:0:2}))
            g=$((16#${hex:2:2}))
            b=$((16#${hex:4:2}))
            out+=$(printf '\033[38;2;%d;%d;%dm%s' "$r" "$g" "$b" "$ch")
        done
        printf '%s%s\n' "$out" "$WHITE"
    done <<'EOF'
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▓▓▓▓▓▓▓▓▒▓▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▓▒▓▓▓▓█▓▓▓▓▓▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▓▓▓▓▓▓▓▓▓▓▓▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▓▓▓▓▓▓▓▓▓▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▓▓▓▓▓▓▓▓▓▓▓▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
████████████████████████████████████████████████████
████████████████████████████████████████████████████
████████████████████████████████████████████████████
████████████████████████████████████████████████████
████████████████████████████████████████████████████
EOF
    # After banner, reset all attributes and force white foreground for prompts.
    printf '%b' "$RESET$WHITE"
}

ensure_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "This installer must be run as root. Try: sudo bash install.sh" >&2
        exit 1
    fi
}

ensure_environment() {
    # Basic OS / systemd checks
    if [ ! -f /etc/os-release ]; then
        echo "Unsupported system: /etc/os-release not found." >&2
        exit 1
    fi
    . /etc/os-release
    case "${ID:-}" in
        ubuntu|debian)
            ;;
        *)
            echo "Warning: this script is tested on Ubuntu/Debian. Detected '$ID'." >&2
            ;;
    esac

    if ! command -v systemctl >/dev/null 2>&1; then
        echo "systemd not found. EasyConduit requires systemd to manage services." >&2
        exit 1
    fi

    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        echo "curl or wget is required. Please install one of them and re-run." >&2
        exit 1
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 is required for the Telegram bot. Please install python3 and re-run." >&2
        exit 1
    fi
}

read_tty_line() {
    # Read a single line from /dev/tty (not stdin) so that curl | bash works.
    local prompt="$1"
    local var
    printf "%s" "$prompt" > /dev/tty
    IFS= read -r var < /dev/tty || var=""
    printf '%s\n' "$var"
}

installed_already() {
    if [ -x "$BIN_DIR/conduit" ] && systemctl list-unit-files | grep -q "^$CONDUIT_SERVICE"; then
        return 0
    fi
    return 1
}

prompt_install_mode() {
    if installed_already; then
        echo
        echo "EasyConduit is already installed on this system."
        echo "[1] Reconfigure (enter Bot Token, Chat ID, and parameters again)"
        echo "[2] Exit"
        local choice
        choice=$(read_tty_line "Select an option [1/2]: ")
        case "$choice" in
            1|reconfigure|R|r) MODE="reconfigure" ;;
            *) echo "Exiting without changes."; exit 0 ;;
        esac
    else
        MODE="install"
    fi
}

prompt_parameters() {
    local token chat_id

    echo
    echo "Please enter your Telegram details. You can copy/paste from Notepad into PuTTY,"
    echo "then use Backspace to fix any mistakes before pressing Enter."
    echo

    while :; do
        token=$(read_tty_line "Enter your Telegram Bot Token: ")
        token=${token//[$'\r\n']}
        if [ -n "$token" ] && printf '%s' "$token" | grep -q ':'; then
            BOT_TOKEN="$token"
            break
        fi
        echo "Invalid token. It must be non-empty and contain a ':'. Please try again."
    done

    while :; do
        chat_id=$(read_tty_line "Enter your Chat ID (e.g. 987654321 or -1001234567890): ")
        chat_id=${chat_id//[$'\r\n']}
        if printf '%s' "$chat_id" | grep -Eq '^-?[0-9]+$'; then
            OWNER_CHAT_ID="$chat_id"
            break
        fi
        echo "Invalid Chat ID. It must be an integer. Please try again."
    done

    # Defaults: no prompt; set in conduit.env
    MAX_CLIENTS=50
    BANDWIDTH=5
}

install_conduit() {
    mkdir -p "$BIN_DIR" "$DATA_DIR" "$STATE_DIR"

    if ! id "$CONDUIT_USER" >/dev/null 2>&1; then
        useradd -r -s /usr/sbin/nologin "$CONDUIT_USER"
    fi

    # Download Conduit CLI if not present
    if [ ! -x "$BIN_DIR/conduit" ]; then
        echo "Downloading Conduit CLI..."
        local arch url tag version
        case "$(uname -m)" in
            x86_64) arch="amd64" ;;
            aarch64|arm64) arch="arm64" ;;
            *)
                echo "Unsupported architecture $(uname -m). Supported: x86_64, arm64." >&2
                exit 1
                ;;
        esac

        # For now pin to latest known version; this can be updated over time.
        version="1.5.0"
        tag="release-cli-$version"
        url="https://github.com/Psiphon-Inc/conduit/releases/download/$tag/conduit-linux-$arch"

        if command -v curl >/dev/null 2>&1; then
            curl -fL "$url" -o "$BIN_DIR/conduit"
        else
            wget -O "$BIN_DIR/conduit" "$url"
        fi
        chmod +x "$BIN_DIR/conduit"
    fi

    # Write conduit.env
    cat >"$STATE_DIR/conduit.env" <<EOF
DATA_DIR=$DATA_DIR
MAX_CLIENTS=$MAX_CLIENTS
BANDWIDTH=$BANDWIDTH
EOF

    chown -R "$CONDUIT_USER":"$CONDUIT_USER" "$DATA_DIR"

    # Wrapper script
    cat >"$BIN_DIR/run-conduit.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
STATE_DIR="/opt/easyconduit/state"
BIN_DIR="/opt/easyconduit/bin"
ENV_FILE="$STATE_DIR/conduit.env"

if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
fi

DATA_DIR="${DATA_DIR:-/opt/easyconduit/data}"
MAX_CLIENTS="${MAX_CLIENTS:-50}"
BANDWIDTH="${BANDWIDTH:-5}"

exec "$BIN_DIR/conduit" start \
  --data-dir "$DATA_DIR" \
  --max-clients "$MAX_CLIENTS" \
  --bandwidth "$BANDWIDTH" \
  --metrics-addr 127.0.0.1:9090
EOF
    chmod +x "$BIN_DIR/run-conduit.sh"

    # systemd unit
    cat >/etc/systemd/system/$CONDUIT_SERVICE <<EOF
[Unit]
Description=EasyConduit Psiphon inproxy service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CONDUIT_USER
Group=$CONDUIT_USER
ExecStart=$BIN_DIR/run-conduit.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$CONDUIT_SERVICE"
    systemctl restart "$CONDUIT_SERVICE"
}

install_bot() {
    mkdir -p "$BOT_DIR"

    # Ensure Python dependencies are available for the system python3 used by systemd.
    # Pillow is REQUIRED; matplotlib is BEST-EFFORT (we fall back to simpler charts if missing).
    if ! python3 -c "import PIL" >/dev/null 2>&1 || ! python3 -c "import matplotlib" >/dev/null 2>&1; then
        echo "Installing Python Pillow + (optional) matplotlib libraries for image generation..."

        # Try via pip first (common on many systems)
        if command -v python3 >/dev/null 2>&1 && command -v pip3 >/dev/null 2>&1; then
            python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
            python3 -m pip install pillow matplotlib >/dev/null 2>&1 || true
        fi

        # Fallback to apt-get on Debian/Ubuntu
        if command -v apt-get >/dev/null 2>&1; then
            if ! python3 -c "import PIL" >/dev/null 2>&1; then
                echo "Trying to install Pillow via apt-get (python3-pil)..."
                DEBIAN_FRONTEND=noninteractive apt-get update >/dev/null 2>&1 || true
                DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pil >/dev/null 2>&1 || true
            fi
            if ! python3 -c "import matplotlib" >/dev/null 2>&1; then
                echo "Trying to install matplotlib via apt-get (python3-matplotlib)..."
                DEBIAN_FRONTEND=noninteractive apt-get update >/dev/null 2>&1 || true
                DEBIAN_FRONTEND=noninteractive apt-get install -y python3-matplotlib >/dev/null 2>&1 || true
            fi
        fi
    fi

    # If we still don't have Pillow, abort with a clear error so the one-liner doesn't silently misconfigure
    if ! python3 -c "import PIL" >/dev/null 2>&1; then
        echo "ERROR: Could not install Python Pillow (PIL). Please install it manually (e.g. 'apt-get install -y python3-pil' or 'python3 -m pip install pillow') and re-run the installer." >&2
        exit 1
    fi
    # matplotlib remains optional – warn but continue with Pillow-only fallback charts if missing
    if ! python3 -c "import matplotlib" >/dev/null 2>&1; then
        echo "WARNING: matplotlib is not installed; dashboard charts will use a simpler fallback. You can install it later with 'apt-get install -y python3-matplotlib' or 'python3 -m pip install matplotlib'." >&2
    fi

    # Write bot configuration/state seed
    cat >"$STATE_DIR/bot_state.json" <<EOF
{
  "owner_chat_id": $OWNER_CHAT_ID,
  "dashboard_message_ids": {},
  "last_good_metrics": null
}
EOF

    cat >"$STATE_DIR/bot_runtime.conf" <<EOF
BOT_TOKEN=$BOT_TOKEN
METRICS_URL=http://127.0.0.1:9090/metrics
CONDUIT_ENV_PATH=$STATE_DIR/conduit.env
STATE_DIR=$STATE_DIR
EOF

    # Always fetch latest bot code (main.py) and assets from GitHub so re-runs get updates
    echo "Downloading/Updating EasyConduit bot code..."
    BOT_MAIN_URL="${EASYCONDUIT_BOT_MAIN_URL:-https://raw.githubusercontent.com/0xn0c0de/easyconduit/main/bot/main.py}"
    BOT_ASSETS_BASE="${EASYCONDUIT_REPO_RAW:-https://raw.githubusercontent.com/0xn0c0de/easyconduit/main/bot}"
    mkdir -p "$BOT_DIR/assets"
    if command -v curl >/dev/null 2>&1; then
        curl -fL "$BOT_MAIN_URL" -o "$BOT_DIR/main.py"
        curl -fL "${BOT_ASSETS_BASE}/assets/flag.png" -o "$BOT_DIR/assets/flag.png" 2>/dev/null || true
    else
        wget -O "$BOT_DIR/main.py" "$BOT_MAIN_URL"
        wget -O "$BOT_DIR/assets/flag.png" "${BOT_ASSETS_BASE}/assets/flag.png" 2>/dev/null || true
    fi
    chmod +x "$BOT_DIR/main.py"

    # Update script: fetch latest bot + Conduit from GitHub/Psiphon, then restart services
    BOT_MAIN_URL="${EASYCONDUIT_BOT_MAIN_URL:-https://raw.githubusercontent.com/0xn0c0de/easyconduit/main/bot/main.py}"
    CONDUIT_VERSION="1.5.0"
    cat >"$BIN_DIR/update.sh" <<UPDATESH
#!/usr/bin/env bash
# EasyConduit update: bot code + Conduit binary from canonical sources, then restart.
set -euo pipefail
EASY_PREFIX="/opt/easyconduit"
BIN_DIR="\$EASY_PREFIX/bin"
BOT_DIR="\$EASY_PREFIX/bot"
BOT_MAIN_URL="$BOT_MAIN_URL"
BOT_ASSETS_BASE="\${EASYCONDUIT_REPO_RAW:-https://raw.githubusercontent.com/0xn0c0de/easyconduit/main/bot}"
CONDUIT_VERSION="$CONDUIT_VERSION"
mkdir -p "\$BOT_DIR/assets"

arch=\$(uname -m)
case "\$arch" in
    x86_64) arch="amd64" ;;
    aarch64|arm64) arch="arm64" ;;
    *) echo "Unsupported arch \$arch"; exit 1 ;;
esac
CONDUIT_URL="https://github.com/Psiphon-Inc/conduit/releases/download/release-cli-\${CONDUIT_VERSION}/conduit-linux-\$arch"

echo "Updating EasyConduit..."
cp -a "\$BOT_DIR/main.py" "\$BOT_DIR/main.py.bak" 2>/dev/null || true
# Ensure bot dependencies (Pillow + matplotlib) so updated code can start
python3 -m pip install --quiet pillow matplotlib 2>/dev/null || true
if command -v curl >/dev/null 2>&1; then
    curl -fL "\$BOT_MAIN_URL" -o "\$BOT_DIR/main.py.new"
else
    wget -O "\$BOT_DIR/main.py.new" "\$BOT_MAIN_URL"
fi
if python3 -m py_compile "\$BOT_DIR/main.py.new" 2>/dev/null; then
    mv "\$BOT_DIR/main.py.new" "\$BOT_DIR/main.py" && chmod +x "\$BOT_DIR/main.py"
else
    echo "Bot update failed: new main.py invalid, keeping current." >&2
    rm -f "\$BOT_DIR/main.py.new"
fi
if command -v curl >/dev/null 2>&1; then
    curl -fL "\${BOT_ASSETS_BASE}/assets/flag.png" -o "\$BOT_DIR/assets/flag.png" 2>/dev/null || true
else
    wget -O "\$BOT_DIR/assets/flag.png" "\${BOT_ASSETS_BASE}/assets/flag.png" 2>/dev/null || true
fi
# Test-run new bot for 8s; if it exits (crash), restore backup so we don't restart into a broken state
if [ -f "\$BOT_DIR/main.py.bak" ]; then
    timeout 8 python3 "\$BOT_DIR/main.py" 2>/dev/null || true
    code=\$?
    if [ \$code -ne 0 ] && [ \$code -ne 124 ]; then
        echo "Bot crashed on test run (exit \$code), restoring backup." >&2
        mv "\$BOT_DIR/main.py.bak" "\$BOT_DIR/main.py"
    fi
fi
if command -v curl >/dev/null 2>&1; then
    curl -fL "\$CONDUIT_URL" -o "\$BIN_DIR/conduit.new" && mv "\$BIN_DIR/conduit.new" "\$BIN_DIR/conduit" && chmod +x "\$BIN_DIR/conduit"
else
    wget -O "\$BIN_DIR/conduit.new" "\$CONDUIT_URL" && mv "\$BIN_DIR/conduit.new" "\$BIN_DIR/conduit" && chmod +x "\$BIN_DIR/conduit"
fi
systemctl restart conduit.service 2>/dev/null || true
systemctl restart easyconduit-bot.service
echo "Update done."
UPDATESH
    chmod +x "$BIN_DIR/update.sh"

    # systemd unit for bot
    cat >/etc/systemd/system/$BOT_SERVICE <<EOF
[Unit]
Description=EasyConduit Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$BOT_DIR
ExecStart=/usr/bin/python3 $BOT_DIR/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$BOT_SERVICE"
    systemctl restart "$BOT_SERVICE"
}

main() {
    ensure_root
    ensure_environment

    echo
    echo "============================="
    echo "  EasyConduit Installer"
    echo "============================="
    echo
    banner_small_iran_flag
    echo

    prompt_install_mode
    prompt_parameters

    echo
    echo "Installing/Updating Conduit service..."
    install_conduit

    echo "Installing/Updating Telegram bot..."
    install_bot

    echo
    echo "EasyConduit installed/updated successfully."
    echo "You can now close PuTTY and use your Telegram bot."
    echo "Open your bot chat and wait up to a minute for the dashboard to appear."
    echo
    banner_small_iran_flag
    echo
}

main "$@"

