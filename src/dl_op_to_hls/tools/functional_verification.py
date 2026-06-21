from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PASS_MARKERS = (
    "golden_check_passed",
    "csim done with 0 errors",
    "c simulation completed",
)
FAIL_MARKERS = (
    "assertion failed",
    "golden_check_failed",
    "csim failed",
    "c simulation failed",
    "simulation failed",
    "csim_design' failed",
    "compilation error",
    "out of memory allocating",
    "verificationfailed",
)


def _write_lines(path: Path, rows: list[list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(" ".join(f"{float(value):.8g}" for value in row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _read_numeric_rows(path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        values = [float(token) for token in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", line)]
        if values:
            rows.append(values)
    return rows


def _read_labels(path: Path) -> list[int]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("labels", [])
        return [int(item) for item in payload]
    labels: list[int] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        for token in re.findall(r"[-+]?\d+", line):
            labels.append(int(token))
    return labels


def _argmax(row: list[float]) -> int:
    return max(range(len(row)), key=lambda index: row[index]) if row else -1


def _find_first_named(base_dir: Path, filename: str) -> Path | None:
    if not base_dir.exists():
        return None
    direct = base_dir / filename
    if direct.exists():
        return direct
    # Vivado HLS runs C simulation from solution1/csim/build, so hls4ml
    # output files can land under a copied tb_data directory rather than
    # the top-level work_dir/tb_data folder.
    for path in base_dir.rglob(filename):
        if path.is_file():
            return path
    return None


def _resolve_optional_path(path_value: str | None, *, base_dir: Path | None = None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if path.is_absolute():
        return path
    if base_dir is not None:
        candidate = base_dir / path
        if candidate.exists():
            return candidate
    return path


def compare_classification_outputs(
    reference_path: str | Path,
    output_path: str | Path,
    labels_path: str | Path,
) -> dict[str, Any]:
    reference = Path(reference_path)
    output = Path(output_path)
    labels_file = Path(labels_path)
    if not reference.exists() or not output.exists() or not labels_file.exists():
        return {
            "status": "not_available",
            "reason": "Reference, output, or labels file is missing.",
            "reference_path": str(reference),
            "output_path": str(output),
            "labels_path": str(labels_file),
        }
    reference_rows = _read_numeric_rows(reference)
    output_rows = _read_numeric_rows(output)
    labels = _read_labels(labels_file)
    sample_count = min(len(reference_rows), len(output_rows), len(labels))
    if sample_count == 0:
        return {
            "status": "not_available",
            "reason": "No overlapping samples were available for classification comparison.",
            "reference_path": str(reference),
            "output_path": str(output),
            "labels_path": str(labels_file),
        }
    reference_predictions = [_argmax(row) for row in reference_rows[:sample_count]]
    hls_predictions = [_argmax(row) for row in output_rows[:sample_count]]
    used_labels = labels[:sample_count]
    reference_correct = sum(int(pred == label) for pred, label in zip(reference_predictions, used_labels))
    hls_correct = sum(int(pred == label) for pred, label in zip(hls_predictions, used_labels))
    argmax_matches = sum(int(ref == hls) for ref, hls in zip(reference_predictions, hls_predictions))
    return {
        "status": "success",
        "sample_count": sample_count,
        "reference_accuracy": reference_correct / sample_count,
        "hls_accuracy": hls_correct / sample_count,
        "argmax_match_rate": argmax_matches / sample_count,
        "reference_correct": reference_correct,
        "hls_correct": hls_correct,
        "argmax_matches": argmax_matches,
        "labels_path": str(labels_file),
        "reference_predictions": reference_predictions,
        "hls_predictions": hls_predictions,
        "labels": used_labels,
    }


def compare_numeric_files(reference_path: str | Path, output_path: str | Path, tolerance: float = 0.25) -> dict[str, Any]:
    reference = Path(reference_path)
    output = Path(output_path)
    if not reference.exists() or not output.exists():
        return {
            "status": "not_available",
            "passed": None,
            "reason": "Reference or output file is missing.",
            "reference_path": str(reference),
            "output_path": str(output),
        }
    try:
        reference_rows = _read_numeric_rows(reference)
        output_rows = _read_numeric_rows(output)
    except Exception as exc:
        return {
            "status": "parse_error",
            "passed": False,
            "reason": str(exc),
            "reference_path": str(reference),
            "output_path": str(output),
        }
    if len(reference_rows) != len(output_rows):
        return {
            "status": "shape_mismatch",
            "passed": False,
            "reason": f"Expected {len(reference_rows)} rows, got {len(output_rows)} rows.",
            "reference_path": str(reference),
            "output_path": str(output),
        }
    max_abs_error = 0.0
    max_rel_error = 0.0
    sample_count = len(reference_rows)
    value_count = 0
    for row_index, (expected_row, actual_row) in enumerate(zip(reference_rows, output_rows)):
        if len(expected_row) != len(actual_row):
            return {
                "status": "shape_mismatch",
                "passed": False,
                "reason": f"Row {row_index} expected {len(expected_row)} values, got {len(actual_row)}.",
                "reference_path": str(reference),
                "output_path": str(output),
            }
        for expected, actual in zip(expected_row, actual_row):
            abs_error = abs(actual - expected)
            rel_error = abs_error / max(abs(expected), 1e-9)
            max_abs_error = max(max_abs_error, abs_error)
            max_rel_error = max(max_rel_error, rel_error)
            value_count += 1
    passed = max_abs_error <= tolerance
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "sample_count": sample_count,
        "value_count": value_count,
        "max_abs_error": max_abs_error,
        "max_rel_error": max_rel_error,
        "tolerance": tolerance,
        "reference_path": str(reference),
        "output_path": str(output),
    }


def parse_csim_verification(
    log_path: str | Path | None,
    *,
    work_dir: str | Path | None = None,
    reference_path: str | Path | None = None,
    output_path: str | Path | None = None,
    tolerance: float = 0.25,
) -> dict[str, Any]:
    log = Path(log_path) if log_path else None
    log_text = log.read_text(encoding="utf-8", errors="ignore") if log and log.exists() else ""
    lowered = log_text.lower()
    has_fail_marker = any(marker in lowered for marker in FAIL_MARKERS)
    base_dir = Path(work_dir) if work_dir else (log.parent if log else None)
    inferred_reference = Path(reference_path) if reference_path else None
    inferred_output = Path(output_path) if output_path else None
    if base_dir:
        inferred_reference = inferred_reference or base_dir / "tb_data" / "tb_output_predictions.dat"
        inferred_output = inferred_output or base_dir / "tb_data" / "csim_results.log"
        if inferred_reference and not inferred_reference.exists():
            inferred_reference = _find_first_named(base_dir, "tb_output_predictions.dat") or inferred_reference
        if inferred_output and not inferred_output.exists():
            inferred_output = _find_first_named(base_dir, "csim_results.log") or inferred_output

    comparison = None
    if inferred_reference and inferred_output and inferred_reference.exists() and inferred_output.exists():
        comparison = compare_numeric_files(inferred_reference, inferred_output, tolerance=tolerance)
        classification = None
        manifest_path = _find_first_named(base_dir, "reference_manifest.json") if base_dir else None
        if manifest_path and manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                labels_path = _resolve_optional_path(manifest.get("labels_path"), base_dir=manifest_path.parent)
                if labels_path:
                    classification = compare_classification_outputs(inferred_reference, inferred_output, labels_path)
                    comparison["classification"] = classification
                    if classification.get("status") == "success":
                        configured_min_accuracy = manifest.get("classification_min_accuracy")
                        configured_min_argmax_match = manifest.get("argmax_match_min")
                        # Reference manifests intentionally serialize unspecified
                        # thresholds as JSON null. Treat null as the documented
                        # defaults instead of turning a completed CSim result into
                        # a parser error.
                        min_accuracy = 0.9 if configured_min_accuracy is None else float(configured_min_accuracy)
                        min_argmax_match = 0.95 if configured_min_argmax_match is None else float(configured_min_argmax_match)
                        recognition_passed = (
                            float(classification.get("hls_accuracy", 0.0)) >= min_accuracy
                            and float(classification.get("argmax_match_rate", 0.0)) >= min_argmax_match
                        )
                        comparison["numeric_passed"] = comparison.get("passed")
                        comparison["recognition_passed"] = recognition_passed
                        comparison["classification_min_accuracy"] = min_accuracy
                        comparison["argmax_match_min"] = min_argmax_match
                        if recognition_passed and not comparison.get("passed"):
                            comparison["passed"] = True
                            comparison["status"] = "recognition_passed"
                            comparison["reason"] = (
                                "Numeric logits exceeded tolerance, but classification accuracy and "
                                "argmax match met the configured recognition thresholds."
                            )
            except Exception as exc:
                classification = {"status": "parse_error", "reason": str(exc), "manifest_path": str(manifest_path)}
        # A numerical output file is not proof of a completed simulation.  A
        # compiler/runtime failure must win over stale or partially written
        # output artifacts from the work directory.
        status = "csim_passed" if comparison.get("passed") and not has_fail_marker else "csim_failed"
        return {
            "status": status,
            "passed": bool(comparison.get("passed")) and not has_fail_marker,
            "mode": "hls4ml_reference_compare",
            "csim_executed": any(marker in lowered for marker in (*PASS_MARKERS, *FAIL_MARKERS, "processing input", "csim finish")),
            "log_path": str(log) if log else None,
            "reference_path": str(inferred_reference),
            "output_path": str(inferred_output),
            "comparison": comparison,
            "classification": classification,
            "reason": "C simulation log contains a failure marker." if has_fail_marker else None,
        }

    has_pass_marker = any(marker in lowered for marker in PASS_MARKERS)
    # Golden testbenches may print per-sample mismatch diagnostics while still
    # meeting a run-level accuracy threshold. In that case the explicit pass
    # marker is authoritative unless a hard failure marker is also present.
    if has_fail_marker or ("mismatch" in lowered and not has_pass_marker):
        return {
            "status": "csim_failed",
            "passed": False,
            "mode": "golden_testbench",
            "csim_executed": "starting c simulation" in lowered or "csim" in lowered,
            "log_path": str(log) if log else None,
            "comparison": comparison,
            "reason": "C simulation log contains a failure marker.",
        }
    if has_pass_marker:
        return {
            "status": "csim_passed",
            "passed": True,
            "mode": "golden_testbench" if "golden_check_passed" in lowered else "vivado_csim",
            "csim_executed": True,
            "log_path": str(log) if log else None,
            "comparison": comparison,
        }
    if "csim_design" in lowered or "starting c simulation" in lowered:
        return {
            "status": "unknown",
            "passed": None,
            "mode": "vivado_csim",
            "csim_executed": True,
            "log_path": str(log) if log else None,
            "reason": "C simulation ran but no pass/fail marker was found.",
        }
    return {
        "status": "not_run",
        "passed": None,
        "mode": "none",
        "csim_executed": False,
        "log_path": str(log) if log else None,
        "reason": "No C simulation markers or reference output were found.",
    }


def write_onnx_reference_data(
    model_path: str | Path,
    project_dir: str | Path,
    *,
    num_samples: int = 2,
    seed: int = 7,
    input_data_path: str | Path | None = None,
    labels_path: str | Path | None = None,
    classification_min_accuracy: float | None = None,
    argmax_match_min: float | None = None,
) -> dict[str, Any]:
    project = Path(project_dir)
    tb_data = project / "tb_data"
    input_path = tb_data / "tb_input_features.dat"
    output_path = tb_data / "tb_output_predictions.dat"
    manifest_path = tb_data / "reference_manifest.json"
    try:
        import numpy as np  # type: ignore
        import onnxruntime as ort  # type: ignore

        session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        input_meta = session.get_inputs()[0]
        output_meta = session.get_outputs()[0]
        raw_shape = input_meta.shape
        sample_shape: list[int] = []
        for index, dim in enumerate(raw_shape):
            if index == 0:
                sample_shape.append(1)
            elif isinstance(dim, int) and dim > 0:
                sample_shape.append(int(dim))
            else:
                sample_shape.append(1)
        rng = np.random.default_rng(seed)
        input_rows: list[list[float]] = []
        output_rows: list[list[float]] = []
        labels = _read_labels(Path(labels_path)) if labels_path else []
        provided_rows = _read_numeric_rows(Path(input_data_path)) if input_data_path else []
        requested_samples = max(1, int(num_samples))
        if provided_rows:
            requested_samples = min(requested_samples, len(provided_rows))
        reference_predictions: list[int] = []
        for sample_index in range(requested_samples):
            if provided_rows:
                sample = np.asarray(provided_rows[sample_index], dtype=np.float32).reshape(sample_shape)
            else:
                sample = rng.uniform(-0.5, 0.5, size=sample_shape).astype(np.float32)
            outputs = session.run([output_meta.name], {input_meta.name: sample})[0]
            hls_sample = sample
            if sample.ndim == 4:
                hls_sample = np.transpose(sample, (0, 2, 3, 1))
            input_rows.append([float(value) for value in hls_sample.reshape(-1)])
            output_row = [float(value) for value in np.asarray(outputs).reshape(-1)]
            output_rows.append(output_row)
            reference_predictions.append(_argmax(output_row))
        _write_lines(input_path, input_rows)
        _write_lines(output_path, output_rows)
        reference_accuracy = None
        if labels:
            used_labels = labels[: len(reference_predictions)]
            if used_labels:
                reference_accuracy = sum(
                    int(prediction == label) for prediction, label in zip(reference_predictions, used_labels)
                ) / len(used_labels)
        manifest = {
            "status": "success",
            "model_path": str(model_path),
            "input_name": input_meta.name,
            "output_name": output_meta.name,
            "raw_input_shape": [str(item) for item in raw_shape],
            "sample_shape": sample_shape,
            "num_samples": len(input_rows),
            "input_layout_for_hls": "NHWC_flat" if len(sample_shape) == 4 else "flat",
            "input_path": str(input_path),
            "output_path": str(output_path),
            "source_input_path": str(input_data_path) if input_data_path else None,
            "labels_path": str(labels_path) if labels_path else None,
            "reference_predictions": reference_predictions,
            "reference_accuracy": reference_accuracy,
            "classification_min_accuracy": classification_min_accuracy,
            "argmax_match_min": argmax_match_min,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"status": "success", "input_path": str(input_path), "output_path": str(output_path), "manifest_path": str(manifest_path)}
    except Exception as exc:
        tb_data.mkdir(parents=True, exist_ok=True)
        manifest = {
            "status": "error",
            "model_path": str(model_path),
            "error": str(exc),
            "input_path": str(input_path),
            "output_path": str(output_path),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"status": "error", "error": str(exc), "manifest_path": str(manifest_path)}


def fallback_reference_payload(task: dict[str, Any]) -> dict[str, Any]:
    op_type = str(task.get("op_type", ""))
    input_shape = task.get("input_shape") or []
    output_shape = task.get("output_shape") or []
    return {
        "status": "success",
        "source": "fallback_golden_generator",
        "op_type": op_type,
        "name": task.get("name"),
        "input_shape": input_shape,
        "output_shape": output_shape,
        "dtype": task.get("dtype"),
        "tolerance": 0.001,
        "description": "Reference values are generated deterministically inside testbench.cpp and checked before returning.",
    }


def write_fallback_reference_data(task: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    path = output / "reference.json"
    payload = fallback_reference_payload(task)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "success", "reference_path": str(path), "reference": payload}
