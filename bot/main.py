#!/usr/bin/env python3
"""
EasyConduit Telegram bot

- Exactly three messages per chat, always updated in-place (no new messages):
  1. Dashboard image (PNG)
  2. Status text (same info as image)
  3. Control Panel (inline buttons)
- Only the chat ID entered during installation can see and interact with the bot; everyone else is rejected.
"""

# Dashboard version shown in header and /info (bump only when you declare a new version)
DASHBOARD_VERSION = "1.0"
# Canonical repository URL for docs and updates
REPO_URL = "https://github.com/0xn0c0de/easyconduit"

import json
import os
import sys
import time
import traceback
from typing import Dict, Any, List, Optional, Tuple

import urllib.request
import urllib.parse

from io import BytesIO

try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
except ImportError:
    print(
        "Pillow (PIL) is required. Install with: python3 -m pip install pillow",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt  # type: ignore
    _HAS_MATPLOTLIB = True
except ImportError:
    plt = None  # type: ignore
    _HAS_MATPLOTLIB = False


def load_runtime_conf(path: str) -> Dict[str, str]:
    conf: Dict[str, str] = {}
    if not os.path.isfile(path):
        raise RuntimeError(f"Runtime config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip()
    required = ["BOT_TOKEN", "METRICS_URL", "CONDUIT_ENV_PATH", "STATE_DIR"]
    for key in required:
        if key not in conf or not conf[key]:
            raise RuntimeError(f"Missing {key} in runtime config {path}")
    return conf


CMD_DESK_MAIN_TEXT = "EasyConduit – Control Panel\n(Use the buttons below.)"


def load_state(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def save_state(path: str, state: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


class TelegramAPI:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"

    def _request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, bytes]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base}/{method}"
        if files:
            # multipart/form-data
            boundary = "----easyconduitboundary"
            body = BytesIO()
            if params:
                for k, v in params.items():
                    body.write(
                        (
                            f"--{boundary}\r\n"
                            f'Content-Disposition: form-data; name="{k}"\r\n\r\n'
                            f"{v}\r\n"
                        ).encode("utf-8")
                    )
            for field, data in files.items():
                body.write(
                    (
                        f"--{boundary}\r\n"
                        f'Content-Disposition: form-data; name="{field}"; filename="image.png"\r\n'
                        "Content-Type: image/png\r\n\r\n"
                    ).encode("utf-8")
                )
                body.write(data)
                body.write(b"\r\n")
            body.write(f"--{boundary}--\r\n".encode("utf-8"))
            data = body.getvalue()
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
        else:
            encoded = urllib.parse.urlencode(params or {}).encode("utf-8")
            req = urllib.request.Request(url, data=encoded)

        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        try:
            obj = json.loads(raw)
        except Exception:
            raise RuntimeError(f"Telegram API returned non-JSON: {raw!r}")
        if not obj.get("ok", False):
            # Keep returning the error so caller can handle (e.g. recreate messages)
            raise RuntimeError(f"Telegram API error in {method}: {obj}")
        return obj

    def get_updates(self, offset: Optional[int], timeout: int = 30) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"timeout": str(timeout)}
        if offset is not None:
            params["offset"] = str(offset)
        res = self._request("getUpdates", params=params)
        return res.get("result", [])

    def send_photo(
        self,
        chat_id: int,
        caption: str,
        image_bytes: bytes,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"chat_id": str(chat_id), "caption": caption}
        if reply_markup:
            params["reply_markup"] = json.dumps(reply_markup)
        return self._request("sendPhoto", params=params, files={"photo": image_bytes})

    def edit_message_media(
        self,
        chat_id: int,
        message_id: int,
        image_bytes: bytes,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        media = {
            "type": "photo",
            "media": "attach://photo",
        }
        if caption is not None:
            media["caption"] = caption
        params: Dict[str, Any] = {
            "chat_id": str(chat_id),
            "message_id": str(message_id),
            "media": json.dumps(media),
        }
        return self._request(
            "editMessageMedia", params=params, files={"photo": image_bytes}
        )

    def edit_message_caption(
        self, chat_id: int, message_id: int, caption: str
    ) -> Dict[str, Any]:
        params = {
            "chat_id": str(chat_id),
            "message_id": str(message_id),
            "caption": caption,
        }
        return self._request("editMessageCaption", params=params)

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"chat_id": str(chat_id), "text": text}
        if reply_markup:
            params["reply_markup"] = json.dumps(reply_markup)
        return self._request("sendMessage", params=params)

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "chat_id": str(chat_id),
            "message_id": str(message_id),
            "text": text,
        }
        if reply_markup:
            params["reply_markup"] = json.dumps(reply_markup)
        return self._request("editMessageText", params=params)

    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        params = {"callback_query_id": callback_query_id, "text": text, "show_alert": "false"}
        try:
            self._request("answerCallbackQuery", params=params)
        except Exception:
            pass

    def delete_message(self, chat_id: int, message_id: int) -> None:
        """Delete a message. Telegram API expects message_id as integer."""
        try:
            self._request(
                "deleteMessage",
                {"chat_id": str(chat_id), "message_id": int(message_id)},
            )
        except Exception:
            pass

    def delete_webhook(self) -> None:
        """Ensure no webhook is set so getUpdates (long polling) works."""
        try:
            self._request("deleteWebhook", {})
        except Exception:
            pass


def fetch_metrics(metrics_url: str) -> Dict[str, float]:
    """
    Fetch and parse minimal Prometheus metrics needed for dashboard.
    Returns empty dict if Conduit is down or unreachable (no exception).
    """
    values: Dict[str, float] = {}
    try:
        req = urllib.request.Request(metrics_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return values

    wanted = {
        "conduit_connected_clients",
        "conduit_connecting_clients",
        "conduit_bytes_uploaded",
        "conduit_bytes_downloaded",
        "conduit_uptime_seconds",
        "conduit_is_live",
        "conduit_max_clients",
        "conduit_bandwidth_limit_bytes_per_second",
    }
    for line in text.splitlines():
        if line.startswith("#") or " " not in line:
            continue
        name, val = line.split(None, 1)
        if name in wanted:
            try:
                values[name] = float(val.strip())
            except ValueError:
                continue
    return values


def human_bytes(num: float) -> str:
    num = max(0.0, num)
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while num >= 1024.0 and i < len(units) - 1:
        num /= 1024.0
        i += 1
    if i == 0:
        return f"{int(num)} {units[i]}"
    return f"{num:.1f} {units[i]}"


def human_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d > 0:
        return f"{d}d {h}h"
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m"
    return f"{s}s"


def make_bar(current: int, maximum: int, width: int = 10) -> str:
    if maximum <= 0:
        return "[" + ("░" * width) + "]"
    frac = max(0.0, min(1.0, current / float(maximum)))
    filled = int(round(frac * width))
    return "[" + ("█" * filled) + ("░" * (width - filled)) + "]"


# Iran flag (1964–1980): green, white, red + Lion and Sun. We draw tricolor + gold sun (emblem simplified).
_FLAG_GREEN = (35, 159, 64)   # #239F40
_FLAG_WHITE = (255, 255, 255)
_FLAG_RED = (218, 0, 0)      # #DA0000
_FLAG_GOLD = (255, 187, 38)  # #FFBB26


def _draw_flag_iran_1964(img: Image.Image, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int) -> None:
    """Draw Iran (1964–1980) flag: tricolor + gold sun. Uses flag image from assets if present, else drawn."""
    # Try to load from bot assets (e.g. /opt/easyconduit/bot/assets/flag.png) if present
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for name in ("assets/flag.png", "flag.png"):
        path = os.path.join(script_dir, name)
        if os.path.isfile(path):
            try:
                flag_img = Image.open(path).convert("RGB")
                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    resample = Image.LANCZOS
                flag_img = flag_img.resize((w, h), resample)
                img.paste(flag_img, (x, y))
                return
            except Exception:
                pass
    # Fallback: draw tricolor + gold sun (Lion and Sun simplified)
    band_h = h // 3
    draw.rectangle([x, y, x + w, y + band_h], fill=_FLAG_GREEN, outline=(0, 0, 0), width=1)
    draw.rectangle([x, y + band_h, x + w, y + 2 * band_h], fill=_FLAG_WHITE, outline=(0, 0, 0), width=1)
    draw.rectangle([x, y + 2 * band_h, x + w, y + h], fill=_FLAG_RED, outline=(0, 0, 0), width=1)
    cx, cy = x + w // 2, y + band_h + band_h // 2
    r = min(w, band_h) // 3
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_FLAG_GOLD, outline=(0, 0, 0), width=1)


