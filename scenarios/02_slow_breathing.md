# Scenario 02: Slow / Deep Breathing

## Goal

Collect CSI during slow, deep breathing (meditation-like pattern).
This scenario tests low-frequency respiration tracking.

## collect_data.py Configuration

```python
SUBJECT_NAME     = "AN1"
BPM_GROUND_TRUTH = "12"  # Replace with measured value
```

## Procedure

1. Participant sits comfortably and stays still.
2. Follow a slow pattern such as: inhale 4s -> hold 1s -> exhale 4s.
3. Practice this rhythm for about 30 seconds before recording.
4. Record continuously for 120 seconds.

## Ground Truth BPM Rule

Count complete breaths (inhale + exhale) in 60 seconds.

Example:

- If counted 12 breaths, use BPM_GROUND_TRUTH = "12".

## Output Filename Example

```text
AN1_Slow_Take01_BPM12_20260418_091212.csv
```

## Minimum Samples

- 2 files minimum.
