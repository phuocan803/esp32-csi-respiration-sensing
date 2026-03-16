# Scenario 03: Fast Breathing

## Goal

Collect CSI at high breathing rates to test the upper range of estimation.

## collect_data.py Configuration

```python
SUBJECT_NAME     = "AN1"
BPM_GROUND_TRUTH = "26"  # Replace with measured value
```

## Procedure

### Option A: Light activity first (more natural)

1. Participant performs light movement (for example, quick walk in place) for about 2 minutes.
2. Start recording immediately after sitting down.
3. Record about 90-120 seconds.

### Option B: Controlled fast breathing

1. Follow a paced pattern: inhale 1s, exhale 1s.
2. Keep around 25-30 BPM during the first minute.

Safety note:

- Stop immediately if participant feels dizzy or uncomfortable.

## Output Filename Example

```text
AN1_Fast_Take01_BPM26_20260418_111055.csv
```

## Minimum Samples

- 2 files minimum.
