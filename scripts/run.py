"""
run.py  —  ESP32 CSI Breathing Monitor
========================================
Flow:
  1. python run.py  -> opens serial, connects to AWS IoT Core
  2. User sends /do on Telegram
    3. run.py collects MEASURE_SECONDS of fresh CSI, runs CNN ONNX inference
  4. Publishes result to breathing/result/<chat_id> via MQTT
  5. AWS IoT Rule -> Lambda -> Telegram result notification

Usage:
    python run.py               # uses config.env (default COM16)
    python run.py --port COM3   # override serial port
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Full, Queue

# ── Resolve script/project roots and load config.env ──────────────────────
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

_load_env(_SCRIPT_DIR / "config.env")

# ── CLI ───────────────────────────────────────────────────────────────────
_ap = argparse.ArgumentParser(description="ESP32 WiFi Breathing Monitor")
_ap.add_argument("--port", default=None, help="Serial port override (e.g. COM16)")
_args = _ap.parse_args()

# ── Config ────────────────────────────────────────────────────────────────
SERIAL_PORT   = _args.port or os.getenv("SERIAL_PORT",   "COM16")
BAUD_RATE     = int(os.getenv("BAUD_RATE",    "115200"))
ENDPOINT      = os.getenv("AWS_IOT_ENDPOINT", "a19d98g5v8f80n-ats.iot.us-east-1.amazonaws.com")
CLIENT_ID     = os.getenv("AWS_IOT_CLIENT_ID", "basicPubSub")
DEVICE_ID     = os.getenv("DEVICE_ID",         "pc-host-01")
DEFAULT_CHAT  = os.getenv("TELEGRAM_CHAT_ID",  "8044018687")
MEASURE_SECS  = int(os.getenv("MEASURE_SECONDS", "60"))
FS            = float(os.getenv("SAMPLING_RATE", "100"))
MODEL_WINDOW_S = int(os.getenv("MODEL_WINDOW_SECONDS", "30"))
MODEL_FS       = float(os.getenv("MODEL_SAMPLING_RATE", "100"))

CERT = str(_PROJECT_ROOT / os.getenv("AWS_CERT_PATH", "certs/device.cert.pem"))
KEY  = str(_PROJECT_ROOT / os.getenv("AWS_KEY_PATH",  "certs/device.private.key"))
CA   = str(_PROJECT_ROOT / os.getenv("AWS_CA_PATH",   "certs/root-CA.pem"))

# ── Signal processing ─────────────────────────────────────────────────────
sys.path.insert(0, str(_PROJECT_ROOT / "edge"))
from src.processor import process_window
from src.estimator import estimate_bpm_fft
from src.model_inferencer import estimate_bpm_model, get_model_metadata, is_model_available


def classify(bpm: float) -> str:
    if bpm < 5:   return "Apnea"
    if bpm < 12:  return "Slow"
    if bpm <= 20: return "Normal"
    return "Fast"


# ── Parse CSI serial line ─────────────────────────────────────────────────
def parse_csi(line: str):
    import numpy as np
    m = re.search(r"\[([-\d ]+)\]", line)
    if not m:
        return None, None
    try:
        values = list(map(int, m.group(1).split()))
    except ValueError:
        return None, None
    if len(values) < 128:
        return None, None
    rssi = None
    parts = line.split(",")
    if len(parts) > 3:
        try:
            rssi = float(parts[3])
        except (ValueError, IndexError):
            pass
    return np.array(values[:128], dtype=np.float32), rssi


# ── AWS IoT ───────────────────────────────────────────────────────────────
def connect_iot():
    from awsiot import mqtt_connection_builder
    from awscrt import mqtt as _mqtt
    for path, label in [(CERT, "cert"), (KEY, "key"), (CA, "root CA")]:
        if not Path(path).exists():
            print(f"[ERROR] {label} not found: {path}")
            sys.exit(1)
    conn = mqtt_connection_builder.mtls_from_path(
        endpoint=ENDPOINT,
        cert_filepath=CERT,
        pri_key_filepath=KEY,
        ca_filepath=CA,
        client_id=CLIENT_ID,
    )
    print(f"[IoT] Connecting to {ENDPOINT} ...")
    conn.connect().result(20)
    print("[IoT] Connected OK")
    return conn, _mqtt





# ── Command queue (filled by MQTT subscription callback) ─────────────────
_cmd_queue: Queue = Queue()

# ── Serial reader thread ──────────────────────────────────────────────────
_csi_queue: Queue = Queue(maxsize=30000)
_quit = threading.Event()
_serial_stats = {
    "lines": 0,
    "csi_tag": 0,
    "parsed": 0,
    "dropped": 0,
}


def _serial_reader(ser) -> None:
    import serial as _serial
    while not _quit.is_set():
        try:
            raw = ser.readline().decode(errors="ignore").strip()
        except _serial.SerialException:
            time.sleep(0.5)
            continue
        if raw:
            _serial_stats["lines"] += 1
        if "CSI_DATA" not in raw:
            continue
        _serial_stats["csi_tag"] += 1
        csi, rssi = parse_csi(raw)
        if csi is None:
            continue
        _serial_stats["parsed"] += 1
        try:
            _csi_queue.put_nowait((csi, rssi))
        except Full:
            _serial_stats["dropped"] += 1
            _csi_queue.get_nowait()        # drop oldest packet
            _csi_queue.put_nowait((csi, rssi))


# ── Measurement ───────────────────────────────────────────────────────────
def do_measurement(chat_id: str, conn, _mqtt) -> None:
    import numpy as np

    window_end = time.time() + MEASURE_SECS

    # Flush old data — only use fresh CSI from this moment
    while not _csi_queue.empty():
        _csi_queue.get_nowait()

    buf       = []
    last_rssi = None
    stat0 = dict(_serial_stats)
    bpm_cnn = None
    bpm_fft = None
    infer_mode = None
    model_window_s = MODEL_WINDOW_S
    model_fs = MODEL_FS

    def _publish_result(status: str, bpm: float | None, error: str | None = None) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        payload = {
            "device_id": DEVICE_ID,
            "chat_id":   chat_id,
            "bpm":       round(bpm, 1) if isinstance(bpm, (int, float)) else None,
            "status":    status,
            "rssi_dbm":  last_rssi,
            "timestamp": ts,
            "window_s":  MEASURE_SECS,
            "mode":      "on_demand",
            "samples":   len(buf),
            "infer_mode": infer_mode,
            "bpm_cnn": round(bpm_cnn, 2) if isinstance(bpm_cnn, (int, float)) else None,
            "bpm_fft": round(bpm_fft, 2) if isinstance(bpm_fft, (int, float)) else None,
            "fs_eff_hz": round(fs_eff, 3) if "fs_eff" in locals() else None,
            "model_window_s": model_window_s,
            "model_fs_hz": model_fs,
        }
        if error:
            payload["error"] = error

        topic = f"breathing/result/{chat_id}"
        fut, _ = conn.publish(
            topic=topic,
            payload=json.dumps(payload),
            qos=_mqtt.QoS.AT_LEAST_ONCE,
        )
        fut.result(10)
        print(f"[Measure] Published result status={status} -> {topic}")

    print(f"[Measure] Collecting {MEASURE_SECS}s of fresh CSI ...")
    while time.time() < window_end:
        try:
            csi, rssi = _csi_queue.get(timeout=2)
        except Empty:
            print("[Measure] Waiting for CSI packets ...")
            continue
        buf.append(csi)
        last_rssi = rssi
        if len(buf) % 1000 == 0:
            remaining = max(0, int(window_end - time.time()))
            print(f"[Measure] samples={len(buf)}  remaining={remaining}s")

    d_lines = _serial_stats["lines"] - stat0["lines"]
    d_tag = _serial_stats["csi_tag"] - stat0["csi_tag"]
    d_parsed = _serial_stats["parsed"] - stat0["parsed"]
    print(f"[Measure] Serial stats during window: lines={d_lines}, csi_tag={d_tag}, parsed={d_parsed}")

    if len(buf) == 0:
        _publish_result(
            "NoData",
            None,
            f"No CSI packets received during measurement window (lines={d_lines}, csi_tag={d_tag}, parsed={d_parsed})",
        )
        return

    # Use the real observed sample rate instead of assuming configured FS.
    fs_eff = len(buf) / float(MEASURE_SECS)
    if fs_eff < 2.0:
        _publish_result(
            "NoData",
            None,
            f"Sample rate too low for BPM estimation: {fs_eff:.2f} Hz (samples={len(buf)})",
        )
        return

    print("[Measure] Running BPM estimation ...")
    try:
        csi_matrix = np.array(buf)
        signal_proc = process_window(csi_matrix, fs=fs_eff)

        if len(signal_proc) < 8:
            _publish_result("NoData", None, f"Signal too short after processing: n={len(signal_proc)}")
            return

        # Primary: FFT on the processed live signal.
        bpm_fft = float(estimate_bpm_fft(signal_proc, fs=fs_eff)["bpm"])
        bpm = bpm_fft
        infer_mode = "fft"

        # Keep CNN as optional diagnostic only when the artifact is present.
        if is_model_available():
            model_meta = get_model_metadata()
            model_window_s = int(model_meta.get("window_seconds", MODEL_WINDOW_S))
            model_fs = float(model_meta.get("sampling_rate_hz", MODEL_FS))
            target_len = int(model_window_s * model_fs)
            if target_len > 0:
                signal_cnn = signal_proc
                if len(signal_cnn) != target_len:
                    x_old = np.linspace(0.0, 1.0, num=len(signal_cnn), endpoint=True)
                    x_new = np.linspace(0.0, 1.0, num=target_len, endpoint=True)
                    signal_cnn = np.interp(x_new, x_old, signal_cnn).astype(np.float32)
                bpm_cnn = float(estimate_bpm_model(signal_cnn))
    except Exception as e:
        print(f"[Measure] Inference error: {e}")
        _publish_result("Error", None, f"Inference failed: {e}")
        return

    status = classify(bpm)
    _publish_result(status, bpm)
    print(
        f"[Measure] BPM={bpm:.1f}  Status={status}  mode={infer_mode}  "
        f"cnn={bpm_cnn:.2f}  fft={bpm_fft:.2f}  "
        f"fs_eff={fs_eff:.2f}Hz  samples={len(buf)}  model_input={int(model_window_s * model_fs)}"
    )


# ── Main ──────────────────────────────────────────────────────────────────
def main() -> int:
    import serial as _serial

    print("=" * 55)
    print("  ESP32 WiFi Breathing Monitor")
    print(f"  Serial  : {SERIAL_PORT} @ {BAUD_RATE} baud")
    print(f"  Trigger : MQTT breathing/cmd/+ (via Lambda webhook)")
    print(f"  Measure : {MEASURE_SECS}s per reading")
    print(f"  Publish : breathing/result/<chat_id>")
    print("=" * 55)

    conn, _mqtt = connect_iot()

    # Subscribe to /do commands published by nt131-cmd Lambda
    def _on_cmd(topic, payload, **_):
        try:
            data = json.loads(payload.decode() if isinstance(payload, bytes) else payload)
            print(f"[Cmd] Received from {topic}: {data}")
            _cmd_queue.put_nowait(data)
        except Exception as exc:
            print(f"[Cmd] Parse error: {exc}")

    sub_fut, _ = conn.subscribe(
        topic="breathing/cmd/+",
        qos=_mqtt.QoS.AT_LEAST_ONCE,
        callback=_on_cmd,
    )
    sub_fut.result(10)
    print("[IoT] Subscribed to breathing/cmd/+")

    try:
        ser = _serial.Serial(SERIAL_PORT, baudrate=BAUD_RATE, timeout=1)
        print(f"[Serial] Opened {SERIAL_PORT}")
    except _serial.SerialException as e:
        print(f"[ERROR] Cannot open {SERIAL_PORT}: {e}")
        conn.disconnect().result(5)
        return 1

    threading.Thread(target=_serial_reader, args=(ser,), daemon=True).start()
    print("[Serial] Background reader started")
    print("[Ready] Waiting for /do from Telegram ...")

    measuring = False

    try:
        while True:
            try:
                # This timeout only controls how often the loop wakes while idle.
                # Measurement duration is controlled by MEASURE_SECS in do_measurement().
                cmd = _cmd_queue.get(timeout=1)
            except Empty:
                continue

            if measuring:
                print("[Cmd] Already measuring — ignoring duplicate command")
                continue

            chat_id = cmd.get("chat_id", DEFAULT_CHAT)
            print(f"[Cmd] Starting measurement for chat_id={chat_id}")
            measuring = True
            do_measurement(chat_id, conn, _mqtt)
            measuring = False

    except KeyboardInterrupt:
        print("\n[Stopped] Ctrl+C")
    finally:
        _quit.set()
        ser.close()
        conn.disconnect().result(5)
        print("[Done]")

    return 0


if __name__ == "__main__":
    sys.exit(main())