def _get_dashboard_fonts() -> Tuple[Any, Any, Any, Any]:
    """Load fonts for dashboard; fallback to default on server. Returns (font_big, font_med, font_small, font_tiny)."""
    for name, size_big, size_med, size_small, size_tiny in (
        ("DejaVuSans.ttf", 28, 20, 16, 14),
        ("DejaVuSans-Bold.ttf", 28, 20, 16, 14),
        ("LiberationSans-Regular.ttf", 28, 20, 16, 14),
        ("arial.ttf", 28, 20, 16, 14),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28, 20, 16, 14),
    ):
        try:
            font_big = ImageFont.truetype(name, size_big)
            font_med = ImageFont.truetype(name, size_med)
            font_small = ImageFont.truetype(name, size_small)
            font_tiny = ImageFont.truetype(name, size_tiny)
            return font_big, font_med, font_small, font_tiny
        except Exception:
            continue
    default = ImageFont.load_default()
    return default, default, default, default


def _draw_text_centered(
    draw: ImageDraw.Draw,
    box_x: int, box_y: int, box_w: int, box_h: int,
    text: str, font: Any, fill: Tuple[int, int, int],
) -> None:
    """Draw text centered in the given box. Uses textbbox when available."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
    except AttributeError:
        try:
            tw, th = draw.textsize(text, font=font)
        except TypeError:
            tw, th = len(text) * 6, 14
        tx = box_x + (box_w - tw) // 2
        ty = box_y + (box_h - th) // 2
        draw.text((tx, ty), text, fill=fill, font=font)
        return
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = box_x + (box_w - tw) // 2
    ty = box_y + (box_h - th) // 2
    draw.text((tx, ty), text, fill=fill, font=font)


def _draw_sparkline_fallback(
    draw: ImageDraw.Draw,
    x0: int, y0: int, w: int, h: int,
    values: List[float],
    color: Tuple[int, int, int],
    y_max: Optional[float] = None,
) -> None:
    """Pillow-only fallback when matplotlib is not available."""
    if not values or w < 2 or h < 2:
        return
    max_val = y_max if y_max is not None and y_max > 0 else max(max(values), 1.0)
    n = len(values)
    step_x = (w - 1) / max(n - 1, 1)
    points: List[Tuple[int, int]] = []
    for i, v in enumerate(values):
        px = x0 + int(i * step_x)
        py = y0 + h - 1 - int((v / max_val) * (h - 1))
        points.append((px, py))
    if len(points) >= 2:
        draw.line(points, fill=color, width=2)


def _render_matplotlib_chart(
    series: List[List[float]],
    colors: List[Tuple[int, int, int]],
    labels: List[str],
    y_label: str,
    x_label: str,
    width_px: int,
    height_px: int,
) -> Image.Image:
    """Render a small time-series chart with matplotlib and return it as a Pillow Image."""
    if not series or not series[0]:
        return Image.new("RGB", (width_px, height_px), (248, 249, 250))

    def to_hex(c: Tuple[int, int, int]) -> str:
        return "#%02x%02x%02x" % c

    fig, ax = plt.subplots(
        figsize=(max(1.0, width_px / 100.0), max(1.0, height_px / 100.0)),
        dpi=100,
    )
    try:
        for ys, color, label in zip(series, colors, labels):
            if not ys:
                continue
            xs = list(range(len(ys)))
            ax.plot(xs, ys, color=to_hex(color), linewidth=2.0, label=label)

        ax.set_ylabel(y_label)
        ax.set_xlabel(x_label)
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.4)
        if len(series) > 1:
            ax.legend(fontsize=7, loc="best")

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="PNG")
        buf.seek(0)
        chart_img = Image.open(buf).convert("RGB")
    finally:
        plt.close(fig)

    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:
        resample = Image.LANCZOS
    return chart_img.resize((width_px, height_px), resample=resample)


def render_dashboard_image(
    metrics: Dict[str, float],
    max_clients: int,
    bandwidth_mbps: float,
    conduit_svc_status: Optional[str] = None,
    lifetime_bytes_up: float = 0.0,
    lifetime_bytes_down: float = 0.0,
    traffic_history: Optional[List[List[float]]] = None,
    lifetime_history: Optional[List[List[float]]] = None,
    client_seconds_today: float = 0.0,
) -> bytes:
    """Render a professional dashboard PNG: vertical layout, Iran flag, UTC time. Uses conduit_svc_status so image shows STOPPED when service is stopped."""
    # Portrait canvas: single column, two-chart rows for Traffic and Lifetime
    width, height = 600, 980
    # Neutral background
    bg = (245, 246, 248)
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    font_big, font_med, font_small, font_tiny = _get_dashboard_fonts()

    # LIVE only if metrics say so AND conduit service is active; otherwise STOPPED
    metrics_live = metrics.get("conduit_is_live", 0.0) >= 0.5
    if conduit_svc_status is not None and conduit_svc_status != "active":
        live = False
    else:
        live = metrics_live
    connected = int(metrics.get("conduit_connected_clients", 0.0))
    connecting = int(metrics.get("conduit_connecting_clients", 0.0))
    bytes_up = metrics.get("conduit_bytes_uploaded", 0.0)
    bytes_down = metrics.get("conduit_bytes_downloaded", 0.0)
    uptime = metrics.get("conduit_uptime_seconds", 0.0)

    pad = 24
    card_bg = (255, 255, 255)
    card_outline = (220, 221, 225)
    chart_bg = (248, 249, 250)
    gap = 12

    # —— Header: full-width blue bar ——
    header_h = 88
    header_color = (44, 62, 80)
    draw.rectangle([0, 0, width, header_h], fill=header_color)
    # Title + version (top-left)
    draw.text((24, 14), "EasyConduit", fill=(255, 255, 255), font=font_big)
    draw.text((24, 50), f"v{DASHBOARD_VERSION}", fill=(180, 190, 200), font=font_tiny)
    # Status badge: full header height, text centered; width responsive to fit LIVE/STOPPED
    status_text = "LIVE" if live else "STOPPED"
    status_bg = (39, 174, 96) if live else (231, 76, 60)
    badge_w = 110
    badge_x = 24 + 180 + gap
    draw.rectangle([badge_x, 0, badge_x + badge_w, header_h], fill=status_bg)
    _draw_text_centered(draw, badge_x, 0, badge_w, header_h, status_text, font_med, (255, 255, 255))
    # Iran flag: height = full header; width from fixed aspect ratio matching asset (~1024x585, ≈7:4 width:height)
    _FLAG_ASPECT_W_H = 7 / 4
    flag_h = header_h
    flag_w = int(round(flag_h * _FLAG_ASPECT_W_H))
    flag_x = width - flag_w - 16
    flag_y = 0
    _draw_flag_iran_1964(img, draw, flag_x, flag_y, flag_w, flag_h)

    # UTC time below header
    time_y = header_h + 12
    utc_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    draw.text((24, time_y), utc_str, fill=(120, 144, 156), font=font_small)
    content_y = time_y + 28

    card_w_full = width - pad * 2
    x = pad

    # —— Card 1: Clients (clear spacing: label, value, gap, bar, gap, footer text – no overlap) ——
    card_h_clients = 122
    draw.rectangle([x, content_y, x + card_w_full, content_y + card_h_clients], fill=card_bg, outline=card_outline, width=1)
    draw.text((x + 16, content_y + 12), "Clients", fill=(99, 110, 114), font=font_small)
    clients_str = f"{connected} / {max_clients}"
    draw.text((x + 16, content_y + 34), clients_str, fill=(44, 62, 80), font=font_big)
    # Bar starts below the value line (font_big ~28px) with a safe gap so 0/50 never overlaps the bar
    bar_y_b = content_y + 34 + 28 + 8
    bar_x, bar_w, bar_h = x + 16, card_w_full - 32, 14
    draw.rectangle([bar_x, bar_y_b, bar_x + bar_w, bar_y_b + bar_h], fill=(236, 240, 241), outline=card_outline, width=1)
    if max_clients > 0:
        frac = max(0.0, min(1.0, connected / float(max_clients)))
        draw.rectangle([bar_x, bar_y_b, bar_x + int(bar_w * frac), bar_y_b + bar_h], fill=(39, 174, 96))
    client_h_today = client_seconds_today / 3600.0
    draw.text((x + 16, bar_y_b + bar_h + 10), f"Connecting: {connecting}  ·  Client-h today: {client_h_today:.1f}", fill=(99, 110, 114), font=font_small)
    content_y += card_h_clients + pad

    # —— Section: Traffic (session) – two charts side by side (Upload left, Download right), bigger ——
    section_title_h = 44
    chart_h = 220
    chart_section_h = section_title_h + chart_h
    half_w = (card_w_full - gap) // 2
    draw.rectangle([x, content_y, x + card_w_full, content_y + chart_section_h], fill=card_bg, outline=card_outline, width=1)
    draw.text((x + 16, content_y + 10), "Traffic (session)", fill=(99, 110, 114), font=font_small)
    # Color-code the summary line to match chart colors (Upload = blue, Download = purple)
    label_y = content_y + 28
    up_text = f"↑ {human_bytes(bytes_up)}"
    sep_text = "  |  "
    down_text = f"↓ {human_bytes(bytes_down)}"
    # Upload
    draw.text((x + 16, label_y), up_text, fill=(52, 152, 219), font=font_med)
    # Separator (neutral)
    up_w = draw.textbbox((0, 0), up_text, font=font_med)[2]
    draw.text((x + 16 + up_w, label_y), sep_text, fill=(44, 62, 80), font=font_med)
    # Download
    sep_w = draw.textbbox((0, 0), sep_text, font=font_med)[2]
    draw.text((x + 16 + up_w + sep_w, label_y), down_text, fill=(155, 89, 182), font=font_med)
    chart_box_y = content_y + section_title_h
    if traffic_history and len(traffic_history) > 0:
        ups = [p[0] for p in traffic_history]
        downs = [p[1] for p in traffic_history]
        if _HAS_MATPLOTLIB:
            chart_up = _render_matplotlib_chart([ups], [(52, 152, 219)], ["Upload"], "Bytes", "Time (last ~20 min)", half_w - 8, chart_h - 8)
            chart_down = _render_matplotlib_chart([downs], [(155, 89, 182)], ["Download"], "Bytes", "Time (last ~20 min)", half_w - 8, chart_h - 8)
            img.paste(chart_up, (x + 4, chart_box_y + 4))
            img.paste(chart_down, (x + half_w + gap + 4, chart_box_y + 4))
        else:
            draw.rectangle([x + 4, chart_box_y + 4, x + half_w + 4, chart_box_y + chart_h - 4], fill=chart_bg, outline=card_outline, width=1)
            draw.rectangle([x + half_w + gap + 4, chart_box_y + 4, x + card_w_full - 4, chart_box_y + chart_h - 4], fill=chart_bg, outline=card_outline, width=1)
            _draw_sparkline_fallback(draw, x + 8, chart_box_y + 8, half_w - 16, chart_h - 16, ups, (52, 152, 219), y_max=max(ups) if ups else None)
            _draw_sparkline_fallback(draw, x + half_w + gap + 8, chart_box_y + 8, half_w - 16, chart_h - 16, downs, (155, 89, 182), y_max=max(downs) if downs else None)
    content_y += chart_section_h + pad

    # —— Uptime and Bandwidth side by side (shorter horizontal) ——
    card_h_short = 76
    half_card_w = (card_w_full - gap) // 2
    draw.rectangle([x, content_y, x + half_card_w, content_y + card_h_short], fill=card_bg, outline=card_outline, width=1)
    draw.text((x + 12, content_y + 10), "Uptime", fill=(99, 110, 114), font=font_small)
    draw.text((x + 12, content_y + 36), human_duration(uptime), fill=(44, 62, 80), font=font_big)
    draw.rectangle([x + half_card_w + gap, content_y, x + card_w_full, content_y + card_h_short], fill=card_bg, outline=card_outline, width=1)
    draw.text((x + half_card_w + gap + 12, content_y + 10), "Bandwidth", fill=(99, 110, 114), font=font_small)
    bw_text = "Unlimited" if bandwidth_mbps < 0 else f"{bandwidth_mbps:.0f} Mbps"
    draw.text((x + half_card_w + gap + 12, content_y + 36), bw_text, fill=(44, 62, 80), font=font_big)
    content_y += card_h_short + pad

    # —— Section: Lifetime Traffic – two charts side by side (same as Traffic section) ——
    draw.rectangle([x, content_y, x + card_w_full, content_y + chart_section_h], fill=card_bg, outline=card_outline, width=1)
    draw.text((x + 16, content_y + 10), "Lifetime Traffic", fill=(99, 110, 114), font=font_small)
    # Color-code summary to match Lifetime charts
    label_y = content_y + 28
    up_text = f"↑ {human_bytes(lifetime_bytes_up)}"
    sep_text = "  |  "
    down_text = f"↓ {human_bytes(lifetime_bytes_down)}"
    draw.text((x + 16, label_y), up_text, fill=(52, 152, 219), font=font_med)
    up_w = draw.textbbox((0, 0), up_text, font=font_med)[2]
    draw.text((x + 16 + up_w, label_y), sep_text, fill=(44, 62, 80), font=font_med)
    sep_w = draw.textbbox((0, 0), sep_text, font=font_med)[2]
    draw.text((x + 16 + up_w + sep_w, label_y), down_text, fill=(155, 89, 182), font=font_med)
    chart_box_y = content_y + section_title_h
    if lifetime_history and len(lifetime_history) > 0:
        ups = [p[0] for p in lifetime_history]
        downs = [p[1] for p in lifetime_history]
        if _HAS_MATPLOTLIB:
            chart_up = _render_matplotlib_chart([ups], [(52, 152, 219)], ["Upload"], "Bytes", "Time (last ~20 min)", half_w - 8, chart_h - 8)
            chart_down = _render_matplotlib_chart([downs], [(155, 89, 182)], ["Download"], "Bytes", "Time (last ~20 min)", half_w - 8, chart_h - 8)
            img.paste(chart_up, (x + 4, chart_box_y + 4))
            img.paste(chart_down, (x + half_w + gap + 4, chart_box_y + 4))
        else:
            draw.rectangle([x + 4, chart_box_y + 4, x + half_w + 4, chart_box_y + chart_h - 4], fill=chart_bg, outline=card_outline, width=1)
            draw.rectangle([x + half_w + gap + 4, chart_box_y + 4, x + card_w_full - 4, chart_box_y + chart_h - 4], fill=chart_bg, outline=card_outline, width=1)
            _draw_sparkline_fallback(draw, x + 8, chart_box_y + 8, half_w - 16, chart_h - 16, ups, (52, 152, 219), y_max=max(ups) if ups else None)
            _draw_sparkline_fallback(draw, x + half_w + gap + 8, chart_box_y + 8, half_w - 16, chart_h - 16, downs, (155, 89, 182), y_max=max(downs) if downs else None)

    bio = BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def get_service_status(unit: str) -> str:
    """Return systemd unit status: active, inactive, failed, or unknown."""
    try:
        with os.popen(f"systemctl is-active {unit} 2>/dev/null") as p:
            s = (p.read() or "").strip().lower()
        return s if s in ("active", "inactive", "failed") else "unknown"
    except Exception:
        return "unknown"


def update_lifetime_traffic(state: Dict[str, Any], metrics: Dict[str, float]) -> None:
    """
    Update bot-persisted lifetime traffic from current Conduit metrics.
    When Conduit restarts, its byte counters reset; we add deltas so lifetime
    survives restarts. State keys: last_seen_bytes_*, lifetime_bytes_*.
    """
    cur_up = metrics.get("conduit_bytes_uploaded", 0.0)
    cur_down = metrics.get("conduit_bytes_downloaded", 0.0)
    last_up = state.get("last_seen_bytes_uploaded", 0.0)
    last_down = state.get("last_seen_bytes_downloaded", 0.0)
    if cur_up >= last_up:
        state["lifetime_bytes_uploaded"] = state.get("lifetime_bytes_uploaded", 0.0) + (cur_up - last_up)
    if cur_down >= last_down:
        state["lifetime_bytes_downloaded"] = state.get("lifetime_bytes_downloaded", 0.0) + (cur_down - last_down)
    state["last_seen_bytes_uploaded"] = cur_up
    state["last_seen_bytes_downloaded"] = cur_down


# Chart history length (~20 min at 30s interval)
_HISTORY_MAX = 40


def update_heartbeat(state_dir: str) -> None:
    """Write a lightweight heartbeat file so an external watchdog can detect freezes."""
    try:
        hb_path = os.path.join(state_dir, "bot_heartbeat")
        with open(hb_path, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except Exception:
        # Heartbeat must never break the bot
        pass


def ensure_watchdog_installed(state_dir: str) -> None:
    """
    Ensure a simple systemd watchdog service exists.
    It watches the heartbeat file and, if stale, rolls back to main.py.bak (if present)
    and restarts easyconduit-bot.service.
    """
    try:
        prefix = os.path.dirname(state_dir.rstrip(os.sep)) or "/opt/easyconduit"
        bin_dir = os.path.join(prefix, "bin")
        bot_dir = os.path.join(prefix, "bot")
        os.makedirs(bin_dir, exist_ok=True)
        script_path = os.path.join(bin_dir, "bot-watchdog.sh")
        unit_path = "/etc/systemd/system/easyconduit-bot-watchdog.service"

        if not os.path.isfile(script_path):
            script = f"""#!/usr/bin/env bash
