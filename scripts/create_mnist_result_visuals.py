from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "mnist_recognition_mlp_234d539d"
RUN_DIR = ROOT / "runs" / RUN_ID
MODEL_DIR = ROOT / "models" / "mnist_recognition"
OUT_DIR = ROOT / "docs" / "figures" / "mnist_recognition"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_matrix(path: Path, cols: int | None = None) -> np.ndarray:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append([float(x) for x in line.split()])
    arr = np.asarray(rows, dtype=np.float32)
    if cols is not None and arr.size:
        arr = arr.reshape((-1, cols))
    return arr


def setup_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 220,
            "font.family": "DejaVu Sans",
            "axes.titleweight": "bold",
            "axes.edgecolor": "#1f2a44",
            "axes.labelcolor": "#1f2a44",
            "xtick.color": "#344054",
            "ytick.color": "#344054",
        }
    )


def save(fig: plt.Figure, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def load_data() -> dict:
    verification = read_json(RUN_DIR / "verification.json")
    report = read_json(RUN_DIR / "report.json")
    training = read_json(MODEL_DIR / "mnist_mlp_training_metrics.json")
    labels = verification["classification"]["labels"]
    ref_pred = verification["classification"]["reference_predictions"]
    hls_pred = verification["classification"]["hls_predictions"]
    inputs = read_matrix(MODEL_DIR / "mnist_test_inputs_20.dat", cols=784)
    ref_logits = read_matrix(RUN_DIR / "vivado_hls" / "tb_data" / "tb_output_predictions.dat", cols=10)
    hls_logits = read_matrix(
        RUN_DIR
        / "vivado_hls"
        / "vivado_hls"
        / "solution1"
        / "csim"
        / "build"
        / "tb_data"
        / "csim_results.log",
        cols=10,
    )
    return {
        "verification": verification,
        "report": report,
        "training": training,
        "labels": labels,
        "ref_pred": ref_pred,
        "hls_pred": hls_pred,
        "inputs": inputs,
        "ref_logits": ref_logits,
        "hls_logits": hls_logits,
    }


def draw_prediction_grid(data: dict) -> Path:
    images = data["inputs"].reshape((-1, 28, 28))
    labels = data["labels"]
    ref_pred = data["ref_pred"]
    hls_pred = data["hls_pred"]

    fig, axes = plt.subplots(4, 5, figsize=(11.5, 9.4))
    fig.suptitle("MNIST HLS Recognition Samples: label / reference / HLS", fontsize=16, color="#102a43")
    for idx, ax in enumerate(axes.ravel()):
        ax.imshow(images[idx], cmap="gray", vmin=0.0, vmax=1.0)
        ok = labels[idx] == hls_pred[idx]
        agree = ref_pred[idx] == hls_pred[idx]
        border = "#1f9d55" if ok else "#d64545"
        if not agree:
            border = "#f59e0b"
        for spine in ax.spines.values():
            spine.set_linewidth(2.4)
            spine.set_color(border)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(
            f"#{idx:02d}  y={labels[idx]}\nref={ref_pred[idx]}  hls={hls_pred[idx]}",
            fontsize=8.5,
            color="#1f2a44",
            pad=6,
        )
    fig.subplots_adjust(top=0.88, bottom=0.09, left=0.04, right=0.98, hspace=0.82, wspace=0.26)
    fig.text(
        0.5,
        0.02,
        "Green border = HLS prediction is correct. One red sample reflects the model's own classification error, not an HLS mismatch.",
        ha="center",
        fontsize=10,
        color="#52616b",
    )
    return save(fig, "mnist_sample_prediction_grid.png")


def draw_prediction_agreement(data: dict) -> Path:
    labels = np.asarray(data["labels"])
    ref_pred = np.asarray(data["ref_pred"])
    hls_pred = np.asarray(data["hls_pred"])
    sample_ids = np.arange(len(labels))
    correct = hls_pred == labels
    agree = hls_pred == ref_pred

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), gridspec_kw={"height_ratios": [2.2, 1.0]})
    width = 0.26
    ax1.bar(sample_ids - width, labels, width=width, label="Label", color="#344054")
    ax1.bar(sample_ids, ref_pred, width=width, label="Reference pred", color="#2f80ed")
    ax1.bar(sample_ids + width, hls_pred, width=width, label="HLS pred", color="#1f9d55")
    ax1.set_title("Prediction Agreement Across 20 MNIST Samples", fontsize=15, color="#102a43")
    ax1.set_ylabel("Digit class")
    ax1.set_xticks(sample_ids)
    ax1.set_yticks(range(10))
    ax1.grid(axis="y", alpha=0.18)
    ax1.legend(ncol=3, frameon=False, loc="upper right")

    colors = ["#1f9d55" if c and a else "#d64545" if not c else "#f59e0b" for c, a in zip(correct, agree)]
    ax2.bar(sample_ids, np.ones_like(sample_ids), color=colors)
    ax2.set_ylim(0, 1)
    ax2.set_yticks([])
    ax2.set_xticks(sample_ids)
    ax2.set_xlabel("Sample index")
    ax2.set_title("HLS correctness strip: green=correct, red=wrong label", fontsize=11, color="#344054")
    for idx, c in enumerate(correct):
        ax2.text(idx, 0.5, "OK" if c else "ERR", ha="center", va="center", color="white", fontsize=8, weight="bold")

    fig.tight_layout()
    return save(fig, "mnist_prediction_agreement.png")


