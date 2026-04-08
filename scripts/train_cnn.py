"""Train 1D CNN respiration model from CSI datasets and export ONNX artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from itertools import product
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit, train_test_split

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from edge.src.processor import process_window


@dataclass
class TrainConfig:
    dataset_dir: str
    models_dir: str
    sampling_rate: float = 100.0
    window_seconds: int = 30
    step_seconds: int = 5
    epochs: int = 25
    batch_size: int = 16
    max_windows_per_file: int = 6
    learning_rate: float = 3e-4
    dropout: float = 0.2
    huber_delta: float = 0.2
    bandpass_lowcut: float = 0.1
    bandpass_highcut: float = 0.5
    bandpass_order: int = 4
    target_global_mae_bpm: float = 3.0
    random_seed: int = 42
    split_mode: str = "random"
    test_size: float = 0.2
    export_onnx: bool = True
    save_model: bool = True


@dataclass
class DatasetBundle:
    X: np.ndarray
    y: np.ndarray
    scenarios: np.ndarray
    subjects: np.ndarray
    source_files: np.ndarray
    file_summary_df: pd.DataFrame
    window_feature_df: pd.DataFrame


SWEEP_PARAM_CASTERS: dict[str, Any] = {
    "epochs": int,
    "batch_size": int,
    "max_windows_per_file": int,
    "learning_rate": float,
    "dropout": float,
    "huber_delta": float,
    "bandpass_lowcut": float,
    "bandpass_highcut": float,
    "bandpass_order": int,
    "target_global_mae_bpm": float,
}

DATASET_PARAM_KEYS = {
    "sampling_rate",
    "window_seconds",
    "step_seconds",
    "max_windows_per_file",
    "bandpass_lowcut",
    "bandpass_highcut",
    "bandpass_order",
}

FEATURE_COLUMNS = [
    "signal_std",
    "signal_rms",
    "signal_ptp",
    "zero_crossing_rate",
    "dominant_bpm_fft",
]


def parse_bpm_from_filename(path: str) -> float:
    match = re.search(r"BPM(\d+)", os.path.basename(path), re.IGNORECASE)
    if not match:
        raise ValueError(f"Missing BPM tag in filename: {os.path.basename(path)}")
    return float(match.group(1))


def parse_scenario_from_filename(path: str) -> str:
    lower_name = os.path.basename(path).lower()
    if "apnea" in lower_name:
        return "Apnea"
    if "slow" in lower_name:
        return "Slow"
    if "fast" in lower_name:
        return "Fast"
    if "noise" in lower_name:
        return "Noise"
    return "Normal"


def parse_subject_from_filename(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    subject = stem.split("_", 1)[0].strip()
    if not subject:
        raise ValueError(f"Missing subject tag in filename: {os.path.basename(path)}")
    return subject


def parse_csi_payload(payload: str) -> np.ndarray | None:
    match = re.search(r"\[([-\d ]+)\]", str(payload))
    if not match:
        return None
    try:
        values = list(map(int, match.group(1).split()))
    except ValueError:
        return None
    if len(values) < 128:
        return None
    return np.array(values[:128])


def load_one_csv(path: str) -> tuple[np.ndarray, int, int]:
    df = pd.read_csv(path, header=None, on_bad_lines="skip")
    total_rows = int(len(df))
    parsed = [parse_csi_payload(v) for v in df.iloc[:, -1]]
    rows = [x for x in parsed if x is not None]
    if not rows:
        return np.empty((0, 128), dtype=np.int32), total_rows, 0
    return np.vstack(rows), total_rows, len(rows)


def compute_signal_features(signal: np.ndarray, sampling_rate: float) -> dict[str, float]:
    centered = signal.astype(np.float32) - float(np.mean(signal))
    signal_std = float(np.std(centered))
    signal_rms = float(np.sqrt(np.mean(np.square(centered))))
    signal_ptp = float(np.ptp(centered))
    sign_changes = np.mean(np.diff(np.signbit(centered)).astype(np.float32)) if len(centered) > 1 else 0.0

    spectrum = np.abs(np.fft.rfft(centered))
    freqs = np.fft.rfftfreq(len(centered), d=1.0 / sampling_rate)
    breathing_band = (freqs >= 0.05) & (freqs <= 1.0)
    dominant_bpm_fft = 0.0
    if np.any(breathing_band):
        dominant_freq = float(freqs[breathing_band][np.argmax(spectrum[breathing_band])])
        dominant_bpm_fft = dominant_freq * 60.0

    return {
        "signal_std": round(signal_std, 6),
        "signal_rms": round(signal_rms, 6),
        "signal_ptp": round(signal_ptp, 6),
        "zero_crossing_rate": round(float(sign_changes), 6),
        "dominant_bpm_fft": round(dominant_bpm_fft, 6),
    }


def build_dataset(cfg: TrainConfig) -> DatasetBundle:
    window_size = int(cfg.sampling_rate * cfg.window_seconds)
    step_size = int(cfg.sampling_rate * cfg.step_seconds)

    csv_files = sorted(
        [os.path.join(cfg.dataset_dir, f) for f in os.listdir(cfg.dataset_dir) if f.lower().endswith(".csv")]
    )

    X_list: list[np.ndarray] = []
    y_list: list[float] = []
    scenario_list: list[str] = []
    subject_list: list[str] = []
    source_file_list: list[str] = []
    file_summary_rows: list[dict[str, Any]] = []
    window_feature_rows: list[dict[str, Any]] = []

    for path in csv_files:
        bpm = parse_bpm_from_filename(path)
        scenario = parse_scenario_from_filename(path)
        subject = parse_subject_from_filename(path)
        source_file = os.path.basename(path)
        csi, total_rows, valid_rows = load_one_csv(path)
        if len(csi) < window_size:
            file_summary_rows.append(
                {
                    "source_file": source_file,
                    "subject": subject,
                    "scenario": scenario,
                    "bpm": bpm,
                    "total_rows": total_rows,
                    "valid_rows": valid_rows,
                    "valid_ratio": round(valid_rows / max(total_rows, 1), 4),
                    "windows_produced": 0,
                }
            )
            continue

        produced = 0
        file_feature_rows: list[dict[str, float]] = []
        for start in range(0, len(csi) - window_size + 1, step_size):
            window = csi[start : start + window_size]
            signal = process_window(
                window,
                fs=cfg.sampling_rate,
                bandpass_lowcut=cfg.bandpass_lowcut,
                bandpass_highcut=cfg.bandpass_highcut,
                bandpass_order=cfg.bandpass_order,
            )
            signal = signal.astype(np.float32)
            # Per-window normalization helps stabilize model training across sessions.
            signal = (signal - np.mean(signal)) / max(np.std(signal), 1e-6)
            feature_row = compute_signal_features(signal, cfg.sampling_rate)
            X_list.append(signal)
            y_list.append(float(bpm))
            scenario_list.append(scenario)
            subject_list.append(subject)
            source_file_list.append(source_file)
            window_feature_rows.append(
                {
                    "source_file": source_file,
                    "subject": subject,
                    "scenario": scenario,
                    "bpm": bpm,
                    **feature_row,
                }
            )
            file_feature_rows.append(feature_row)
            produced += 1
            if cfg.max_windows_per_file > 0 and produced >= cfg.max_windows_per_file:
                break

        file_summary: dict[str, Any] = {
            "source_file": source_file,
            "subject": subject,
            "scenario": scenario,
            "bpm": bpm,
            "total_rows": total_rows,
            "valid_rows": valid_rows,
            "valid_ratio": round(valid_rows / max(total_rows, 1), 4),
            "windows_produced": produced,
        }
        if file_feature_rows:
            for feature_name in FEATURE_COLUMNS:
                values = [row[feature_name] for row in file_feature_rows]
                file_summary[f"{feature_name}_mean"] = round(float(np.mean(values)), 6)
        file_summary_rows.append(file_summary)

        print(f"[Train] {source_file} -> windows={produced}, label={bpm}")

    if not X_list:
        raise RuntimeError("No training windows were generated. Check dataset files.")

    return DatasetBundle(
        X=np.stack(X_list),
        y=np.array(y_list, dtype=np.float32),
        scenarios=np.array(scenario_list),
        subjects=np.array(subject_list),
        source_files=np.array(source_file_list),
        file_summary_df=pd.DataFrame(file_summary_rows),
        window_feature_df=pd.DataFrame(window_feature_rows),
    )


def build_cnn(input_len: int, cfg: TrainConfig):
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers

    tf.random.set_seed(cfg.random_seed)
    inputs = keras.Input(shape=(input_len, 1), name="breathing_signal")
    x = layers.Conv1D(16, 7, padding="same", activation="relu")(inputs)
    x = layers.BatchNormalization()(x)
    x = layers.MaxPooling1D(2)(x)

    x = layers.Conv1D(32, 5, padding="same", activation="relu")(x)
    x = layers.BatchNormalization()(x)
    x = layers.MaxPooling1D(2)(x)

    x = layers.Conv1D(64, 3, padding="same", activation="relu")(x)
    x = layers.GlobalAveragePooling1D()(x)
    x = layers.Dropout(cfg.dropout)(x)
    x = layers.Dense(32, activation="relu")(x)
    outputs = layers.Dense(1, activation="linear", name="bpm_norm")(x)

    model = keras.Model(inputs, outputs, name="respiration_cnn")
    model.compile(
        optimizer=keras.optimizers.Adam(cfg.learning_rate),
        loss=keras.losses.Huber(delta=cfg.huber_delta),
        metrics=[keras.metrics.MeanAbsoluteError()],
    )
    return model


def summarize_label_quality(file_summary_df: pd.DataFrame) -> dict[str, Any]:
    subject_rows: list[dict[str, Any]] = []
    for subject, frame in file_summary_df.groupby("subject", sort=True):
        subject_rows.append(
            {
                "subject": subject,
                "files": int(len(frame)),
                "scenarios": sorted(frame["scenario"].unique().tolist()),
                "bpms": sorted(float(v) for v in frame["bpm"].unique().tolist()),
            }
        )

    scenario_rows: list[dict[str, Any]] = []
    for scenario, frame in file_summary_df.groupby("scenario", sort=True):
        scenario_rows.append(
            {
                "scenario": scenario,
                "files": int(len(frame)),
                "subjects": sorted(frame["subject"].unique().tolist()),
                "bpms": sorted(float(v) for v in frame["bpm"].unique().tolist()),
            }
        )

    warnings: list[str] = []
    low_validity = file_summary_df[file_summary_df["valid_ratio"] < 0.95]
    if not low_validity.empty:
        warnings.extend(
            f"low_valid_ratio:{row.source_file}={row.valid_ratio:.4f}"
            for row in low_validity.itertuples(index=False)
        )

    zero_windows = file_summary_df[file_summary_df["windows_produced"] == 0]
    if not zero_windows.empty:
        warnings.extend(
            f"zero_windows:{row.source_file}"
            for row in zero_windows.itertuples(index=False)
        )

    inconsistent_subject_scenarios = (
        file_summary_df.groupby(["subject", "scenario"])["bpm"].nunique().reset_index(name="bpm_count")
    )
    inconsistent_subject_scenarios = inconsistent_subject_scenarios[
        inconsistent_subject_scenarios["bpm_count"] > 1
    ]
    if not inconsistent_subject_scenarios.empty:
        warnings.extend(
            f"subject_scenario_label_mismatch:{row.subject}:{row.scenario}"
            for row in inconsistent_subject_scenarios.itertuples(index=False)
        )

    return {
        "files": int(len(file_summary_df)),
        "subjects": subject_rows,
        "scenarios": scenario_rows,
        "warnings": warnings,
    }


def summarize_signal_features(window_feature_df: pd.DataFrame) -> dict[str, Any]:
    def _aggregate(frame: pd.DataFrame, group_column: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for group_value, group_frame in frame.groupby(group_column, sort=True):
            row: dict[str, Any] = {
                group_column: group_value,
                "windows": int(len(group_frame)),
            }
            for feature_name in FEATURE_COLUMNS:
                row[f"{feature_name}_mean"] = round(float(group_frame[feature_name].mean()), 6)
                row[f"{feature_name}_std"] = round(float(group_frame[feature_name].std(ddof=0)), 6)
            rows.append(row)
        return rows

    global_summary: dict[str, Any] = {"windows": int(len(window_feature_df))}
    for feature_name in FEATURE_COLUMNS:
        global_summary[f"{feature_name}_mean"] = round(float(window_feature_df[feature_name].mean()), 6)
        global_summary[f"{feature_name}_std"] = round(float(window_feature_df[feature_name].std(ddof=0)), 6)

    return {
        "global": global_summary,
        "by_scenario": _aggregate(window_feature_df, "scenario"),
        "by_subject": _aggregate(window_feature_df, "subject"),
    }


def choose_split_indices(bundle: DatasetBundle, cfg: TrainConfig) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    indices = np.arange(len(bundle.X))
    if cfg.split_mode == "random":
        train_idx, test_idx = train_test_split(
            indices,
            test_size=cfg.test_size,
            random_state=cfg.random_seed,
            stratify=bundle.y,
        )
        return train_idx, test_idx, {"mode": "random", "held_out_groups": []}

    if cfg.split_mode == "subject":
        groups = bundle.subjects
    elif cfg.split_mode == "scenario":
        groups = bundle.scenarios
    elif cfg.split_mode == "file":
        groups = bundle.source_files
    else:
        raise ValueError(f"Unsupported split mode: {cfg.split_mode}")

    unique_groups = np.unique(groups)
    if len(unique_groups) < 2:
        raise RuntimeError(f"Split mode '{cfg.split_mode}' needs at least two unique groups.")

    splitter = GroupShuffleSplit(n_splits=1, test_size=cfg.test_size, random_state=cfg.random_seed)
    train_idx, test_idx = next(splitter.split(indices, bundle.y, groups=groups))
    return train_idx, test_idx, {
        "mode": cfg.split_mode,
        "held_out_groups": sorted(np.unique(groups[test_idx]).tolist()),
    }


def summarize_split(bundle: DatasetBundle, train_idx: np.ndarray, test_idx: np.ndarray, split_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": split_info["mode"],
        "held_out_groups": split_info["held_out_groups"],
        "train_windows": int(len(train_idx)),
        "test_windows": int(len(test_idx)),
        "train_subjects": sorted(np.unique(bundle.subjects[train_idx]).tolist()),
        "test_subjects": sorted(np.unique(bundle.subjects[test_idx]).tolist()),
        "train_scenarios": sorted(np.unique(bundle.scenarios[train_idx]).tolist()),
        "test_scenarios": sorted(np.unique(bundle.scenarios[test_idx]).tolist()),
    }


def export_model_onnx(models_dir: str) -> None:
    onnx_path = os.path.join(models_dir, "respiration_model.onnx")
    saved_model_dir = os.path.join(models_dir, "respiration_saved_model")
    cmd = [
        sys.executable,
        "-m",
        "tf2onnx.convert",
        "--saved-model",
        saved_model_dir,
        "--output",
        onnx_path,
        "--opset",
        "13",
    ]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"tf2onnx failed: {completed.stderr.strip()}")


def persist_dataset_reports(
    cfg: TrainConfig,
    file_summary_df: pd.DataFrame,
    label_quality: dict[str, Any],
    signal_feature_summary: dict[str, Any],
) -> None:
    file_summary_df.to_csv(os.path.join(cfg.models_dir, "dataset_file_summary.csv"), index=False)
    with open(os.path.join(cfg.models_dir, "label_quality_report.json"), "w", encoding="utf-8") as fp:
        json.dump(label_quality, fp, indent=2)
    with open(os.path.join(cfg.models_dir, "signal_feature_summary.json"), "w", encoding="utf-8") as fp:
        json.dump(signal_feature_summary, fp, indent=2)


def train(cfg: TrainConfig, dataset: DatasetBundle | None = None, persist_artifacts: bool = True) -> dict:
    os.makedirs(cfg.models_dir, exist_ok=True)

    bundle = dataset or build_dataset(cfg)
    label_quality = summarize_label_quality(bundle.file_summary_df)
    signal_feature_summary = summarize_signal_features(bundle.window_feature_df)

    train_idx, test_idx, split_info = choose_split_indices(bundle, cfg)
    split_summary = summarize_split(bundle, train_idx, test_idx, split_info)

    X = bundle.X
    y = bundle.y
    bpm_min, bpm_max = float(y.min()), float(y.max())
    y_norm = (y - bpm_min) / max(1e-6, (bpm_max - bpm_min))

    X_train = X[train_idx][:, :, np.newaxis]
    X_test = X[test_idx][:, :, np.newaxis]
    y_train = y_norm[train_idx]
    y_test = y_norm[test_idx]
    scenario_test = bundle.scenarios[test_idx]
    subject_test = bundle.subjects[test_idx]

    np.random.seed(cfg.random_seed)

    model = build_cnn(X_train.shape[1], cfg)
    print(model.summary())

    from tensorflow import keras

    h5_path = os.path.join(cfg.models_dir, "respiration_model.h5")
    callbacks = [
        keras.callbacks.EarlyStopping(monitor="val_mean_absolute_error", patience=10, mode="min", restore_best_weights=True),
        keras.callbacks.ReduceLROnPlateau(monitor="val_mean_absolute_error", patience=5, mode="min", factor=0.5, min_lr=1e-5),
    ]

    history = model.fit(
        X_train,
        y_train,
        validation_split=0.2,
        epochs=cfg.epochs,
        batch_size=cfg.batch_size,
        verbose=1,
        callbacks=callbacks,
    )

    if persist_artifacts and cfg.save_model:
        model.save(h5_path, include_optimizer=False)
    test_loss, _test_mae_norm = model.evaluate(X_test, y_test, verbose=0)

    y_pred_norm = model.predict(X_test, verbose=0).flatten()
    bpm_range = max(1e-6, (bpm_max - bpm_min))
    y_true_bpm = y_test * bpm_range + bpm_min
    y_pred_bpm = y_pred_norm * bpm_range + bpm_min
    errors = y_pred_bpm - y_true_bpm

    test_mae_bpm = float(np.mean(np.abs(errors)))
    within_2bpm_pct = float(np.mean(np.abs(errors) <= 2.0) * 100.0)

    per_scenario_mae_bpm: dict[str, float] = {}
    for scenario in sorted(set(scenario_test.tolist())):
        idx = scenario_test == scenario
        if np.any(idx):
            per_scenario_mae_bpm[scenario] = round(float(np.mean(np.abs(errors[idx]))), 4)

    per_subject_mae_bpm: dict[str, float] = {}
    for subject in sorted(set(subject_test.tolist())):
        idx = subject_test == subject
        if np.any(idx):
            per_subject_mae_bpm[subject] = round(float(np.mean(np.abs(errors[idx]))), 4)

    failed_criteria: list[str] = []
    if test_mae_bpm > cfg.target_global_mae_bpm:
        failed_criteria.append(
            f"global_mae_bpm={test_mae_bpm:.4f} > target={cfg.target_global_mae_bpm:.4f}"
        )

    production_ready = len(failed_criteria) == 0

    if persist_artifacts:
        np.savez(
            os.path.join(cfg.models_dir, "training_history.npz"),
            loss=history.history.get("loss", []),
            val_loss=history.history.get("val_loss", []),
            mae=history.history.get("mean_absolute_error", history.history.get("mae", [])),
            val_mae=history.history.get("val_mean_absolute_error", history.history.get("val_mae", [])),
        )

        if cfg.export_onnx:
            saved_model_dir = os.path.join(cfg.models_dir, "respiration_saved_model")
            model.export(saved_model_dir)
            export_model_onnx(cfg.models_dir)

        persist_dataset_reports(cfg, bundle.file_summary_df, label_quality, signal_feature_summary)

    metadata = {
        "bpm_min": bpm_min,
        "bpm_max": bpm_max,
        "window_seconds": cfg.window_seconds,
        "step_seconds": cfg.step_seconds,
        "sampling_rate_hz": cfg.sampling_rate,
        "train_samples": int(X_train.shape[0]),
        "test_samples": int(X_test.shape[0]),
        "test_mse_norm": float(test_loss),
        "model_mae_bpm": round(test_mae_bpm, 4),
        "within_2bpm_pct": round(within_2bpm_pct, 2),
        "per_scenario_mae_bpm": per_scenario_mae_bpm,
        "per_subject_mae_bpm": per_subject_mae_bpm,
        "learning_rate": cfg.learning_rate,
        "dropout": cfg.dropout,
        "huber_delta": cfg.huber_delta,
        "bandpass_lowcut": cfg.bandpass_lowcut,
        "bandpass_highcut": cfg.bandpass_highcut,
        "bandpass_order": cfg.bandpass_order,
        "max_windows_per_file": cfg.max_windows_per_file,
        "split_summary": split_summary,
        "label_quality": label_quality,
        "signal_feature_summary": signal_feature_summary,
        "acceptance_criteria": {
            "global_mae_bpm_lte": cfg.target_global_mae_bpm,
            "mode": "global_only",
        },
        "production_ready": production_ready,
        "failed_criteria": failed_criteria,
        "export_onnx": cfg.export_onnx,
        "save_model": cfg.save_model,
    }
    if persist_artifacts:
        with open(os.path.join(cfg.models_dir, "model_metadata.json"), "w", encoding="utf-8") as fp:
            json.dump(metadata, fp, indent=2)

    print("[Train] Done")
    if production_ready:
        print("[Train] Production readiness: PASS")
    else:
        print("[Train] Production readiness: FAIL")
        for item in failed_criteria:
            print(f"  - {item}")
    print(json.dumps(metadata, indent=2))
    return metadata


def parse_sweep_specs(sweep_specs: list[str]) -> list[dict[str, Any]]:
    if not sweep_specs:
        return [{"max_windows_per_file": value} for value in [1, 2, 4, 6, 8, 12]]

    keys: list[str] = []
    values_per_key: list[list[Any]] = []
    for spec in sweep_specs:
        if "=" not in spec:
            raise ValueError(f"Invalid sweep spec '{spec}'. Expected key=v1,v2 format.")
        key, raw_values = spec.split("=", 1)
        key = key.strip()
        caster = SWEEP_PARAM_CASTERS.get(key)
        if caster is None:
            raise ValueError(f"Unsupported sweep parameter: {key}")
        values = [caster(part.strip()) for part in raw_values.split(",") if part.strip()]
        if not values:
            raise ValueError(f"Sweep parameter '{key}' does not contain any values.")
        keys.append(key)
        values_per_key.append(values)

    return [dict(zip(keys, combo)) for combo in product(*values_per_key)]


def dataset_cache_key(cfg: TrainConfig) -> tuple[Any, ...]:
    return (
        cfg.dataset_dir,
        cfg.sampling_rate,
        cfg.window_seconds,
        cfg.step_seconds,
        cfg.max_windows_per_file,
    )


def run_quick_sweep(base_cfg: TrainConfig, sweep_specs: list[str], materialize_best: bool) -> dict[str, Any]:
    os.makedirs(base_cfg.models_dir, exist_ok=True)

    candidates = parse_sweep_specs(sweep_specs)
    dataset_cache: dict[tuple[Any, ...], DatasetBundle] = {}
    results: list[dict[str, Any]] = []
    best_metadata: dict[str, Any] | None = None
    best_overrides: dict[str, Any] | None = None

    for index, overrides in enumerate(candidates, start=1):
        candidate_cfg = replace(base_cfg, **overrides, export_onnx=False, save_model=False)
        cache_key = dataset_cache_key(candidate_cfg)
        bundle = dataset_cache.get(cache_key)
        if bundle is None:
            bundle = build_dataset(candidate_cfg)
            dataset_cache[cache_key] = bundle

        print(f"[Sweep] Candidate {index}/{len(candidates)} -> {json.dumps(overrides, sort_keys=True)}")
        metadata = train(candidate_cfg, dataset=bundle, persist_artifacts=False)
        result_row = {
            "candidate": index,
            **overrides,
            "model_mae_bpm": metadata["model_mae_bpm"],
            "within_2bpm_pct": metadata["within_2bpm_pct"],
            "production_ready": metadata["production_ready"],
            "split_mode": candidate_cfg.split_mode,
            "held_out_groups": metadata["split_summary"]["held_out_groups"],
        }
        results.append(result_row)

        if best_metadata is None or metadata["model_mae_bpm"] < best_metadata["model_mae_bpm"]:
            best_metadata = metadata
            best_overrides = overrides

    results_df = pd.DataFrame(results).sort_values("model_mae_bpm", ascending=True)
    results_df.to_csv(os.path.join(base_cfg.models_dir, "sweep_results.csv"), index=False)
    with open(os.path.join(base_cfg.models_dir, "sweep_results.json"), "w", encoding="utf-8") as fp:
        json.dump(results_df.to_dict(orient="records"), fp, indent=2)

    summary: dict[str, Any] = {
        "candidates": len(results),
        "best_overrides": best_overrides,
        "best_result": best_metadata,
    }

    if materialize_best and best_overrides is not None:
        best_cfg = replace(base_cfg, **best_overrides)
        best_bundle = dataset_cache[dataset_cache_key(best_cfg)]
        summary["materialized_best"] = train(best_cfg, dataset=best_bundle, persist_artifacts=True)

    print("[Sweep] Done")
    print(json.dumps(summary, indent=2))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train CSI CNN model")
    parser.add_argument("--dataset-dir", default=os.path.join("ESP32-WiFi-Sensing-2", "datasets"))
    parser.add_argument("--models-dir", default=os.path.join("ESP32-WiFi-Sensing-2", "models"))
    parser.add_argument("--sampling-rate", type=float, default=100.0)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--window-seconds", type=int, default=30)
    parser.add_argument("--step-seconds", type=int, default=5)
    parser.add_argument("--max-windows-per-file", type=int, default=6)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--huber-delta", type=float, default=0.2)
    parser.add_argument("--bandpass-lowcut", type=float, default=0.1)
    parser.add_argument("--bandpass-highcut", type=float, default=0.5)
    parser.add_argument("--bandpass-order", type=int, default=4)
    parser.add_argument("--target-global-mae-bpm", type=float, default=3.0)
    parser.add_argument("--split-mode", choices=["random", "subject", "scenario", "file"], default="random")
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--skip-export-onnx", action="store_true")
    parser.add_argument("--skip-save-model", action="store_true")
    parser.add_argument("--quick-sweep", action="store_true")
    parser.add_argument(
        "--sweep",
        nargs="*",
        default=[],
        help="Grid specs like max_windows_per_file=2,4,6 learning_rate=0.0003,0.0002",
    )
    parser.add_argument("--materialize-best", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = TrainConfig(
        dataset_dir=args.dataset_dir,
        models_dir=args.models_dir,
        sampling_rate=args.sampling_rate,
        epochs=args.epochs,
        batch_size=args.batch_size,
        window_seconds=args.window_seconds,
        step_seconds=args.step_seconds,
        max_windows_per_file=args.max_windows_per_file,
        learning_rate=args.learning_rate,
        dropout=args.dropout,
        huber_delta=args.huber_delta,
        bandpass_lowcut=args.bandpass_lowcut,
        bandpass_highcut=args.bandpass_highcut,
        bandpass_order=args.bandpass_order,
        target_global_mae_bpm=args.target_global_mae_bpm,
        split_mode=args.split_mode,
        test_size=args.test_size,
        export_onnx=not args.skip_export_onnx and not args.quick_sweep,
        save_model=not args.skip_save_model and not args.quick_sweep,
    )
    if args.quick_sweep:
        run_quick_sweep(cfg, args.sweep, args.materialize_best)
    else:
        train(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