set -euo pipefail
STATE_DIR="{state_dir}"
BOT_DIR="{bot_dir}"
SERVICE="easyconduit-bot.service"
HB="$STATE_DIR/bot_heartbeat"

while true; do
  if [ -f "$HB" ]; then
    # If heartbeat file is older than 5 minutes, consider the bot frozen
    if find "$HB" -mmin +5 >/dev/null 2>&1; then
      echo "[easyconduit-watchdog] Heartbeat stale, attempting rollback/restart" >&2
      if [ -f "$BOT_DIR/main.py.bak" ]; then
        cp "$BOT_DIR/main.py.bak" "$BOT_DIR/main.py"
      fi
      systemctl restart "$SERVICE" >/dev/null 2>&1 || true
    fi
  fi
  sleep 60
done
"""
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script)
            os.chmod(script_path, 0o755)

        if not os.path.isfile(unit_path):
            unit = f"""[Unit]
Description=EasyConduit bot watchdog (heartbeat + rollback)
After=easyconduit-bot.service

[Service]
Type=simple
User=root
ExecStart={script_path}
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
"""
            with open(unit_path, "w", encoding="utf-8") as f:
                f.write(unit)

        # (Re)load and ensure watchdog is active; failures are non-fatal
        os.system("systemctl daemon-reload >/dev/null 2>&1 || true")
        os.system("systemctl enable --now easyconduit-bot-watchdog.service >/dev/null 2>&1 || true")
    except Exception:
        # Watchdog install should never break the bot
        pass


def update_client_seconds_today(state: Dict[str, Any], connected: int, interval_sec: float = 30.0) -> None:
    """Add connected*interval_sec to client_seconds_today; reset at midnight UTC. Shows as Client-h today (usage). Total unique clients per day would require Conduit to expose a connection counter."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if state.get("last_day_utc") != today:
        state["client_seconds_today"] = 0.0
        state["last_day_utc"] = today
    state["client_seconds_today"] = state.get("client_seconds_today", 0.0) + connected * interval_sec


