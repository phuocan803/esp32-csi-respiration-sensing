# CSI Breathing Data Collection Guide

This document is the single, unified guide for scenario planning and CSI data collection.

## 1. Scenario Overview

Each scenario also has a dedicated file in this folder.

| File | Scenario | Target BPM | Minimum Samples |
|:---|:---|:---|:---|
| [01_normal_breathing.md](./01_normal_breathing.md) | Normal breathing | 12-18 | 5 files |
| [02_slow_breathing.md](./02_slow_breathing.md) | Slow / deep breathing | < 10 | 2 files |
| [03_fast_breathing.md](./03_fast_breathing.md) | Fast breathing | > 25 | 2 files |
| [04_apnea.md](./04_apnea.md) | Apnea (breath holding) | ~ 0 | 2 files |
| [05_noisy_environment.md](./05_noisy_environment.md) | Noisy environment | any | 3 files |

Recommended scenario order:

1. Normal breathing first (system familiarization).
2. Apnea next (high contrast signal behavior).
3. Slow and Fast (expand BPM range).
4. Noisy environment last (after clean data is sufficient).

## 2. Required Equipment

- 2x ESP32 boards with firmware flashed (see DEPLOYMENT_GUIDE.md, Phase 1)
- 1x PC or Jetson Nano with Python 3.9+
- 1x USB cable for ESP32-RX
- 1x stopwatch (phone is fine)
- Labels or stickers for TX and RX boards

## 3. Physical Setup

![Data Collection Setup](../assets/data_collection_setup.png)

- Place TX and RX at chest height.
- The participant sits centered between TX and RX (within about 30 cm from center).
- Keep the path between TX, participant, and RX clear of large obstacles.

## 4. File Naming Convention

Use this format for all CSV files:

```
[SubjectName]_[Scenario]_Take[NN]_BPM[XX]_[YYYYMMDD]_[HHMMSS].csv
```

Examples:

```
AN1_Normal_Take01_BPM17_20260418_095253.csv
AN1_Apnea_Take03_BPM06_20260418_084613.csv
AN2_Fast_Take05_BPM26_20260418_154118.csv
```

Notes:

- Scenario should be one of: Apnea, Slow, Normal, Noise, Fast.
- Use two digits for Take index (Take01, Take02, ...).
- Keep BPM with two digits when possible (BPM06, BPM12, BPM17, BPM26).

## 5. Step-by-Step Collection Process (One Sample)

### Step 1 - Power on devices

1. Power ESP32-TX first (battery or USB adapter).
2. Connect ESP32-RX to PC/Jetson via USB.
3. Wait about 5 seconds for both boards to connect.

### Step 2 - Open terminal

```bash
cd ESP32-WiFi-Breathing
```

### Step 3 - Configure collection script

Open edge/collect_data.py and set:

```python
SERIAL_PORT      = "COM3"        # Windows: COM3, COM4... | Linux: /dev/ttyUSB0
SUBJECT_NAME     = "An"          # Participant name
BPM_GROUND_TRUTH = "placeholder" # Fill after manual measurement
```

Use the scenario file in this folder to decide the expected BPM condition.

### Step 4 - Measure breathing rate manually

Before recording:

1. Start a 60-second timer.
2. Count chest rises (1 rise = 1 breath).
3. Enter the measured value into BPM_GROUND_TRUTH.
4. Save the file.

### Step 5 - Start recording

```bash
python edge/collect_data.py
```

Expected terminal output:

```
[*] Opening port COM3...
[*] Writing file: datasets/An_BPM16_20240320_090000.csv
[+] Packet #1 received...
[+] Packet #2 received...
```

### Step 6 - Perform the scenario

For 120 seconds while recording:

- Participant follows the selected scenario.
- Operator watches packet count; it should increase continuously.

Failure sign:

- If packet logs pause for more than 5 seconds, connection may be unstable.
- Stop and check USB/power before retrying.

### Step 7 - Stop and save

Press Ctrl+C after about 120 seconds.

The CSV file is saved automatically in datasets/.

### Step 8 - Verify data quality

```bash
python edge/verify_data.py datasets/An_BPM16_20240320_090000.csv
```

Target quality:

```
[+] Total packets: 12000+
[+] Valid CSI: 98%+
[+] Estimated sampling rate: 95-105 Hz
```

If quality fails, delete the file and repeat the process.

## 6. Session Checklist

Use this checklist during each data collection session:

```
[ ] TX and RX are powered and connected
[ ] Correct serial port selected (COMx or /dev/ttyUSB0)
[ ] SUBJECT_NAME is correct
[ ] BPM_GROUND_TRUTH measured and updated
[ ] Quiet environment with minimal movement
[ ] Participant centered between TX and RX
[ ] Packet count increases steadily
[ ] Full 120-second recording completed
[ ] verify_data.py result is PASS
```

## 7. Dataset Target

Collect at least 14 CSV files in total:

| Scenario | Required Files |
|:---|:---|
| Normal breathing (01) | 5 files |
| Slow breathing (02) | 2 files |
| Fast breathing (03) | 2 files |
| Apnea (04) | 2 files |
| Noisy environment (05) | 3 files |

## 8. Quick Logging After Each Sample

After each recording, write one short log line (notebook or datasets/log.txt):

```
[2024-03-20 09:00] An_BPM16 - Normal - OK - 12240 packets
[2024-03-20 09:05] An_BPM07 - Slow   - OK - 12180 packets
[2024-03-20 09:10] An_BPM00 - Apnea  - FAIL - 800 packets (USB disconnected)
```
