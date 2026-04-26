"""
mqtt_client.py - Stage 4: MQTT Integration
===========================================
MQTT publisher integration for publishing respiration rate estimates and telemetry.

Default Topics:
  - "respiration/bpm"   : Publish estimated BPM payload.
  - "respiration/status": Publish classification status (Normal/Fast/Slow/Apnea).
"""

import json
import os
import paho.mqtt.client as paho
from paho import mqtt

# ============================================================
# CONFIG - Environment defaults
# ============================================================
MQTT_BROKER   = os.getenv("MQTT_BROKER", "1904448cf01a4564947dae8e889f5fee.s2.eu.hivemq.cloud")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "your_username")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "your_password")
TOPIC_BPM     = "respiration/bpm"
TOPIC_STATUS  = "respiration/status"


# ============================================================
# Breathing Classification
# ============================================================

def classify_breathing(bpm: float) -> str:
    """
    Classify respiration status based on clinical thresholds.

    Reference Thresholds (Adult at rest):
      - Apnea: < 5 BPM (or undetected)
      - Bradypnea (Slow): 5 – 12 BPM
      - Normal: 12 – 20 BPM
      - Tachypnea (Fast): > 20 BPM

    Parameters:
        bpm: Estimated breaths per minute.

    Returns:
        Status string: "Apnea", "Slow", "Normal", or "Fast".
    """
    if bpm < 5:
        return "Apnea"
    elif bpm < 12:
        return "Slow"
    elif bpm <= 20:
        return "Normal"
    else:
        return "Fast"


def classify_link_quality(rssi: float) -> str:
    """
    Classify WiFi link quality by RSSI level.

    Levels:
      - Good:   RSSI >= -68 dBm
      - Medium: -75 <= RSSI < -68 dBm
      - Poor:   RSSI < -75 dBm
    """
    if rssi >= -68:
        return "Good"
    if rssi >= -75:
        return "Medium"
    return "Poor"


# ============================================================
# MQTT Publisher
# ============================================================

def _on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("[MQTT] Successfully connected to broker.")
    else:
        print(f"[MQTT] Connection failed with status code: {rc}")


def _on_publish(client, userdata, mid, properties=None):
    print(f"[MQTT] Packet published with mid={mid}")


def publish_result(
    bpm: float,
    rssi: float | None = None,
    rssi_std_db: float | None = None,
    packet_rate_hz: float | None = None,
    packet_loss_pct: float | None = None,
    jitter_ms: float | None = None,
    csi_valid_ratio: float | None = None,
    sample_rate_hz: float | None = None,
):
    """
    Publish BPM result and telemetry metrics to MQTT broker.

    Payload format:
      {
        "bpm": <float>,
        "status": "Normal" | "Fast" | "Slow" | "Apnea",
        "rssi": <float, optional>,
        "rssi_std_db": <float, optional>,
        "link_quality": "Good" | "Medium" | "Poor" (optional),
        "packet_rate_hz": <float, optional>,
        "packet_loss_pct": <float, optional>,
        "jitter_ms": <float, optional>,
        "csi_valid_ratio": <float, optional>,
        "sampling_rate_hz": <float, optional>
      }

    Parameters:
        bpm: Estimated BPM value.
    """
    status = classify_breathing(bpm)
    payload_obj = {"bpm": bpm, "status": status}
    if rssi is not None:
        payload_obj["rssi"] = round(float(rssi), 2)
        payload_obj["link_quality"] = classify_link_quality(float(rssi))
    if rssi_std_db is not None:
        payload_obj["rssi_std_db"] = round(float(rssi_std_db), 3)
    if packet_rate_hz is not None:
        payload_obj["packet_rate_hz"] = round(float(packet_rate_hz), 3)
    if packet_loss_pct is not None:
        payload_obj["packet_loss_pct"] = round(float(packet_loss_pct), 3)
    if jitter_ms is not None:
        payload_obj["jitter_ms"] = round(float(jitter_ms), 3)
    if csi_valid_ratio is not None:
        payload_obj["csi_valid_ratio"] = round(float(csi_valid_ratio), 3)
    if sample_rate_hz is not None:
        payload_obj["sampling_rate_hz"] = float(sample_rate_hz)

    payload = json.dumps(payload_obj)

    client = paho.Client(client_id="", userdata=None, protocol=paho.MQTTv5)
    client.on_connect = _on_connect
    client.on_publish = _on_publish

    # Secure TLS connection
    client.tls_set(tls_version=mqtt.client.ssl.PROTOCOL_TLS)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.loop_start()

    client.publish(TOPIC_BPM, payload=payload, qos=1)
    if rssi is not None:
        print(f"[MQTT] Sent BPM={bpm}, Status={status}, RSSI={rssi:.1f} dBm")
    else:
        print(f"[MQTT] Sent BPM={bpm}, Status={status}")

    client.loop_stop()
    client.disconnect()