def append_metrics_history(state: Dict[str, Any], metrics: Dict[str, float]) -> None:
    """Append current metrics to traffic history for time-series chart. Keeps last _HISTORY_MAX points."""
    up = metrics.get("conduit_bytes_uploaded", 0.0)
    down = metrics.get("conduit_bytes_downloaded", 0.0)
    state.setdefault("traffic_history", []).append([up, down])
    traffic = state["traffic_history"]
    if len(traffic) > _HISTORY_MAX:
        state["traffic_history"] = traffic[-_HISTORY_MAX:]


def append_lifetime_history(state: Dict[str, Any]) -> None:
    """Append current lifetime totals to lifetime_history for growth chart. Call after update_lifetime_traffic."""
    state.setdefault("lifetime_history", []).append([
        state.get("lifetime_bytes_uploaded", 0.0),
        state.get("lifetime_bytes_downloaded", 0.0),
    ])
    hist = state["lifetime_history"]
    if len(hist) > _HISTORY_MAX:
        state["lifetime_history"] = hist[-_HISTORY_MAX:]


def fetch_latest_release() -> Optional[Dict[str, Any]]:
    """
    Placeholder for future remote release metadata.
    Currently returns None so Update behaves as 'reinstall v{DASHBOARD_VERSION}'.
    """
    return None


