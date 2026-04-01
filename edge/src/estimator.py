"""
estimator.py - Stage 3: BPM Estimation Engine
===============================================
Estimates respiration rate (BPM - Breaths Per Minute) from processed CSI signals.

Two estimation approaches:
  1. FFT (Fast Fourier Transform): Reliable when signals are periodic and low-noise.
  2. Peak Detection (Time domain): Effective when signal amplitudes are distinct.

Note: Combines both methods via fusion strategy for increased estimation stability.
"""

import numpy as np
from scipy.signal import find_peaks


# ============================================================
# Method 1: Fast Fourier Transform (FFT)
# ============================================================

def estimate_bpm_fft(signal: np.ndarray, fs: float = 100.0) -> dict:
    """
    Estimate BPM by identifying peak dominant frequency in frequency domain (FFT).

    Algorithm:
      1. Compute Real FFT of the input signal.
      2. Mask frequency axis to respiration range [0.1, 0.5] Hz (corresponding to [6, 30] BPM).
      3. Locate dominant magnitude peak index within mask.
      4. Convert frequency (Hz) to BPM (multiply by 60).

    Parameters:
        signal: 1D band-pass filtered respiration signal.
        fs:     Sampling frequency in Hz.

    Returns:
        dict containing:
          - 'bpm': Estimated respiration rate in BPM (float).
          - 'dominant_freq_hz': Peak dominant frequency in Hz.
          - 'fft_magnitude': FFT magnitude array (for visualization).
          - 'fft_freqs': Corresponding frequency axis (for visualization).
    """
    n = len(signal)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)        # Frequency axis (Hz)
    fft_magnitude = np.abs(np.fft.rfft(signal))   # FFT magnitude

    # Restrict search range to respiration frequency band [0.1, 0.5] Hz
    breathing_mask = (freqs >= 0.1) & (freqs <= 0.5)
    masked_magnitude = fft_magnitude.copy()
    masked_magnitude[~breathing_mask] = 0

    dominant_idx = np.argmax(masked_magnitude)
    dominant_freq = freqs[dominant_idx]
    bpm = dominant_freq * 60.0

    return {
        "bpm": round(bpm, 2),
        "dominant_freq_hz": round(dominant_freq, 4),
        "fft_magnitude": fft_magnitude,
        "fft_freqs": freqs,
    }


# ============================================================
# Method 2: Peak Detection (Time Domain)
# ============================================================

def estimate_bpm_peaks(signal: np.ndarray, fs: float = 100.0) -> dict:
    """
    Estimate BPM by counting local signal peaks over time window.

    Algorithm:
      1. Use scipy.signal.find_peaks to identify local peaks.
      2. Calculate average inter-peak interval in seconds.
      3. BPM = 60 / (average inter-peak interval).

    Parameters:
        signal: 1D band-pass filtered respiration signal.
        fs:     Sampling frequency in Hz.

    Returns:
        dict containing:
          - 'bpm': Estimated BPM (float), -1.0 if insufficient peaks detected.
          - 'peak_count': Number of detected peaks in window.
          - 'peak_indices': Peak sample indices (for visualization).
    """
    # Minimum distance between peaks = minimum breath interval
    # Max respiration rate ~40 BPM -> min interval = 60 / 40 = 1.5s = 1.5 * fs samples
    min_distance_samples = int(1.5 * fs)
    peaks, _ = find_peaks(signal, distance=min_distance_samples, prominence=0.01)

    n_peaks = len(peaks)
    if n_peaks < 2:
        # Insufficient peaks to calculate reliable BPM
        return {"bpm": -1.0, "peak_count": n_peaks, "peak_indices": peaks}

    # Calculate average inter-peak distance in seconds
    intervals_seconds = np.diff(peaks) / fs
    avg_interval = np.mean(intervals_seconds)
    bpm = 60.0 / avg_interval

    return {
        "bpm": round(bpm, 2),
        "peak_count": n_peaks,
        "peak_indices": peaks,
    }


# ============================================================
# Fusion Estimation Method
# ============================================================

def estimate_bpm(signal: np.ndarray, fs: float = 100.0) -> dict:
    """
    Combine FFT and Peak Detection estimates for robust BPM outputs.

    Fusion Strategy:
      - If Peak Detection succeeds (peak_count >= 2): Average FFT and Peak estimates.
      - If Peak Detection yields insufficient peaks: Fall back to FFT estimate.

    Parameters:
        signal: 1D respiration signal.
        fs:     Sampling frequency in Hz.

    Returns:
        dict containing:
          - 'bpm': Final fused BPM value.
          - 'bpm_fft': FFT-derived BPM.
          - 'bpm_peaks': Peak-derived BPM (-1.0 if insufficient).
          - 'method': Fusion method applied.
          - Full FFT and peak details.
    """
    fft_result = estimate_bpm_fft(signal, fs)
    peak_result = estimate_bpm_peaks(signal, fs)

    bpm_fft = fft_result["bpm"]
    bpm_peaks = peak_result["bpm"]

    if bpm_peaks > 0:
        # Weighted average fusion (FFT:Peaks = 1:1)
        bpm_final = round((bpm_fft + bpm_peaks) / 2.0, 2)
        method = "FFT + Peak Detection (averaged)"
    else:
        bpm_final = bpm_fft
        method = "FFT only (not enough peaks)"

    return {
        "bpm": bpm_final,
        "bpm_fft": bpm_fft,
        "bpm_peaks": bpm_peaks,
        "method": method,
        **fft_result,
        "peak_count": peak_result["peak_count"],
        "peak_indices": peak_result["peak_indices"],
    }
