# Scenario 01: Normal Breathing

## Goal

Collect CSI while the participant sits still and breathes naturally at a normal physiological rate.
This is the most important scenario and should have the highest number of samples.

## collect_data.py Configuration

```python
SUBJECT_NAME     = "AN1"
BPM_GROUND_TRUTH = "17"  # Measure manually for 60s before recording
```

## Procedure

1. Participant sits upright, hands on thighs, looking straight ahead.
2. Breathe naturally without intentionally changing rhythm.
3. A second person counts chest rises for 60 seconds.
4. Put that value into BPM_GROUND_TRUTH.
5. Record continuously for 120 seconds.

## Environment Requirements

- Quiet room with minimal movement.
- No fan or strong airflow directly across TX-RX path.
- Participant should not talk or move arms during recording.

## Output Filename Example

```text
AN1_Normal_Take01_BPM17_20260418_095253.csv
```

## Minimum Samples

- 5 files total (preferably across different sessions and/or subjects).