def build_dashboard_caption(
    metrics: Dict[str, float],
    max_clients: int,
    bandwidth_mbps: float,
    lifetime_bytes_up: float = 0.0,
    lifetime_bytes_down: float = 0.0,
    client_seconds_today: float = 0.0,
) -> str:
    live = metrics.get("conduit_is_live", 0.0) >= 0.5
    connected = int(metrics.get("conduit_connected_clients", 0.0))
    connecting = int(metrics.get("conduit_connecting_clients", 0.0))
    bytes_up = metrics.get("conduit_bytes_uploaded", 0.0)
    bytes_down = metrics.get("conduit_bytes_downloaded", 0.0)
    uptime = metrics.get("conduit_uptime_seconds", 0.0)

    status = "LIVE" if live else "STOPPED"
    bar = make_bar(connected, max_clients, width=10)
    bw_text = "Unlimited" if bandwidth_mbps < 0 else f"{bandwidth_mbps:.0f} Mbps"
    client_h_today = client_seconds_today / 3600.0

    lines = [
        f"EasyConduit · {status}",
        f"Clients: {bar} {connected}/{max_clients} (connecting {connecting}) · Client-h today: {client_h_today:.1f}",
        f"Traffic: Up {human_bytes(bytes_up)} · Down {human_bytes(bytes_down)}",
        f"Uptime: {human_duration(uptime)} · BW: {bw_text}",
        f"Lifetime: Up {human_bytes(lifetime_bytes_up)} · Down {human_bytes(lifetime_bytes_down)}",
    ]
    return "\n".join(lines)


def build_status_message(
    metrics: Optional[Dict[str, float]],
    max_clients: int,
    bandwidth_mbps: float,
    conduit_svc_status: str,
    last_good_metrics: Optional[Dict[str, float]] = None,
    lifetime_bytes_up: float = 0.0,
    lifetime_bytes_down: float = 0.0,
    client_seconds_today: float = 0.0,
) -> str:
    """
    Real-time status message: Conduit + server. Hints when something is down.
    metrics is None when fetch failed (Conduit unreachable); then use last_good_metrics for numbers.
    """
    conduit_svc_hint = conduit_svc_status
    if conduit_svc_status == "inactive":
        conduit_svc_hint = "inactive (stopped)"
    elif conduit_svc_status == "failed":
        conduit_svc_hint = "failed (check logs)"

    if metrics is not None:
        caption = build_dashboard_caption(
            metrics, max_clients, bandwidth_mbps, lifetime_bytes_up, lifetime_bytes_down, client_seconds_today
        )
        conduit_line = "LIVE" if metrics.get("conduit_is_live", 0.0) >= 0.5 else "STOPPED"
    else:
        last = last_good_metrics or {}
        caption = build_dashboard_caption(
            last, max_clients, bandwidth_mbps, lifetime_bytes_up, lifetime_bytes_down, client_seconds_today
        )
        conduit_line = "unreachable (service may be down)"

    lines = [
        caption,
        "",
        "Real-time:",
        f"  Conduit: {conduit_line}  ·  Conduit service: {conduit_svc_hint}",
        "  Server (bot): running",
    ]
    return "\n".join(lines)


def load_conduit_env(path: str) -> Tuple[int, float]:
    max_clients = 50
    bandwidth = 10.0
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k == "MAX_CLIENTS":
                    try:
                        max_clients = int(v)
                    except ValueError:
                        pass
                elif k == "BANDWIDTH":
                    try:
                        bandwidth = float(v)
                    except ValueError:
                        pass
    return max_clients, bandwidth


def build_main_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "🔍 Status", "callback_data": "cmd_status"}],
            [{"text": "⚙ Configs", "callback_data": "cmd_configs"}],
            [{"text": "ℹ More Info", "callback_data": "cmd_info"}],
        ]
    }


def build_configs_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "📊 Max connection limit", "callback_data": "cmd_limits"}],
            [{"text": "📶 Max bandwidth", "callback_data": "cmd_bandwidth"}],
            [{"text": "♻ Restart/Start Conduit", "callback_data": "cmd_restart_conduit"}],
            [{"text": "⏹ Stop Conduit", "callback_data": "cmd_stop_conduit"}],
            [{"text": "🔄 Update", "callback_data": "cmd_update"}],
            [{"text": "⚡ Reboot server", "callback_data": "cmd_reboot"}],
            [{"text": "◀ Back", "callback_data": "back_main"}],
        ]
    }


def build_limits_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "50", "callback_data": "set_clients_50"},
                {"text": "75", "callback_data": "set_clients_75"},
                {"text": "100", "callback_data": "set_clients_100"},
                {"text": "125", "callback_data": "set_clients_125"},
            ],
            [
                {"text": "150", "callback_data": "set_clients_150"},
                {"text": "200", "callback_data": "set_clients_200"},
                {"text": "250", "callback_data": "set_clients_250"},
                {"text": "300", "callback_data": "set_clients_300"},
            ],
            [{"text": "◀ Back", "callback_data": "back_configs"}],
        ]
    }


def build_bandwidth_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "5 Mbps", "callback_data": "set_bw_5"},
                {"text": "10 Mbps", "callback_data": "set_bw_10"},
                {"text": "15 Mbps", "callback_data": "set_bw_15"},
            ],
            [
                {"text": "20 Mbps", "callback_data": "set_bw_20"},
                {"text": "25 Mbps", "callback_data": "set_bw_25"},
                {"text": "30 Mbps", "callback_data": "set_bw_30"},
            ],
            [{"text": "◀ Back", "callback_data": "back_configs"}],
        ]
    }


def build_restart_conduit_confirm_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Yes, restart", "callback_data": "restart_conduit_confirm"},
                {"text": "❌ Cancel", "callback_data": "restart_conduit_cancel"},
            ]
        ]
    }


def build_stop_conduit_confirm_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Yes, stop", "callback_data": "stop_conduit_confirm"},
                {"text": "❌ Cancel", "callback_data": "stop_conduit_cancel"},
            ]
        ]
    }


def build_update_confirm_keyboard(label_yes: str = "✅ Yes, update") -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": label_yes, "callback_data": "update_confirm"},
                {"text": "❌ Cancel", "callback_data": "update_cancel"},
            ]
        ]
    }


def build_reboot_confirm_keyboard() -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Yes, reboot server", "callback_data": "reboot_confirm"},
                {"text": "❌ Cancel", "callback_data": "reboot_cancel"},
            ]
        ]
    }


def delete_chat_ui_messages(
    api: TelegramAPI,
    state: Dict[str, Any],
    chat_id: int,
) -> None:
    """Delete the three bot UI messages for this chat (if any) and clear their IDs from state."""
    ckey = str(chat_id)
    dashboard_ids: Dict[str, Any] = state.setdefault("dashboard_message_ids", {})
    status_ids: Dict[str, Any] = state.setdefault("status_message_ids", {})
    command_ids: Dict[str, Any] = state.setdefault("command_message_ids", {})

    for msg_id in (
        dashboard_ids.get(ckey),
        status_ids.get(ckey),
        command_ids.get(ckey),
    ):
        if msg_id is not None:
            try:
                api.delete_message(chat_id, int(msg_id))
            except Exception:
                pass

    for d in (dashboard_ids, status_ids, command_ids):
        if ckey in d:
            del d[ckey]


