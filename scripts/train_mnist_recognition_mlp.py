from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train a small real MNIST MLP and export ONNX/reference data for the HLS recognition demo."
    )
    parser.add_argument("--output-dir", default="models/mnist_recognition", help="Directory for weights, ONNX, and reference data.")
    parser.add_argument("--data-dir", default="models/mnist_recognition/data", help="MNIST download/cache directory.")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--eval-samples", type=int, default=5000)
    parser.add_argument("--reference-samples", type=int, default=20)
    parser.add_argument("--target-accuracy", type=float, default=0.90)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--opset", type=int, default=13)
    return parser


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _write_dat(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(" ".join(f"{float(value):.8g}" for value in row) for row in rows) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = build_parser().parse_args(argv)
    random.seed(args.seed)

    try:
        import numpy as np
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
        from torch.utils.data import DataLoader, Subset
        from torchvision import datasets, transforms
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[error] training dependencies are unavailable: {exc}")
        return 2

    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    class MnistRecognitionMLP(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.fc1 = nn.Linear(784, 64)
            self.fc2 = nn.Linear(64, 32)
            self.fc3 = nn.Linear(32, 10)

        def forward(self, x):
            x = x.reshape(x.shape[0], 784)
            x = F.relu(self.fc1(x))
            x = F.relu(self.fc2(x))
            return self.fc3(x)

    transform = transforms.Compose([transforms.ToTensor()])
    train_ds = datasets.MNIST(root=args.data_dir, train=True, download=True, transform=transform)
    test_ds = datasets.MNIST(root=args.data_dir, train=False, download=True, transform=transform)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    eval_size = min(int(args.eval_samples), len(test_ds))
    eval_subset = Subset(test_ds, list(range(eval_size)))
    eval_loader = DataLoader(eval_subset, batch_size=args.batch_size, shuffle=False)

    model = MnistRecognitionMLP()
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    loss_fn = nn.CrossEntropyLoss()

    history: list[dict[str, float | int]] = []
    best_accuracy = 0.0
    for epoch in range(1, int(args.epochs) + 1):
        model.train()
        total_loss = 0.0
        total_seen = 0
        for images, labels in train_loader:
            inputs = images.reshape(images.shape[0], 784)
            logits = model(inputs)
            loss = loss_fn(logits, labels)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * int(labels.numel())
            total_seen += int(labels.numel())

        model.eval()
        correct = 0
        seen = 0
        with torch.no_grad():
            for images, labels in eval_loader:
                inputs = images.reshape(images.shape[0], 784)
                predictions = model(inputs).argmax(dim=1)
                correct += int((predictions == labels).sum().item())
                seen += int(labels.numel())
        accuracy = correct / max(seen, 1)
        best_accuracy = max(best_accuracy, accuracy)
        item = {"epoch": epoch, "train_loss": total_loss / max(total_seen, 1), "eval_accuracy": accuracy}
        history.append(item)
        print(f"[train] epoch={epoch} loss={item['train_loss']:.4f} eval_accuracy={accuracy:.4f}")
        if accuracy >= args.target_accuracy and epoch >= 2:
            break

    model.eval()
    state_path = output_dir / "mnist_mlp_trained.pt"
    onnx_path = output_dir / "mnist_mlp_trained.onnx"
    metrics_path = output_dir / "mnist_mlp_training_metrics.json"
    input_dat_path = output_dir / f"mnist_test_inputs_{args.reference_samples}.dat"
    labels_path = output_dir / f"mnist_test_labels_{args.reference_samples}.json"
    predictions_path = output_dir / f"mnist_test_python_predictions_{args.reference_samples}.json"

    torch.save(model.state_dict(), state_path)
    sample = torch.zeros(1, 784, dtype=torch.float32)
    torch.onnx.export(
        model,
        sample,
        str(onnx_path),
        export_params=True,
        input_names=["model_input"],
        output_names=["logits"],
        opset_version=int(args.opset),
    )

    ref_count = min(int(args.reference_samples), len(test_ds))
    ref_rows = []
    ref_labels = []
    ref_predictions = []
    with torch.no_grad():
        for index in range(ref_count):
            image, label = test_ds[index]
            flat = image.reshape(784).to(torch.float32)
            logits = model(flat.reshape(1, 784))
            ref_rows.append([float(value) for value in flat.tolist()])
            ref_labels.append(int(label))
            ref_predictions.append(int(logits.argmax(dim=1).item()))

    _write_dat(input_dat_path, ref_rows)
    labels_path.write_text(json.dumps({"labels": ref_labels}, indent=2), encoding="utf-8")
    predictions_path.write_text(
        json.dumps({"predictions": ref_predictions, "labels": ref_labels}, indent=2),
        encoding="utf-8",
    )

    metrics = {
        "status": "success" if best_accuracy >= args.target_accuracy else "below_target",
        "architecture": "MLP(784,64,32,10)",
        "best_eval_accuracy": best_accuracy,
        "target_accuracy": args.target_accuracy,
        "eval_samples": eval_size,
        "reference_samples": ref_count,
        "history": history,
        "state_dict_path": str(state_path),
        "onnx_path": str(onnx_path),
        "reference_input_path": str(input_dat_path),
        "labels_path": str(labels_path),
        "python_predictions_path": str(predictions_path),
    }
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    return 0 if metrics["status"] == "success" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
