"""Capture CSI packets from ESP32-RX and save CSV files for model training."""

from __future__ import annotations

import argparse
import csv
import os
import signal
import sys
import time

import serial


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture CSI_DATA rows from serial and save to datasets/*.csv")
    parser.add_argument("--serial-port", default=os.getenv("CSI_SERIAL_PORT", "COM3"))
    parser.add_argument("--baud-rate", type=int, default=int(os.getenv("CSI_BAUD_RATE", "921600")))
    parser.add_argument("--duration-sec", type=int, default=int(os.getenv("CSI_DURATION_SEC", "120")))
    parser.add_argument("--subject", default=os.getenv("CSI_SUBJECT", "AN1"))
    parser.add_argument("--scenario", default=os.getenv("CSI_SCENARIO", "Normal"))
    parser.add_argument("--bpm", type=int, default=int(os.getenv("CSI_BPM", "16")))
    parser.add_argument("--dataset-dir", default=os.getenv("CSI_DATASET_DIR", os.path.join("..", "datasets")))
    return parser


def make_output_path(dataset_dir: str, subject: str, scenario: str, bpm: int) -> str:
    os.makedirs(dataset_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{subject}_{scenario}_Take01_BPM{bpm}_{ts}.csv"
    return os.path.join(dataset_dir, filename)


def run_capture(args: argparse.Namespace) -> str:
    output_path = make_output_path(args.dataset_dir, args.subject, args.scenario, args.bpm)
    should_stop = {"value": False}

    def handle_sigint(_sig, _frame):
        should_stop["value"] = True

    signal.signal(signal.SIGINT, handle_sigint)

    start_t = time.time()
    packet_count = 0
    print(f"[Capture] Opening {args.serial_port} @ {args.baud_rate} ...")
    with serial.Serial(args.serial_port, baudrate=args.baud_rate, timeout=1) as ser:
        with open(output_path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            print(f"[Capture] Writing to: {output_path}")
            print(f"[Capture] Target duration: {args.duration_sec}s (Ctrl+C to stop)")

            while not should_stop["value"]:
                if args.duration_sec > 0 and (time.time() - start_t) >= args.duration_sec:
                    break
                if ser.in_waiting <= 0:
                    continue

                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if "CSI_DATA" not in line:
                    continue

                writer.writerow(line.split(","))
                packet_count += 1
                if packet_count % 200 == 0:
                    elapsed = max(time.time() - start_t, 1e-6)
                    rate = packet_count / elapsed
                    print(f"[Capture] packets={packet_count} avg_rate={rate:.1f} Hz")

    elapsed = max(time.time() - start_t, 1e-6)
    avg_rate = packet_count / elapsed
    print(f"[Capture] Done. packets={packet_count} elapsed={elapsed:.1f}s avg_rate={avg_rate:.1f}Hz")
    print("[Capture] A recording is valid when avg_rate >= 20Hz and packet_count >= duration_sec*20.")
    return output_path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        run_capture(args)
    except serial.SerialException as exc:
        print(f"[Capture][ERROR] Serial failure: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n[Capture] Interrupted by user")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
