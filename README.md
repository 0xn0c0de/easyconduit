# EasyConduit

EasyConduit is a **one-command installer + Telegram dashboard** for running a Psiphon Conduit station on a VPS.

It:

- Installs the official Conduit CLI with embedded Psiphon config.
- Sets up a Telegram bot as your **only interface** after installation:
  - One live dashboard message (caption + PNG) that updates every 60 seconds.
  - One command desk message with **inline buttons only** (no text commands needed).
- Lets you:
  - See connected clients, traffic, uptime, and bandwidth limits.
  - Change max clients and bandwidth.
  - Restart Conduit.
  - Reboot the server (with confirmation).

All a non-technical user needs is:

- A Telegram bot token and chat ID.
- A small VPS (e.g. Hetzner CX22).
- PuTTY + PuTTYgen on Windows.

Then they log in **once**, run **one command**, answer a few prompts, and close the server forever. Everything else happens in Telegram.

## Quick start (for users)

Full step‑by‑step with screenshots is in [`docs/USER_GUIDE_HETZNER.md`](docs/USER_GUIDE_HETZNER.md).

High‑level steps:

1. **Create Telegram bot + chat ID**
   - Use @BotFather to create a bot and get the Bot Token.
   - Use `https://api.telegram.org/bot<token>/getUpdates` to get your Chat ID.
2. **Install PuTTY + PuTTYgen** on Windows and create an SSH key.
3. **Create a VPS on Hetzner** (Ubuntu 22.04/24.04, e.g. CX22) and add your SSH public key.
4. **Connect once with PuTTY** as `root`.
5. **Run the installer command** (as root on the VPS):

   ```bash
   curl -sSL https://raw.githubusercontent.com/0xn0c0de/easyconduit/main/install.sh | bash
   ```

6. When asked:
   - Paste/enter your **Bot Token**.
   - Paste/enter your **Chat ID**.
   - Press Enter to accept defaults for max clients and bandwidth, or type new values.
7. Wait for “EasyConduit installed…”, then **close PuTTY**.
8. Open Telegram and talk to your bot:
   - The **top message** is a live dashboard (image + caption) that updates every minute.
   - The **bottom message** is the command desk with buttons for everything.

## What gets installed on the VPS

Under `/opt/easyconduit`:

- `bin/conduit` – Conduit CLI binary from the official Psiphon-Inc releases.
- `bin/run-conduit.sh` – wrapper that launches Conduit with parameters from `state/conduit.env`.
- `data/` – Conduit data directory (keys and state), owned by a `conduit` system user.
- `state/conduit.env` – current `DATA_DIR`, `MAX_CLIENTS`, and `BANDWIDTH`.
- `state/bot_state.json` – bot state: owner chat ID, message IDs, last metrics.
- `state/bot_runtime.conf` – bot runtime config: token, metrics URL, paths.
- `bot/main.py` – Telegram bot.

