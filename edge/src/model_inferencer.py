"""
model_inferencer.py - Stage 3 (Option B): Deep Learning BPM Estimator
======================================================================
Replaces or complements estimator.py (FFT + Peaks) via deep neural network regression.

Workflow:
  1. Receive processed 1D respiration signal from processor.py (shape: WINDOW_SIZE,).
  2. Execute ONNX inference session (exported from training pipeline).
  3. Denormalize target prediction back to actual BPM scale.
  4. Return predicted BPM value to execution engine.

Requirements:
  - File `models/respiration_model.onnx` (or `models_best/respiration_model.onnx`).
  - File `models/model_metadata.json` containing normalization scaling limits.

Dependencies:
  pip install onnxruntime
"""

import json
import os
import numpy as np

_SRC_DIR = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.abspath(os.path.join(_SRC_DIR, '..', '..'))


def _is_valid_model_dir(path: str) -> bool:
    return os.path.exists(os.path.join(path, 'respiration_model.onnx')) and os.path.exists(
        os.path.join(path, 'model_metadata.json')
    )


def _resolve_models_dir() -> str:
    # Optional override from environment variable.
    # Accepts absolute path or project-relative directory.
    override = os.getenv('BREATHING_MODEL_DIR') or os.getenv('MODEL_ARTIFACT_DIR')
    if override:
        candidate = override if os.path.isabs(override) else os.path.join(_PROJECT_ROOT, override)
        candidate = os.path.abspath(candidate)
        if _is_valid_model_dir(candidate):
            return candidate
        raise FileNotFoundError(
            f'Invalid BREATHING_MODEL_DIR/MODEL_ARTIFACT_DIR: {candidate}. '\
            'Required files: respiration_model.onnx, model_metadata.json'
        )

    # Default priority: models
    models_dir = os.path.join(_PROJECT_ROOT, 'models')
    if _is_valid_model_dir(models_dir):
        return models_dir

    fallback_dir = os.path.join(_PROJECT_ROOT, 'models')
    return fallback_dir


_MODELS_DIR = _resolve_models_dir()
_ONNX_PATH = os.path.join(_MODELS_DIR, 'respiration_model.onnx')
_META_PATH = os.path.join(_MODELS_DIR, 'model_metadata.json')

# Lazy loading: load model on demand to conserve memory
_session = None
_metadata = None


def _load_model():
    """Load ONNX session and metadata if not already initialized (Singleton pattern)."""
    global _session, _metadata

    if _session is not None:
        return _session, _metadata

    if not os.path.exists(_ONNX_PATH):
        raise FileNotFoundError(
            f'ONNX model not found at: {_ONNX_PATH}\n'
            'Run train_cnn.py to train and export the ONNX model.'
        )
    if not os.path.exists(_META_PATH):
        raise FileNotFoundError(f'Metadata file not found at: {_META_PATH}')

    import onnxruntime as ort

    print(f'[ModelInferencer] Active model dir: {_MODELS_DIR}')
    print(f'[ModelInferencer] Loading ONNX model from: {_ONNX_PATH}')
    _session = ort.InferenceSession(_ONNX_PATH, providers=['CPUExecutionProvider'])

    with open(_META_PATH, 'r') as f:
        _metadata = json.load(f)

    print(f"[ModelInferencer] Model loaded successfully. Baseline MAE={_metadata.get('model_mae_bpm')} BPM")
    return _session, _metadata


def estimate_bpm_model(breathing_signal: np.ndarray) -> float:
    """
    Estimate BPM from respiration signal using ONNX regression model.

    Parameters:
        breathing_signal: 1D signal output from processor.process_window.
                          Shape must match trained model window size.

    Returns:
        bpm: Estimated respiration rate in BPM (float).
    """
    session, meta = _load_model()

    bpm_min = meta['bpm_min']
    bpm_max = meta['bpm_max']

    # Apply per-window z-score normalization matching training pipeline
    x = breathing_signal.astype(np.float32)
    x = (x - np.mean(x)) / max(np.std(x), 1e-6)

    # Reshape input: (WINDOW_SIZE,) -> (1, WINDOW_SIZE, 1) [batch, time, channel]
    x = x[np.newaxis, :, np.newaxis]

    # Execute ONNX inference
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    y_norm = session.run([output_name], {input_name: x})[0][0][0]

    # Denormalize output value to BPM scale
    bpm = float(y_norm) * (bpm_max - bpm_min) + bpm_min
    bpm = max(bpm_min, min(bpm_max, bpm))  # Clamp value to valid BPM bounds

    return round(bpm, 2)


def is_model_available() -> bool:
    """Check if trained ONNX model and metadata files exist."""
    return os.path.exists(_ONNX_PATH) and os.path.exists(_META_PATH)


def get_model_metadata() -> dict:
    """Return metadata dict of active model."""
    _, meta = _load_model()
    return dict(meta)
