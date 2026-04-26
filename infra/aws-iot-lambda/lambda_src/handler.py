import json
import os
import re
import urllib.request
from datetime import datetime, timezone


def _send_telegram(webhook_url: str, text: str) -> None:
    if not webhook_url:
        return
    data = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as _:
        pass


def _send_telegram_chat(bot_token: str, chat_id: int, text: str) -> None:
    if not bot_token or not chat_id:
        return
    data = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as _:
        pass


def _to_int_chat_id(value):
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _chat_id_from_topic(topic: str | None):
    if not topic:
        return None
    m = re.search(r"/(-?\d+)$", str(topic).strip())
    if not m:
        return None
    return _to_int_chat_id(m.group(1))


def lambda_handler(event, _context):
    bpm      = event.get("bpm")
    status   = event.get("status", "Unknown")
    device   = event.get("device_id", event.get("mqtt_topic", "unknown"))
    rssi     = event.get("rssi_dbm") or event.get("rssi")
    loss_pct = event.get("packet_loss_pct")
    error    = event.get("error")
    samples  = event.get("samples")
    mqtt_topic = event.get("mqtt_topic", "")
    chat_id  = _to_int_chat_id(event.get("chat_id"))
    if chat_id is None:
        chat_id = _chat_id_from_topic(mqtt_topic)
    ts_raw   = event.get("timestamp", "")
    webhook  = os.getenv("TELEGRAM_WEBHOOK_URL", "")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    default_chat_id = _to_int_chat_id(os.getenv("TELEGRAM_CHAT_ID", ""))

    try:
        ts_dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        ts_str = ts_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    bpm_str = f"{bpm:.1f} BPM" if isinstance(bpm, (int, float)) else "N/A"

    lines = [
        "Breathing Result",
        f"  Device : {device}",
        f"  BPM    : {bpm_str}",
        f"  Status : {status}",
    ]
    if rssi is not None:
        lines.append(f"  RSSI   : {rssi} dBm")
    if loss_pct is not None:
        lines.append(f"  Loss   : {loss_pct:.1f}%")
    if samples is not None:
        lines.append(f"  Samples: {samples}")
    if error:
        lines.append(f"  Error  : {error}")
    lines.append(f"  Time   : {ts_str}")

    text = "\n".join(lines)

    # Prefer direct Telegram send to the requester chat_id from MQTT payload.
    # Fallback order: payload chat_id -> TELEGRAM_CHAT_ID env -> fixed webhook.
    target_chat_id = chat_id or default_chat_id
    if bot_token and target_chat_id:
        _send_telegram_chat(bot_token, target_chat_id, text)
    else:
        _send_telegram(webhook, text)

    return {
        "ok": True,
        "device": device,
        "bpm": bpm,
        "status": status,
        "chat_id": target_chat_id,
        "chat_id_from_payload": _to_int_chat_id(event.get("chat_id")),
        "chat_id_from_topic": _chat_id_from_topic(mqtt_topic),
        "used_direct_bot": bool(bot_token and target_chat_id),
    }