def ensure_chat_messages(
    api: TelegramAPI,
    state: Dict[str, Any],
    chat_id: int,
    status_text: str,
    image_bytes: bytes,
) -> Tuple[int, int, int]:
    """
    Ensure exactly three messages exist: (1) dashboard image, (2) status text, (3) command desk.
    Returns (dashboard_message_id, status_message_id, command_message_id).
    """
    dashboard_ids: Dict[str, int] = state.setdefault("dashboard_message_ids", {})
    status_ids: Dict[str, int] = state.setdefault("status_message_ids", {})
    command_ids: Dict[str, int] = state.setdefault("command_message_ids", {})

    dash_id = dashboard_ids.get(str(chat_id))
    status_id = status_ids.get(str(chat_id))
    cmd_id = command_ids.get(str(chat_id))

    if dash_id is None:
        try:
            res = api.send_photo(chat_id, "", image_bytes)
            dash_id = res["result"]["message_id"] if "result" in res else res["message_id"]
        except Exception:
            dash_id = None
    if status_id is None:
        try:
            res = api.send_message(chat_id, status_text)
            status_id = res["result"]["message_id"] if "result" in res else res["message_id"]
        except Exception:
            status_id = None
    if cmd_id is None:
        try:
            kb = build_main_keyboard()
            res = api.send_message(chat_id, CMD_DESK_MAIN_TEXT, reply_markup=kb)
            cmd_id = res["result"]["message_id"] if "result" in res else res["message_id"]
        except Exception:
            cmd_id = None

    if dash_id is not None:
        dashboard_ids[str(chat_id)] = dash_id
    if status_id is not None:
        status_ids[str(chat_id)] = status_id
    if cmd_id is not None:
        command_ids[str(chat_id)] = cmd_id
    return dash_id or 0, status_id or 0, cmd_id or 0


def update_dashboard_for_chat(
    api: TelegramAPI,
    state: Dict[str, Any],
    chat_id: int,
    status_text: str,
    image_bytes: bytes,
) -> None:
    """Update in place: (1) dashboard image, (2) status text. Only create messages on /start, not from periodic update."""
    dashboard_ids: Dict[str, int] = state.setdefault("dashboard_message_ids", {})
    status_ids: Dict[str, int] = state.setdefault("status_message_ids", {})
    dash_id = dashboard_ids.get(str(chat_id))
    status_id = status_ids.get(str(chat_id))

    # Do not create messages here – only /start creates the 3 messages. Avoids 6 messages on first run.
    if not dash_id or not status_id:
        return

    try:
        api.edit_message_media(chat_id, dash_id, image_bytes, caption=None)
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" in err:
            pass
        elif "message to edit not found" in err or "message can't be edited" in err or "message not found" in err:
            try:
                res = api.send_photo(chat_id, "", image_bytes)
                dash_id = res["result"]["message_id"] if "result" in res else res["message_id"]
                dashboard_ids[str(chat_id)] = dash_id
            except Exception:
                pass

    try:
        api.edit_message_text(chat_id, status_id, status_text)
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" in err:
            pass
        elif "message to edit not found" in err or "message can't be edited" in err or "message not found" in err:
            try:
                res = api.send_message(chat_id, status_text)
                status_id = res["result"]["message_id"] if "result" in res else res["message_id"]
                status_ids[str(chat_id)] = status_id
            except Exception:
                pass


def edit_command_desk(
    api: TelegramAPI,
    state: Dict[str, Any],
    chat_id: int,
    text: str,
    keyboard: Dict[str, Any],
) -> None:
    """Edit the command-desk message in place. Send new only if the message does not exist."""
    command_ids: Dict[str, int] = state.setdefault("command_message_ids", {})
    cmd_id = command_ids.get(str(chat_id))

    if not cmd_id:
        # Create if missing
        try:
            res = api.send_message(chat_id, text, reply_markup=keyboard)
            cmd_id = res["result"]["message_id"] if "result" in res else res["message_id"]
            command_ids[str(chat_id)] = cmd_id
        except Exception:
            return
        return

    try:
        api.edit_message_text(chat_id, cmd_id, text, reply_markup=keyboard)
    except Exception as e:
        err = str(e).lower()
        # Do not send new message for "message is not modified" (same content) – avoids spam
        if "message is not modified" in err:
            return
        # Only recreate when the message to edit no longer exists
        if "message to edit not found" in err or "message can't be edited" in err or "message not found" in err:
            try:
                res = api.send_message(chat_id, text, reply_markup=keyboard)
                cmd_id = res["result"]["message_id"] if "result" in res else res["message_id"]
                command_ids[str(chat_id)] = cmd_id
            except Exception:
                pass


def set_conduit_param(env_path: str, key: str, value: str) -> None:
    d: Dict[str, str] = {}
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    d[key] = value
    with open(env_path, "w", encoding="utf-8") as f:
        for k, v in d.items():
            f.write(f"{k}={v}\n")


def system_restart_conduit() -> None:
    os.system("systemctl restart conduit.service >/dev/null 2>&1 || true")


def system_stop_conduit() -> None:
    os.system("systemctl stop conduit.service >/dev/null 2>&1 || true")


def system_start_conduit() -> None:
    os.system("systemctl start conduit.service >/dev/null 2>&1 || true")


def system_reboot() -> None:
    os.system("reboot >/dev/null 2>&1 || true")


def main() -> None:
    while True:
        try:
            _main_loop()
        except KeyboardInterrupt:
            break
        except Exception:
            traceback.print_exc()
            print("[bot] Startup or runtime error, retrying in 30s...", file=sys.stderr, flush=True)
            time.sleep(30)


