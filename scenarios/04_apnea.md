# Scenario 04: Apnea (Breath Hold)

## Goal

Collect short breath-hold segments for apnea detection testing.
This scenario is critical for alert-oriented behavior.

## collect_data.py Configuration

```python
SUBJECT_NAME     = "AN1"
BPM_GROUND_TRUTH = "06"
```

## Procedure

Use an alternating timeline in one recording:

```text
[0-20s]    Normal breathing (baseline)
[20-40s]   Breath hold (apnea event)
[40-60s]   Normal breathing (recovery)
[60-80s]   Breath hold (apnea event)
[80-120s]  Normal breathing (recovery)
```

Steps:

1. Start collection script.
2. Guide participant according to the timeline above.
3. Keep clear verbal or hand signals for transition points.

Safety note:

- Do not force prolonged breath hold.
- Stop immediately if participant is uncomfortable.

## Output Filename Example

```text
AN1_Apnea_Take01_BPM06_20260418_083015.csv
```

## Analysis Value

This pattern creates low-breath segments and recovery segments in one file,
useful for validating apnea event detection.

## Minimum Samples

- 2 files minimum.
