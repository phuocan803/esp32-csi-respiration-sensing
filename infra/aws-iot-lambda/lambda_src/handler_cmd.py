"""
Lambda nt131-cmd  —  Telegram webhook handler for /do command
=============================================================
Flow:
  Telegram  ->  Lambda Function URL  ->  this handler
  On /do    ->  publish to breathing/cmd/<chat_id> via IoT Core
              ->  send ACK message to Telegram
"""
import json
import os
import uuid
import urllib.request
import boto3
from datetime import datetime, timezone

BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
IOT_ENDPOINT = os.getenv("IOT_DATA_ENDPOINT", "")
MEASURE_SECS = int(os.getenv("MEASURE_SECONDS", "60"))
DEVICE_ID    = os.getenv("DEFAULT_DEVICE_ID", "pc-host-01")

MODE_PROFILES = {
    "-1": {
        "measure_seconds": 60,
        "model_window_seconds": 60,
        "model_sampling_rate": 10,
        "label": "60s@10Hz",
    },
    "-2": {
        "measure_seconds": 30,
        "model_window_seconds": 30,
        "model_sampling_rate": 100,
        "label": "30s@100Hz",
    },
}


def _tg_send(chat_id: int, text: str) -> None:
    if not BOT_TOKEN:
        return
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5):
        pass


def lambda_handler(event, _context):
    # Parse Telegram webhook body
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    msg     = body.get("message", {})
    text    = msg.get("text", "").strip()
    chat_id = msg.get("chat", {}).get("id")

    if not chat_id:
        return {"statusCode": 200, "body": "ok"}

    if not text.lower().startswith("/do"):
        _tg_send(chat_id, "Unknown command. Use /do to start a measurement.")
        return {"statusCode": 200, "body": "ok"}

    parts = text.split()
    mode = parts[1].strip() if len(parts) > 1 else ""

    if mode and mode not in MODE_PROFILES:
        _tg_send(
            chat_id,
            "Invalid mode. Use /do -1 for 60s@10Hz or /do -2 for 30s@100Hz.",
        )
        return {"statusCode": 200, "body": "ok"}

    profile = MODE_PROFILES.get(mode)
    measure_secs = profile["measure_seconds"] if profile else MEASURE_SECS

    request_id = str(uuid.uuid4())
    ts         = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"

    payload = {
        "chat_id":        str(chat_id),
        "device_id":      DEVICE_ID,
        "measure_seconds": measure_secs,
        "request_id":     request_id,
        "timestamp":      ts,
    }
    if profile:
        payload["mode"] = mode
        payload["model_window_seconds"] = profile["model_window_seconds"]
        payload["model_sampling_rate"] = profile["model_sampling_rate"]

    # Publish command to IoT Core so run.py picks it up
    iot = boto3.client(
        "iot-data",
        endpoint_url=f"https://{IOT_ENDPOINT}",
        region_name="us-east-1",
    )
    iot.publish(
        topic=f"breathing/cmd/{chat_id}",
        qos=1,
        payload=json.dumps(payload),
    )

    # ACK to Telegram
    _tg_send(
        chat_id,
        "Measurement command accepted.\n"
        f"Device: {DEVICE_ID}\n"
        f"Duration: {measure_secs}s\n"
        f"Mode: {profile['label'] if profile else 'default'}\n"
        f"Request ID: {request_id}\n"
        "Please wait for the result message.",
    )

    return {"statusCode": 200, "body": "ok"}
