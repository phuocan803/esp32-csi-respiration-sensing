# Scenario 05: Noisy Environment

## Goal

Collect CSI under external interference conditions.
This scenario is used to evaluate robustness of preprocessing and estimation.

## collect_data.py Configuration

```python
SUBJECT_NAME     = "AN1"
BPM_GROUND_TRUTH = "17"
```

## Noise Types to Test

### Noise A: Human movement

- While participant breathes normally, another person walks around the room.
- Keep movement roughly 1-3 meters from TX-RX path.

### Noise B: Fan / airflow

- Turn on a fan to create airflow disturbance near TX-RX path.
- Avoid direct airflow to participant face.

### Noise C: RF interference

- Add extra Wi-Fi activity nearby (for example, phone hotspot or active traffic).

## Output Filename Example

```text
AN1_Noise_Take01_BPM17_20260418_103259.csv
```

Optional logging tag (in notes file):

- NoiseType=Moving
- NoiseType=Fan
- NoiseType=RF

## Minimum Samples

- At least 1 file for each noise type (3 files minimum).

## Expected Result

- Under mild noise, BPM error should remain reasonably small.
- If error increases significantly, review preprocessing and filtering parameters.