def _main_loop() -> None:
    runtime_path = os.environ.get("EASYCONDUIT_RUNTIME_CONF", "/opt/easyconduit/state/bot_runtime.conf")
    runtime = load_runtime_conf(runtime_path)
    state_dir = runtime["STATE_DIR"]
    os.makedirs(state_dir, exist_ok=True)
    state_path = os.path.join(state_dir, "bot_state.json")
    state = load_state(state_path)
    if "owner_chat_id" not in state:
        raise RuntimeError("owner_chat_id missing in bot_state.json")

    owner_chat_id = int(state["owner_chat_id"])

    api = TelegramAPI(runtime["BOT_TOKEN"])
    api.delete_webhook()
    # One-time: ensure watchdog service is present so frozen bots can be auto-rolled-back via heartbeat.
    ensure_watchdog_installed(state_dir)

    metrics_url = runtime["METRICS_URL"]
    conduit_env_path = runtime["CONDUIT_ENV_PATH"]

    last_dashboard_ts = 0.0
    update_interval = 30.0
    status_rate_limit_sec = 10

    # Persist offset so after restart we don't re-process the same update (e.g. update_confirm)
    try:
        lid = state.get("last_update_id")
        offset = int(lid) + 1 if lid is not None else None
    except (TypeError, ValueError):
        offset = None

    # On startup (or restart), normalize the command desk text to the main view,
    # so any previous \"Update started\" or transient text is cleared.
    try:
        edit_command_desk(api, state, owner_chat_id, CMD_DESK_MAIN_TEXT, build_main_keyboard())
        save_state(state_path, state)
    except Exception:
        traceback.print_exc()

    while True:
        try:
            now = time.time()
            # Heartbeat on every main-loop iteration so watchdog can detect freezes
            update_heartbeat(state_dir)

            # Periodic dashboard updates – always update so status reflects real-time (Conduit + server)
            if now - last_dashboard_ts >= update_interval:
                max_clients, bandwidth = load_conduit_env(conduit_env_path)
                conduit_svc = get_service_status("conduit.service")
                metrics = None
                try:
                    metrics = fetch_metrics(metrics_url)
                    state["last_good_metrics"] = metrics
                    if metrics:
                        update_lifetime_traffic(state, metrics)
                        append_lifetime_history(state)
                        append_metrics_history(state, metrics)
                        connected = int(metrics.get("conduit_connected_clients", 0.0))
                        update_client_seconds_today(state, connected, 30.0)
                except Exception:
                    traceback.print_exc()
                last_good = state.get("last_good_metrics")
                lifetime_up = state.get("lifetime_bytes_uploaded", 0.0)
                lifetime_down = state.get("lifetime_bytes_downloaded", 0.0)
                traffic_hist = state.get("traffic_history", [])
                lifetime_hist = state.get("lifetime_history", [])
                client_sec_today = state.get("client_seconds_today", 0.0)
                status_text = build_status_message(
                    metrics, max_clients, bandwidth, conduit_svc, last_good_metrics=last_good,
                    lifetime_bytes_up=lifetime_up, lifetime_bytes_down=lifetime_down,
                    client_seconds_today=client_sec_today,
                )
                img_metrics = metrics if metrics is not None else (last_good or {})
                img_bytes = render_dashboard_image(
                    img_metrics, max_clients, bandwidth, conduit_svc,
                    lifetime_bytes_up=lifetime_up, lifetime_bytes_down=lifetime_down,
                    traffic_history=traffic_hist, lifetime_history=lifetime_hist,
                    client_seconds_today=client_sec_today,
                )
                for cid in [owner_chat_id]:
                    try:
                        update_dashboard_for_chat(api, state, cid, status_text, img_bytes)
                    except Exception:
                        traceback.print_exc()
                save_state(state_path, state)
                last_dashboard_ts = now

            # Process updates from Telegram
            try:
                updates = api.get_updates(offset, timeout=10)
            except Exception:
                updates = []

            for upd in updates:
                offset = max(offset or 0, upd.get("update_id", 0) + 1)
                state["last_update_id"] = upd.get("update_id")

                # Handle callback queries (buttons)
                if "callback_query" in upd:
                    cq = upd["callback_query"]
                    cq_id = str(cq.get("id"))
                    msg = cq.get("message") or {}
                    chat = msg.get("chat") or cq.get("from") or {}
                    chat_id = int(chat.get("id"))
                    data = cq.get("data") or ""

                    is_owner = chat_id == owner_chat_id
                    if not is_owner:
                        api.answer_callback_query(cq_id, "Not authorized. Only the chat ID set during installation can use this bot.")
                        continue

                    if data == "cmd_status":
                        last_press: Dict[str, float] = state.setdefault("last_status_press", {})
                        t = last_press.get(str(chat_id), 0.0)
                        if now - t < status_rate_limit_sec:
                            api.answer_callback_query(cq_id, "Please wait before refreshing again.")
                        else:
                            last_press[str(chat_id)] = now
                            last_dashboard_ts = 0.0
                            api.answer_callback_query(cq_id, "Refreshing…")

                    elif data == "cmd_configs":
                        edit_command_desk(
                            api, state, chat_id,
                            "Configs – limits and Conduit control. Conduit service will restart when you change limits.",
                            build_configs_keyboard(),
                        )
                        api.answer_callback_query(cq_id, "")

                    elif data == "cmd_limits":
                        edit_command_desk(
                            api, state, chat_id,
                            "Max connection limit (50–300). Conduit supports this range; service restarts after change.",
                            build_limits_keyboard(),
                        )
                        api.answer_callback_query(cq_id, "")

                    elif data == "cmd_bandwidth":
                        edit_command_desk(
                            api, state, chat_id,
                            "Max bandwidth (5–30 Mbps). Service restarts after change.",
                            build_bandwidth_keyboard(),
                        )
                        api.answer_callback_query(cq_id, "")

                    elif data == "back_main":
                        edit_command_desk(api, state, chat_id, CMD_DESK_MAIN_TEXT, build_main_keyboard())
                        api.answer_callback_query(cq_id, "")

                    elif data == "back_configs":
                        edit_command_desk(
                            api, state, chat_id,
                            "Configs – limits and Conduit control. Conduit service will restart when you change limits.",
                            build_configs_keyboard(),
                        )
                        api.answer_callback_query(cq_id, "")

                    elif data.startswith("set_clients_") and is_owner:
                        allowed = (50, 75, 100, 125, 150, 200, 250, 300)
                        try:
                            mc = int(data.split("_", 2)[2])
                            if mc in allowed:
                                set_conduit_param(conduit_env_path, "MAX_CLIENTS", str(mc))
                                system_restart_conduit()
                                api.answer_callback_query(cq_id, f"Max clients set to {mc}. Conduit restarting.")
                            else:
                                api.answer_callback_query(cq_id, "Use one of the preset values.")
                        except ValueError:
                            api.answer_callback_query(cq_id, "Invalid value.")

                    elif data.startswith("set_bw_") and is_owner:
                        allowed_bw = (5, 10, 15, 20, 25, 30)
                        try:
                            bw_val = int(data.split("_", 2)[2])
                            if bw_val in allowed_bw:
                                set_conduit_param(conduit_env_path, "BANDWIDTH", str(bw_val))
                                system_restart_conduit()
                                api.answer_callback_query(cq_id, f"Bandwidth set to {bw_val} Mbps. Conduit restarting.")
                            else:
                                api.answer_callback_query(cq_id, "Use one of the preset values.")
                        except ValueError:
                            api.answer_callback_query(cq_id, "Invalid value.")

                    elif data == "cmd_restart_conduit":
                        edit_command_desk(
                            api, state, chat_id,
                            "Restart (or start) Conduit service? It will apply current limits.",
                            build_restart_conduit_confirm_keyboard(),
                        )
                        api.answer_callback_query(cq_id, "")

                    elif data == "restart_conduit_confirm":
                        system_restart_conduit()
                        edit_command_desk(api, state, chat_id, CMD_DESK_MAIN_TEXT, build_main_keyboard())
                        api.answer_callback_query(cq_id, "Conduit restarted.")

                    elif data == "restart_conduit_cancel":
                        edit_command_desk(api, state, chat_id, CMD_DESK_MAIN_TEXT, build_main_keyboard())
                        api.answer_callback_query(cq_id, "Cancelled.")

                    elif data == "cmd_stop_conduit":
                        edit_command_desk(
                            api, state, chat_id,
                            "Stop Conduit? Dashboard will show STOPPED. You can start again via Configs → Restart/Start Conduit.",
                            build_stop_conduit_confirm_keyboard(),
                        )
                        api.answer_callback_query(cq_id, "")

                    elif data == "stop_conduit_confirm":
                        system_stop_conduit()
                        max_clients, bandwidth = load_conduit_env(conduit_env_path)
                        conduit_svc = get_service_status("conduit.service")
                        metrics = None
                        try:
                            metrics = fetch_metrics(metrics_url)
                            if metrics:
                                update_lifetime_traffic(state, metrics)
                                append_lifetime_history(state)
                                append_metrics_history(state, metrics)
                                connected = int(metrics.get("conduit_connected_clients", 0.0))
                                update_client_seconds_today(state, connected, 30.0)
                        except Exception:
                            pass
                        last_good = state.get("last_good_metrics")
                        lifetime_up = state.get("lifetime_bytes_uploaded", 0.0)
                        lifetime_down = state.get("lifetime_bytes_downloaded", 0.0)
                        traffic_hist = state.get("traffic_history", [])
                        lifetime_hist = state.get("lifetime_history", [])
                        client_sec_today = state.get("client_seconds_today", 0.0)
                        status_text = build_status_message(
                            metrics, max_clients, bandwidth, conduit_svc, last_good_metrics=last_good,
                            lifetime_bytes_up=lifetime_up, lifetime_bytes_down=lifetime_down,
                            client_seconds_today=client_sec_today,
                        )
                        img_metrics = metrics if metrics is not None else (last_good or {})
                        img_bytes = render_dashboard_image(
                            img_metrics, max_clients, bandwidth, conduit_svc,
                            lifetime_bytes_up=lifetime_up, lifetime_bytes_down=lifetime_down,
                            traffic_history=traffic_hist, lifetime_history=lifetime_hist,
                            client_seconds_today=client_sec_today,
                        )
                        update_dashboard_for_chat(api, state, chat_id, status_text, img_bytes)
                        if metrics is not None:
                            state["last_good_metrics"] = metrics
                        edit_command_desk(api, state, chat_id, CMD_DESK_MAIN_TEXT, build_main_keyboard())
                        api.answer_callback_query(cq_id, "Conduit stopped. Status updated.")

                    elif data == "stop_conduit_cancel":
                        edit_command_desk(api, state, chat_id, CMD_DESK_MAIN_TEXT, build_main_keyboard())
                        api.answer_callback_query(cq_id, "Cancelled.")

                    elif data == "cmd_update":
                        # For now, we treat the current deployed version as latest stable.
                        text = (
                            "EasyConduit – Update\n\n"
                            f"You are on EasyConduit v{DASHBOARD_VERSION}.\n\n"
                            "Press the button below to re-download and reinstall this version from GitHub, "
                            "or Cancel to go back.\n\n"
                            f"Project: {REPO_URL}"
                        )
                        label_yes = f"🔄 Reinstall v{DASHBOARD_VERSION}"
                        edit_command_desk(
                            api, state, chat_id,
                            text,
                            build_update_confirm_keyboard(label_yes),
                        )
                        api.answer_callback_query(cq_id, "")

                    elif data == "update_confirm":
                        api.answer_callback_query(cq_id, "Updating…")
                        # Keep the command desk on its main text while update runs; avoid stale \"Update started\" text after restart.
                        edit_command_desk(api, state, chat_id, CMD_DESK_MAIN_TEXT, build_main_keyboard())
                        state["last_update_id"] = upd.get("update_id")
                        save_state(state_path, state)
                        try:
                            os.system("bash /opt/easyconduit/bin/update.sh >/dev/null 2>&1")
                        except Exception:
                            pass

                    elif data == "update_cancel":
                        edit_command_desk(
                            api, state, chat_id,
                            "Configs – limits and Conduit control. Conduit service will restart when you change limits.",
                            build_configs_keyboard(),
                        )
                        api.answer_callback_query(cq_id, "Cancelled.")

                    elif data == "cmd_reboot":
                        edit_command_desk(
                            api, state, chat_id,
                            "Reboot the entire server? All connections will drop. Only use if needed.",
                            build_reboot_confirm_keyboard(),
                        )
                        api.answer_callback_query(cq_id, "")

                    elif data == "reboot_confirm":
                        api.answer_callback_query(cq_id, "Rebooting now…")
                        system_reboot()

                    elif data == "reboot_cancel":
                        edit_command_desk(api, state, chat_id, cmd_desk_main_text(), build_main_keyboard())
                        api.answer_callback_query(cq_id, "Cancelled.")

                    elif data == "cmd_info":
                        info_text = (
                            f"EasyConduit v{DASHBOARD_VERSION} – About\n\n"
                            "This bot controls a Psiphon Conduit inproxy on this server. "
                            "You see a live dashboard (image + status) and a Control Panel with buttons. "
                            "Conduit limits (max clients, bandwidth) take effect after a service restart.\n\n"
                            f"Project: {REPO_URL}"
                        )
                        edit_command_desk(api, state, chat_id, info_text, build_main_keyboard())
                        api.answer_callback_query(cq_id, "")

                    else:
                        api.answer_callback_query(cq_id, "")

                    save_state(state_path, state)
                    continue

                # Handle messages (/start etc.)
                msg = upd.get("message")
                if not msg:
                    continue
                chat = msg.get("chat") or {}
                chat_id = int(chat.get("id"))
                text = msg.get("text") or ""

                if text.startswith("/start"):
                    print(f"[bot] /start from chat_id={chat_id} owner={owner_chat_id}", file=sys.stderr, flush=True)
                    if chat_id != owner_chat_id:
                        try:
                            api.send_message(
                                chat_id,
                                "Not authorized. Only the chat ID set during installation can use this bot.",
                            )
                        except Exception:
                            pass
                        continue
                    # Remove existing bot UI messages and start fresh
                    delete_chat_ui_messages(api, state, chat_id)
                    try:
                        max_clients, bandwidth = load_conduit_env(conduit_env_path)
                        conduit_svc = get_service_status("conduit.service")
                        metrics = None
                        try:
                            metrics = fetch_metrics(metrics_url)
                            if metrics:
                                update_lifetime_traffic(state, metrics)
                                append_lifetime_history(state)
                                append_metrics_history(state, metrics)
                                connected = int(metrics.get("conduit_connected_clients", 0.0))
                                update_client_seconds_today(state, connected, 30.0)
                        except Exception:
                            pass
                        last_good = state.get("last_good_metrics")
                        lifetime_up = state.get("lifetime_bytes_uploaded", 0.0)
                        lifetime_down = state.get("lifetime_bytes_downloaded", 0.0)
                        traffic_hist = state.get("traffic_history", [])
                        lifetime_hist = state.get("lifetime_history", [])
                        client_sec_today = state.get("client_seconds_today", 0.0)
                        status_text = build_status_message(
                            metrics, max_clients, bandwidth, conduit_svc, last_good_metrics=last_good,
                            lifetime_bytes_up=lifetime_up, lifetime_bytes_down=lifetime_down,
                            client_seconds_today=client_sec_today,
                        )
                        img_metrics = metrics if metrics is not None else (last_good or {})
                        img_bytes = render_dashboard_image(
                            img_metrics, max_clients, bandwidth, conduit_svc,
                            lifetime_bytes_up=lifetime_up, lifetime_bytes_down=lifetime_down,
                            traffic_history=traffic_hist, lifetime_history=lifetime_hist,
                            client_seconds_today=client_sec_today,
                        )
                    except Exception:
                        conduit_svc = get_service_status("conduit.service")
                        lifetime_up = state.get("lifetime_bytes_uploaded", 0.0)
                        lifetime_down = state.get("lifetime_bytes_downloaded", 0.0)
                        traffic_hist = state.get("traffic_history", [])
                        lifetime_hist = state.get("lifetime_history", [])
                        client_sec_today = state.get("client_seconds_today", 0.0)
                        status_text = build_status_message(
                            None, 50, 10.0, conduit_svc, last_good_metrics=None,
                            lifetime_bytes_up=lifetime_up, lifetime_bytes_down=lifetime_down,
                            client_seconds_today=client_sec_today,
                        )
                        status_text = status_text + "\n\n(Dashboard will update once metrics are available.)"
                        img_bytes = render_dashboard_image(
                            {}, 50, 10.0, conduit_svc, lifetime_up, lifetime_down,
                            traffic_history=traffic_hist, lifetime_history=lifetime_hist,
                            client_seconds_today=client_sec_today,
                        )
                    try:
                        ensure_chat_messages(api, state, chat_id, status_text, img_bytes)
                        save_state(state_path, state)
                        print(f"[bot] /start done for chat_id={chat_id}", file=sys.stderr, flush=True)
                    except Exception as e:
                        print(f"[bot] /start failed for chat_id={chat_id}: {e}", file=sys.stderr, flush=True)
                        traceback.print_exc()

                # Ignore any other free-form text; bot is button-driven.

            time.sleep(1)
        except KeyboardInterrupt:
            break
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()

