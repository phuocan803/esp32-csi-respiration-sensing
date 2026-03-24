"""
processor.py - Stage 2: Signal Processing Pipeline
====================================================
Signal processing pipeline to isolate respiration signals from raw CSI data.
Processing Order: Amplitude -> Hampel -> PCA -> Band-pass

Rationale for execution order:
  1. Extract Amplitude as chest expansion/respiration modulates WiFi signal magnitude.
  2. Apply Hampel Filter before Band-pass filter so impulse noise (spikes) does not
     cause ringing artifacts in the Butterworth filter.
  3. Apply PCA to reduce 64 subcarrier channels into the single dominant component (PC1).
  4. Apply Band-pass filter (0.1–0.5 Hz) to isolate the human respiration frequency band.
"""

import numpy as np
from scipy.signal import butter, filtfilt
from sklearn.decomposition import PCA


# ============================================================
# Step 1: Amplitude Extraction
# ============================================================

def extract_amplitude(csi_raw: np.ndarray) -> np.ndarray:
    """
    Extract magnitude (amplitude) from raw CSI array.

    Raw ESP32 CSI consists of interleaved values: [imaginary, real, imaginary, real, ...]
    Amplitude = sqrt(imaginary^2 + real^2)

    Parameters:
        csi_raw: 1D array of raw CSI values, shape (128,) representing 64 subcarrier channels.

    Returns:
        amplitudes: 1D amplitude array, shape (64,).
    """
    imaginary = csi_raw[0::2]  # Even indices
    real = csi_raw[1::2]       # Odd indices
    amplitudes = np.sqrt(imaginary**2 + real**2)
    return amplitudes


# ============================================================
# Step 2: Hampel Filter - Spike / Outlier Removal
# ============================================================

def hampel_filter(signal: np.ndarray, window_size: int = 5, n_sigma: float = 3.0) -> np.ndarray:
    """
    Detect and replace outliers in a time series using Median and MAD.

    Sweeps a sliding window across the signal. If a data point deviates from the
    window median by more than (n_sigma * k * MAD), it is identified as a spike outlier
    and replaced with the window median.

    Parameters:
        signal:      1D time-series array to filter.
        window_size: Half-window size. Total window length = 2 * window_size + 1.
        n_sigma:     Sigma multiplier threshold (typically 3.0 following 3-sigma rule).

    Returns:
        filtered: Cleaned 1D array with outliers replaced.
    """
    k = 1.4826  # Scale factor for standard normal distribution consistency
    filtered = signal.copy()
    n = len(signal)

    for i in range(window_size, n - window_size):
        window = signal[i - window_size: i + window_size + 1]
        median = np.median(window)
        mad = np.median(np.abs(window - median))
        threshold = n_sigma * k * mad

        if np.abs(signal[i] - median) > threshold:
            filtered[i] = median

    return filtered


# ============================================================
# Step 3: PCA - Primary Component Channel Selection
# ============================================================

def apply_pca(amplitude_matrix: np.ndarray, n_components: int = 1) -> np.ndarray:
    """
    Compress amplitude matrix (n_samples x 64_subcarriers) down to dominant component.

    The 1st principal component (PC1) captures co-phase respiration fluctuations
    across subcarrier channels.

    Parameters:
        amplitude_matrix: 2D array of shape (n_samples, n_subcarriers).
        n_components:     Number of principal components to retain (default: 1).

    Returns:
        pc1: 1D time-series array of shape (n_samples,).
    """
    pca = PCA(n_components=n_components)
    transformed = pca.fit_transform(amplitude_matrix)
    return transformed[:, 0]


# ============================================================
# Step 4: Band-pass Filter (Butterworth)
# ============================================================

def bandpass_filter(signal: np.ndarray, fs: float, lowcut: float = 0.1, highcut: float = 0.5, order: int = 4) -> np.ndarray:
    """
    Apply Butterworth band-pass filter to isolate respiration frequencies.

    Human respiration rate: 12–20 breaths/min = 0.2–0.33 Hz.
    Filter range 0.1–0.5 Hz covers slow (6 BPM) to fast (30 BPM) breathing.

    Parameters:
        signal:  1D input signal array.
        fs:      Sampling frequency in Hz (configured packet rate).
        lowcut:  Lower cutoff frequency in Hz (default: 0.1 Hz / 6 BPM).
        highcut: Upper cutoff frequency in Hz (default: 0.5 Hz / 30 BPM).
        order:   Filter order (default: 4).

    Returns:
        filtered: Filtered 1D signal array.
    """
    nyquist = 0.5 * fs
    low = lowcut / nyquist
    high = highcut / nyquist
    b, a = butter(order, [low, high], btype='band')
    # Zero-phase digital filtering to prevent phase distortion
    filtered = filtfilt(b, a, signal)
    return filtered


# ============================================================
# Complete Signal Pipeline
# ============================================================

def process_window(
    csi_window: np.ndarray,
    fs: float = 100.0,
    bandpass_lowcut: float = 0.1,
    bandpass_highcut: float = 0.5,
    bandpass_order: int = 4,
) -> np.ndarray:
    """
    Execute the complete signal processing pipeline on a CSI window.

    Parameters:
        csi_window: Raw CSI matrix of shape (n_samples, 128).
                    Each row contains 128 imaginary/real values across 64 subcarriers.
        fs:               Sampling frequency in Hz.
        bandpass_lowcut:  Lower cutoff frequency in Hz.
        bandpass_highcut: Upper cutoff frequency in Hz.
        bandpass_order:   Butterworth filter order.

    Returns:
        breathing_signal: Cleaned 1D respiration signal time series.
    """
    # Step 1: Extract magnitude per packet -> (n_samples, 64)
    amplitude_matrix = np.array([extract_amplitude(row) for row in csi_window])

    # Step 2: Hampel filter across subcarrier channels for spike removal
    for i in range(amplitude_matrix.shape[1]):
        amplitude_matrix[:, i] = hampel_filter(amplitude_matrix[:, i])

    # Step 3: PCA to extract 1st principal component -> (n_samples,)
    pc1 = apply_pca(amplitude_matrix)

    # Step 4: Band-pass filter to isolate respiration frequency band
    breathing_signal = bandpass_filter(
        pc1,
        fs=fs,
        lowcut=bandpass_lowcut,
        highcut=bandpass_highcut,
        order=bandpass_order,
    )

    return breathing_signal