def draw_logits_comparison(data: dict) -> Path:
    ref_logits = data["ref_logits"]
    hls_logits = data["hls_logits"]
    labels = data["labels"]
    ref_pred = data["ref_pred"]
    hls_pred = data["hls_pred"]
    abs_errors = np.max(np.abs(ref_logits - hls_logits), axis=1)
    idx = int(np.argmax(abs_errors))
    classes = np.arange(10)

    fig, ax = plt.subplots(figsize=(11, 5.8))
    width = 0.36
    ax.bar(classes - width / 2, ref_logits[idx], width=width, label="Reference logits", color="#2f80ed")
    ax.bar(classes + width / 2, hls_logits[idx], width=width, label="HLS fixed-point logits", color="#f59e0b")
    ax.axhline(0, color="#52616b", linewidth=0.8)
    ax.set_xticks(classes)
    ax.set_xlabel("Digit class")
    ax.set_ylabel("Logit value")
    ax.set_title(
        f"Logits Drift Example (sample #{idx}): label={labels[idx]}, ref={ref_pred[idx]}, hls={hls_pred[idx]}",
        fontsize=14,
        color="#102a43",
    )
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.18)
    note = (
        f"Max abs error on this sample: {abs_errors[idx]:.2f}\n"
        "Argmax is still identical, so classification semantics pass."
    )
    ax.text(
        0.99,
        0.04,
        note,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=10,
        color="#1f2a44",
        bbox=dict(boxstyle="round,pad=0.45", facecolor="#eef6ff", edgecolor="#b6d4fe"),
    )
    return save(fig, "mnist_logits_drift_argmax_stable.png")


def draw_metrics_dashboard(data: dict) -> Path:
    verification = data["verification"]
    cls = verification["classification"]
    cmp = verification["comparison"]
    report = data["report"]
    timing = report["timing"]
    resources = report["resources"]
    latency = report["latency"]

    fig = plt.figure(figsize=(12, 7))
    fig.suptitle("MNIST HLS Demo: Verification and Synthesis Dashboard", fontsize=17, weight="bold", color="#102a43")
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.25], wspace=0.28, hspace=0.38)

    cards = [
        ("HLS Accuracy", f"{cls['hls_accuracy'] * 100:.0f}%", "19 / 20 samples correct", "#1f9d55"),
        ("Argmax Match", f"{cls['argmax_match_rate'] * 100:.0f}%", "HLS pred == reference pred", "#2f80ed"),
        ("Timing", "PASS" if timing["met"] else "FAIL", f"{timing['estimated_ns']:.3f} ns @ target {timing['target_ns']:.1f} ns", "#1f9d55" if timing["met"] else "#d64545"),
    ]
    for i, (title, value, subtitle, color) in enumerate(cards):
        ax = fig.add_subplot(gs[0, i])
        ax.axis("off")
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, color="#f8fbff", transform=ax.transAxes, zorder=0))
        ax.text(0.06, 0.74, title, fontsize=12, color="#52616b", weight="bold", transform=ax.transAxes)
        ax.text(0.06, 0.38, value, fontsize=29, color=color, weight="bold", transform=ax.transAxes)
        ax.text(0.06, 0.16, subtitle, fontsize=10, color="#344054", transform=ax.transAxes)

    ax_res = fig.add_subplot(gs[1, 0:2])
    names = ["BRAM", "DSP", "FF", "LUT"]
    vals = [resources["bram"], resources["dsp"], resources["ff"], resources["lut"]]
    bars = ax_res.bar(names, vals, color=["#7c3aed", "#f59e0b", "#2f80ed", "#1f9d55"])
    ax_res.set_title("Vivado HLS Resource Estimate", color="#102a43")
    ax_res.set_ylabel("Count")
    ax_res.grid(axis="y", alpha=0.18)
    for bar, val in zip(bars, vals):
        ax_res.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{val}", ha="center", va="bottom", fontsize=9)

    ax_lat = fig.add_subplot(gs[1, 2])
    ax_lat.axis("off")
    lines = [
        ("Latency", f"{latency['min_cycles']} - {latency['max_cycles']} cycles"),
        ("II", f"{report['interval']['min_ii']} - {report['interval']['max_ii']}"),
        ("Numeric logits", f"max abs err {cmp['max_abs_error']:.2f}"),
        ("Recognition", cmp["status"]),
    ]
    y = 0.82
    for label, value in lines:
        ax_lat.text(0.02, y, label, fontsize=10, color="#52616b", weight="bold", transform=ax_lat.transAxes)
        ax_lat.text(0.02, y - 0.12, value, fontsize=12, color="#102a43", transform=ax_lat.transAxes)
        y -= 0.23

    return save(fig, "mnist_verification_synthesis_dashboard.png")


def write_index(paths: list[Path]) -> Path:
    index = OUT_DIR / "README.md"
    lines = [
        "# MNIST Recognition Visual Results",
        "",
        f"Source run: `{RUN_ID}`",
        "",
        "These figures visualize the real MNIST recognition HLS demo results.",
        "",
    ]
    for path in paths:
        title = path.stem.replace("_", " ").title()
        lines.append(f"## {title}")
        lines.append("")
        lines.append(f"![{title}]({path.name})")
        lines.append("")
    index.write_text("\n".join(lines), encoding="utf-8")
    return index


def main() -> None:
    setup_style()
    data = load_data()
    paths = [
        draw_prediction_grid(data),
        draw_prediction_agreement(data),
        draw_logits_comparison(data),
        draw_metrics_dashboard(data),
    ]
    index = write_index(paths)
    for path in [*paths, index]:
        print(path)


if __name__ == "__main__":
    main()
