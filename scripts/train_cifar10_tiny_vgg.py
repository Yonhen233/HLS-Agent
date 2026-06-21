from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

CIFAR10_MD5 = "c58f30108f718f92721af3b95e74349a"
DEFAULT_CIFAR10_MIRRORS = [
    "https://mirrors.bfsu.edu.cn/osdn//datasets/74526/cifar-10-python.tar.gz",
    "https://data.brainchip.com/dataset-mirror/cifar10/cifar-10-python.tar.gz",
    "https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train a HLS-friendly CIFAR-10 TinyVGG model and export ONNX/reference data."
    )
    parser.add_argument("--output-dir", default="models/cifar10_tiny_vgg")
    parser.add_argument("--data-dir", default="models/cifar10_tiny_vgg/data")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument(
        "--early-stopping-patience",
        type=int,
        default=0,
        help="Stop after this many validation epochs without improvement; 0 disables early stopping.",
    )
    parser.add_argument(
        "--min-epochs",
        type=int,
        default=0,
        help="Do not apply early stopping until this many training epochs complete.",
    )
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--optimizer", choices=["adamw", "sgd"], default="adamw")
    parser.add_argument("--momentum", type=float, default=0.9, help="Momentum when --optimizer sgd is selected.")
    parser.add_argument("--label-smoothing", type=float, default=0.0)
    parser.add_argument(
        "--mixup-alpha",
        type=float,
        default=0.0,
        help="Apply MixUp only during training; the exported inference graph is unchanged.",
    )
    parser.add_argument("--weights-path", help="Optional trained state_dict to load before export or evaluation.")
    parser.add_argument(
        "--skip-training",
        action="store_true",
        help="Load --weights-path, evaluate, calibrate, and export without another training pass.",
    )
    parser.add_argument("--train-samples", type=int, default=30000)
    parser.add_argument("--eval-samples", type=int, default=5000)
    parser.add_argument(
        "--device",
        default="auto",
        help="Training device: auto, cpu, cuda, or a concrete torch device such as cuda:0.",
    )
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--reference-samples", type=int, default=20)
    parser.add_argument("--calibration-samples", type=int, default=512)
    parser.add_argument("--target-accuracy", type=float, default=0.55)
    parser.add_argument("--image-size", type=int, default=16)
    parser.add_argument("--channels", type=int, nargs=3, default=[8, 8, 16], metavar=("C1", "C2", "C3"))
    parser.add_argument("--hidden", type=int, default=32)
    parser.add_argument(
        "--architecture",
        choices=["tiny_vgg", "gap_cnn", "vgg_gap", "custom_gap"],
        default="tiny_vgg",
        help=(
            "tiny_vgg uses two pools and a dense hidden head; gap_cnn uses Conv/Pool/Conv/Pool/Conv/GAP/Dense; "
            "vgg_gap uses two 3x3 convs per stage and GAP; custom_gap chooses one or two convolutions per stage."
        ),
    )
    parser.add_argument(
        "--convs-per-stage",
        type=int,
        nargs=3,
        default=[1, 1, 1],
        metavar=("S1", "S2", "S3"),
        help="Conv/ReLU count for each custom_gap stage; the first two stages are followed by MaxPool.",
    )
    parser.add_argument("--augment", action="store_true", help="Use lightweight random crop/flip augmentation for training only.")
    parser.add_argument("--autoaugment", action="store_true", help="Apply the CIFAR-10 AutoAugment policy during training only.")
    parser.add_argument(
        "--random-erasing-probability",
        type=float,
        default=0.0,
        help="Apply RandomErasing after normalization during training only.",
    )
    parser.add_argument(
        "--batchnorm",
        action="store_true",
        help="Insert BatchNorm after each convolution. Inference exports can fold it into convolution weights.",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Apply standard CIFAR-10 channel normalization; exported reference data uses the same normalized inputs.",
    )
    parser.add_argument(
        "--teacher-checkpoint",
        help="Optional teacher state_dict used only for knowledge distillation while training the student.",
    )
    parser.add_argument("--teacher-architecture", choices=["vgg_gap"], default="vgg_gap")
    parser.add_argument("--teacher-channels", type=int, nargs=3, default=[32, 64, 128], metavar=("TC1", "TC2", "TC3"))
    parser.add_argument("--teacher-no-batchnorm", action="store_true")
    parser.add_argument(
        "--distillation-alpha",
        type=float,
        default=0.0,
        help="Teacher-loss weight in [0, 1]. Zero disables knowledge distillation.",
    )
    parser.add_argument("--distillation-temperature", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--opset", type=int, default=13)
    parser.add_argument(
        "--mirror",
        action="append",
        default=[],
        help="CIFAR-10 tar.gz mirror URL. Can be passed multiple times; defaults prefer domestic mirrors.",
    )
    return parser


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _write_dat(path: Path, rows: list[list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(" ".join(f"{float(value):.8g}" for value in row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _subset_indices(size: int, requested: int, seed: int) -> list[int]:
    count = min(int(requested), int(size))
    indices = list(range(int(size)))
    rng = random.Random(seed)
    rng.shuffle(indices)
    return indices[:count]


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_file(url: str, target: Path) -> None:
    temp_path = target.with_suffix(target.suffix + ".part")
    if temp_path.exists():
        temp_path.unlink()
    print(f"[download] {url}", flush=True)
    with urllib.request.urlopen(url, timeout=60) as response:
        total_raw = response.headers.get("Content-Length")
        total = int(total_raw) if total_raw and total_raw.isdigit() else None
        done = 0
        last_report_mb = -1
        with temp_path.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                done_mb = done // (1024 * 1024)
                if done_mb != last_report_mb and done_mb % 16 == 0:
                    last_report_mb = done_mb
                    if total:
                        print(f"[download] {done_mb} MiB / {total // (1024 * 1024)} MiB", flush=True)
                    else:
                        print(f"[download] {done_mb} MiB", flush=True)
    temp_path.replace(target)


def _ensure_cifar10_dataset(data_dir: Path, mirrors: list[str]) -> None:
    extracted_dir = data_dir / "cifar-10-batches-py"
    if (extracted_dir / "data_batch_1").exists() and (extracted_dir / "test_batch").exists():
        print(f"[data] CIFAR-10 already extracted under {extracted_dir}", flush=True)
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    tar_path = data_dir / "cifar-10-python.tar.gz"
    if tar_path.exists() and tar_path.stat().st_size > 0:
        current_md5 = _md5(tar_path)
        if current_md5 != CIFAR10_MD5:
            print(f"[data] removing incomplete/corrupt archive md5={current_md5}", flush=True)
            tar_path.unlink()
    if not tar_path.exists():
        errors: list[str] = []
        for url in mirrors:
            try:
                _download_file(url, tar_path)
                current_md5 = _md5(tar_path)
                if current_md5 != CIFAR10_MD5:
                    errors.append(f"{url}: md5 mismatch {current_md5}")
                    tar_path.unlink(missing_ok=True)
                    continue
                break
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
                tar_path.unlink(missing_ok=True)
        if not tar_path.exists():
            raise RuntimeError("Failed to download CIFAR-10 from all mirrors: " + " | ".join(errors))
    print(f"[data] extracting {tar_path}", flush=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(data_dir)


def _accuracy(model, loader, torch, device) -> tuple[float, int, int]:
    model.eval()
    correct = 0
    seen = 0
    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            logits = model(images)
            predictions = logits.argmax(dim=1)
            correct += int((predictions == labels).sum().item())
            seen += int(labels.numel())
    return correct / max(seen, 1), correct, seen


def _collect_activation_ranges(model, loader, torch, device, max_samples: int) -> dict[str, Any]:
    """Collect conservative post-module ranges for fixed-point HLS planning."""

    ranges: dict[str, dict[str, float | int]] = {}
    handles = []

    def update(name: str, tensor: Any) -> None:
        if not isinstance(tensor, torch.Tensor):
            return
        values = tensor.detach()
        current = ranges.setdefault(
            name,
            {
                "min": float("inf"),
                "max": float("-inf"),
                "max_abs": 0.0,
                "samples": 0,
            },
        )
        current["min"] = min(float(current["min"]), float(values.min().item()))
        current["max"] = max(float(current["max"]), float(values.max().item()))
        current["max_abs"] = max(float(current["max_abs"]), float(values.abs().max().item()))
        current["samples"] = int(current["samples"]) + int(values.shape[0])

    for name, module in model.named_modules():
        if not name or any(True for _ in module.children()):
            continue
        module_type = type(module).__name__
        if module_type not in {"Conv2d", "BatchNorm2d", "MaxPool2d", "AdaptiveAvgPool2d", "Linear"}:
            continue

        def hook(_module, _inputs, output, *, record_name=f"{name}:{module_type}"):
            update(record_name, output)

        handles.append(module.register_forward_hook(hook))

    seen = 0
    model.eval()
    with torch.no_grad():
        for images, _labels in loader:
            images = images.to(device, non_blocking=True)
            update("input", images)
            model(images)
            seen += int(images.shape[0])
            if seen >= max(1, int(max_samples)):
                break
    for handle in handles:
        handle.remove()

    for item in ranges.values():
        max_abs = float(item["max_abs"])
        # ap_fixed<W, I> has signed range [-2^(I-1), 2^(I-1)). This is a
        # conservative integer-bit recommendation for later HLS quantization.
        item["suggested_integer_bits"] = 2 if max_abs <= 1.0 else int(math.floor(math.log2(max_abs))) + 2
    return {
        "status": "success",
        "calibration_samples": seen,
        "ranges": ranges,
        "guidance": "Use the largest suggested_integer_bits across a fused HLS stage, then allocate fractional bits within the chosen total precision.",
    }


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
    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        print(f"[error] requested CUDA device {device}, but CUDA is unavailable.")
        return 2
    if device.type == "cuda":
        torch.cuda.manual_seed_all(args.seed)
    print(f"[runtime] device={device}", flush=True)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    c1, c2, c3 = [int(value) for value in args.channels]
    hidden = int(args.hidden)
    pooled_size = int(args.image_size) // 4
    if pooled_size < 1:
        print("[error] image-size must be at least 4 because the model uses two 2x2 pools.")
        return 2

    class CifarTinyVGG(nn.Module):
        def __init__(self, architecture: str, channels: tuple[int, int, int], batchnorm: bool, hidden_size: int, convs_per_stage=(1, 1, 1)) -> None:
            super().__init__()
            self.architecture = str(architecture)
            c1_local, c2_local, c3_local = channels
            norm = nn.BatchNorm2d if batchnorm else nn.Identity
            if self.architecture == "custom_gap":
                stage_counts = tuple(int(value) for value in convs_per_stage)
                if any(value < 1 or value > 2 for value in stage_counts):
                    raise ValueError("custom_gap convs_per_stage values must be 1 or 2")

                def stage(in_channels: int, out_channels: int, count: int):
                    blocks = []
                    current_channels = in_channels
                    for _ in range(count):
                        blocks.extend([nn.Conv2d(current_channels, out_channels, kernel_size=3, padding=1), norm(out_channels), nn.ReLU()])
                        current_channels = out_channels
                    return nn.Sequential(*blocks)

                self.stage1 = stage(3, c1_local, stage_counts[0])
                self.stage2 = stage(c1_local, c2_local, stage_counts[1])
                self.stage3 = stage(c2_local, c3_local, stage_counts[2])
                self.gap = nn.AdaptiveAvgPool2d((1, 1))
                self.fc = nn.Linear(c3_local, 10)
                return

            self.conv1 = nn.Conv2d(3, c1_local, kernel_size=3, padding=1)
            self.conv2 = nn.Conv2d(c1_local, c2_local, kernel_size=3, padding=1)
            self.conv3 = nn.Conv2d(c2_local, c3_local, kernel_size=3, padding=1)
            self.bn1 = norm(c1_local)
            self.bn2 = norm(c2_local)
            self.bn3 = norm(c3_local)
            self.pool = nn.MaxPool2d(2)
            if self.architecture == "vgg_gap":
                self.conv1b = nn.Conv2d(c1_local, c1_local, kernel_size=3, padding=1)
                self.conv2b = nn.Conv2d(c2_local, c2_local, kernel_size=3, padding=1)
                self.conv3b = nn.Conv2d(c3_local, c3_local, kernel_size=3, padding=1)
                self.bn1b = norm(c1_local)
                self.bn2b = norm(c2_local)
                self.bn3b = norm(c3_local)
                self.gap = nn.AdaptiveAvgPool2d((1, 1))
                self.fc = nn.Linear(c3_local, 10)
            elif self.architecture == "gap_cnn":
                self.gap = nn.AdaptiveAvgPool2d((1, 1))
                self.fc = nn.Linear(c3_local, 10)
            else:
                self.fc1 = nn.Linear(c3_local * pooled_size * pooled_size, hidden_size)
                self.fc2 = nn.Linear(hidden_size, 10)

        def forward(self, x):
            if self.architecture == "custom_gap":
                x = self.pool(self.stage1(x))
                x = self.pool(self.stage2(x))
                x = self.stage3(x)
                return self.fc(self.gap(x).flatten(1))
            if self.architecture == "vgg_gap":
                x = F.relu(self.bn1(self.conv1(x)))
                x = self.pool(F.relu(self.bn1b(self.conv1b(x))))
                x = F.relu(self.bn2(self.conv2(x)))
                x = self.pool(F.relu(self.bn2b(self.conv2b(x))))
                x = F.relu(self.bn3(self.conv3(x)))
                x = F.relu(self.bn3b(self.conv3b(x)))
                x = self.gap(x)
                x = x.flatten(1)
                return self.fc(x)
            if self.architecture == "gap_cnn":
                x = self.pool(F.relu(self.bn1(self.conv1(x))))
                x = self.pool(F.relu(self.bn2(self.conv2(x))))
                x = F.relu(self.bn3(self.conv3(x)))
                x = self.gap(x)
                x = x.flatten(1)
                return self.fc(x)
            x = F.relu(self.bn1(self.conv1(x)))
            x = self.pool(F.relu(self.bn2(self.conv2(x))))
            x = F.relu(self.bn3(self.conv3(self.pool(x))))
            x = self.pool(x)
            x = x.flatten(1)
            x = F.relu(self.fc1(x))
            return self.fc2(x)

    def build_model(
        architecture: str,
        channels: list[int] | tuple[int, int, int],
        batchnorm: bool,
        hidden_size: int,
        convs_per_stage: list[int] | tuple[int, int, int] = (1, 1, 1),
    ) -> CifarTinyVGG:
        return CifarTinyVGG(
            str(architecture),
            tuple(int(value) for value in channels),
            bool(batchnorm),
            int(hidden_size),
            tuple(int(value) for value in convs_per_stage),
        )

    normalize_layers = (
        [transforms.Normalize(mean=(0.4914, 0.4822, 0.4465), std=(0.2470, 0.2435, 0.2616))]
        if args.normalize
        else []
    )
    eval_transform = transforms.Compose(
        [
            transforms.Resize((int(args.image_size), int(args.image_size))),
            transforms.ToTensor(),
            *normalize_layers,
        ]
    )
    if args.augment:
        train_transforms = [
            transforms.Resize((int(args.image_size), int(args.image_size))),
            transforms.RandomCrop(int(args.image_size), padding=4),
            transforms.RandomHorizontalFlip(),
        ]
        if args.autoaugment:
            train_transforms.append(transforms.AutoAugment(transforms.AutoAugmentPolicy.CIFAR10))
        train_transforms.extend([transforms.ToTensor(), *normalize_layers])
        if float(args.random_erasing_probability) > 0:
            train_transforms.append(transforms.RandomErasing(p=float(args.random_erasing_probability)))
        train_transform = transforms.Compose(train_transforms)
    else:
        train_transform = eval_transform
    data_dir = Path(args.data_dir)
    mirrors = list(args.mirror or []) + [url for url in DEFAULT_CIFAR10_MIRRORS if url not in set(args.mirror or [])]
    _ensure_cifar10_dataset(data_dir, mirrors)
    train_ds = datasets.CIFAR10(root=str(data_dir), train=True, download=False, transform=train_transform)
    test_ds = datasets.CIFAR10(root=str(data_dir), train=False, download=False, transform=eval_transform)
    train_indices = _subset_indices(len(train_ds), args.train_samples, args.seed)
    eval_indices = list(range(min(int(args.eval_samples), len(test_ds))))
    loader_options = {
        "batch_size": args.batch_size,
        "num_workers": max(0, int(args.num_workers)),
        "pin_memory": device.type == "cuda",
    }
    train_loader = DataLoader(Subset(train_ds, train_indices), shuffle=True, **loader_options)
    eval_loader = DataLoader(Subset(test_ds, eval_indices), shuffle=False, **loader_options)

    model = build_model(args.architecture, (c1, c2, c3), args.batchnorm, hidden, args.convs_per_stage).to(device)
    if args.weights_path:
        weights_path = Path(args.weights_path)
        if not weights_path.exists():
            print(f"[error] --weights-path does not exist: {weights_path}")
            return 2
        model.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
    elif args.skip_training:
        print("[error] --skip-training requires --weights-path.")
        return 2
    if args.optimizer == "sgd":
        optimizer = torch.optim.SGD(
            model.parameters(),
            lr=args.learning_rate,
            momentum=args.momentum,
            weight_decay=args.weight_decay,
            nesterov=True,
        )
    else:
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=args.learning_rate,
            weight_decay=args.weight_decay,
        )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max(int(args.epochs), 1),
    )
    loss_fn = nn.CrossEntropyLoss(label_smoothing=float(args.label_smoothing))
    teacher = None
    if args.teacher_checkpoint:
        teacher_path = Path(args.teacher_checkpoint)
        if not teacher_path.exists():
            print(f"[error] --teacher-checkpoint does not exist: {teacher_path}")
            return 2
        teacher = build_model(
            args.teacher_architecture,
            args.teacher_channels,
            not bool(args.teacher_no_batchnorm),
            hidden,
        ).to(device)
        teacher.load_state_dict(torch.load(teacher_path, map_location="cpu", weights_only=True))
        teacher.eval()
        for parameter in teacher.parameters():
            parameter.requires_grad_(False)
    if not 0.0 <= float(args.distillation_alpha) <= 1.0:
        print("[error] --distillation-alpha must be in [0, 1].")
        return 2
    if teacher is None and float(args.distillation_alpha) > 0:
        print("[error] --distillation-alpha requires --teacher-checkpoint.")
        return 2
    if float(args.distillation_temperature) <= 0:
        print("[error] --distillation-temperature must be positive.")
        return 2

    history: list[dict[str, Any]] = []
    best_accuracy = 0.0
    best_epoch = 0
    epochs_without_improvement = 0
    stop_reason = "max_epochs_reached"
    best_state = copy.deepcopy(model.state_dict())
    best_checkpoint_path = output_dir / "cifar10_tiny_vgg_best.pt"
    if args.weights_path:
        accuracy, correct, seen = _accuracy(model, eval_loader, torch, device)
        best_accuracy = accuracy
        item = {
            "epoch": 0,
            "train_loss": None,
            "eval_accuracy": accuracy,
            "eval_correct": correct,
            "eval_seen": seen,
            "learning_rate": None,
        }
        history.append(item)
        torch.save(best_state, best_checkpoint_path)
        print(f"[evaluate] loaded weights eval_accuracy={accuracy:.4f}", flush=True)
    if args.skip_training:
        pass
    else:
        for epoch in range(1, int(args.epochs) + 1):
            model.train()
            total_loss = 0.0
            total_seen = 0
            for images, labels in train_loader:
                images = images.to(device, non_blocking=True)
                labels = labels.to(device, non_blocking=True)
                mixed_labels = None
                mixup_lambda = 1.0
                if float(args.mixup_alpha) > 0:
                    mixup_lambda = float(np.random.beta(float(args.mixup_alpha), float(args.mixup_alpha)))
                    order = torch.randperm(int(labels.shape[0]), device=device)
                    images = mixup_lambda * images + (1.0 - mixup_lambda) * images[order]
                    mixed_labels = labels[order]
                logits = model(images)
                supervised_loss = (
                    mixup_lambda * loss_fn(logits, labels) + (1.0 - mixup_lambda) * loss_fn(logits, mixed_labels)
                    if mixed_labels is not None
                    else loss_fn(logits, labels)
                )
                if teacher is None:
                    loss = supervised_loss
                else:
                    with torch.no_grad():
                        teacher_logits = teacher(images)
                    temperature = float(args.distillation_temperature)
                    distillation_loss = F.kl_div(
                        F.log_softmax(logits / temperature, dim=1),
                        F.softmax(teacher_logits / temperature, dim=1),
                        reduction="batchmean",
                    ) * (temperature * temperature)
                    alpha = float(args.distillation_alpha)
                    loss = (1.0 - alpha) * supervised_loss + alpha * distillation_loss
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
                total_loss += float(loss.item()) * int(labels.numel())
                total_seen += int(labels.numel())
            accuracy, correct, seen = _accuracy(model, eval_loader, torch, device)
            if accuracy > best_accuracy:
                best_accuracy = accuracy
                best_epoch = epoch
                best_state = copy.deepcopy(model.state_dict())
                torch.save(best_state, best_checkpoint_path)
                epochs_without_improvement = 0
            else:
                epochs_without_improvement += 1
            item = {
                "epoch": epoch,
                "train_loss": total_loss / max(total_seen, 1),
                "eval_accuracy": accuracy,
                "eval_correct": correct,
                "eval_seen": seen,
                "learning_rate": float(optimizer.param_groups[0]["lr"]),
            }
            history.append(item)
            print(
                f"[train] epoch={epoch} loss={item['train_loss']:.4f} "
                f"eval_accuracy={accuracy:.4f} lr={item['learning_rate']:.6g}",
                flush=True,
            )
            scheduler.step()
            if (
                int(args.early_stopping_patience) > 0
                and epoch >= max(1, int(args.min_epochs))
                and epochs_without_improvement >= int(args.early_stopping_patience)
            ):
                stop_reason = (
                    "early_stopping: validation accuracy did not improve for "
                    f"{epochs_without_improvement} epochs"
                )
                print(f"[training] {stop_reason}", flush=True)
                break

    model.load_state_dict(best_state)
    model.eval()
    state_path = output_dir / "cifar10_tiny_vgg.pt"
    onnx_path = output_dir / "cifar10_tiny_vgg.onnx"
    metrics_path = output_dir / "cifar10_tiny_vgg_training_metrics.json"
    activation_ranges_path = output_dir / "cifar10_tiny_vgg_activation_ranges.json"
    input_dat_path = output_dir / f"cifar10_test_inputs_{args.reference_samples}.dat"
    labels_path = output_dir / f"cifar10_test_labels_{args.reference_samples}.json"
    predictions_path = output_dir / f"cifar10_test_python_predictions_{args.reference_samples}.json"

    torch.save(model.state_dict(), state_path)
    export_model = copy.deepcopy(model).to("cpu").eval()
    sample = torch.zeros(1, 3, int(args.image_size), int(args.image_size), dtype=torch.float32)
    torch.onnx.export(
        export_model,
        sample,
        str(onnx_path),
        export_params=True,
        input_names=["model_input_nchw"],
        output_names=["logits"],
        opset_version=int(args.opset),
    )

    ref_rows: list[list[float]] = []
    ref_labels: list[int] = []
    ref_predictions: list[int] = []
    ref_indices: list[int] = []
    with torch.no_grad():
        for index in range(len(test_ds)):
            image, label = test_ds[index]
            logits = model(image.reshape(1, 3, int(args.image_size), int(args.image_size)).to(device))
            pred = int(logits.argmax(dim=1).item())
            if pred != int(label):
                continue
            ref_rows.append([float(value) for value in image.reshape(-1).tolist()])
            ref_labels.append(int(label))
            ref_predictions.append(pred)
            ref_indices.append(index)
            if len(ref_rows) >= int(args.reference_samples):
                break
    if len(ref_rows) < int(args.reference_samples):
        with torch.no_grad():
            for index in range(len(test_ds)):
                if index in ref_indices:
                    continue
                image, label = test_ds[index]
                logits = model(image.reshape(1, 3, int(args.image_size), int(args.image_size)).to(device))
                ref_rows.append([float(value) for value in image.reshape(-1).tolist()])
                ref_labels.append(int(label))
                ref_predictions.append(int(logits.argmax(dim=1).item()))
                ref_indices.append(index)
                if len(ref_rows) >= int(args.reference_samples):
                    break

    _write_dat(input_dat_path, ref_rows)
    labels_path.write_text(json.dumps({"labels": ref_labels, "indices": ref_indices}, indent=2), encoding="utf-8")
    predictions_path.write_text(
        json.dumps({"predictions": ref_predictions, "labels": ref_labels, "indices": ref_indices}, indent=2),
        encoding="utf-8",
    )
    calibration_loader = DataLoader(
        Subset(test_ds, eval_indices[: min(len(eval_indices), max(1, int(args.calibration_samples)))]),
        shuffle=False,
        **loader_options,
    )
    activation_ranges = _collect_activation_ranges(
        model,
        calibration_loader,
        torch,
        device,
        max_samples=int(args.calibration_samples),
    )
    activation_ranges_path.write_text(
        json.dumps(activation_ranges, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    metrics = {
        "status": "success" if best_accuracy >= args.target_accuracy else "below_target",
        "architecture": (
            f"{args.architecture}-CIFAR10(input=3x{args.image_size}x{args.image_size}, "
            f"conv{c1}, conv{c2}, conv{c3}, "
            f"{'vgg blocks, gap, dense10' if args.architecture == 'vgg_gap' else 'custom stage conv counts ' + str([int(value) for value in args.convs_per_stage]) + ', gap, dense10' if args.architecture == 'custom_gap' else 'gap, dense10' if args.architecture == 'gap_cnn' else f'dense{hidden}, dense10'})"
        ),
        "model_family": args.architecture,
        "channels": [c1, c2, c3],
        "hidden": hidden,
        "augment": bool(args.augment),
        "batchnorm": bool(args.batchnorm),
        "input_normalization": "cifar10_mean_std" if args.normalize else "none",
        "optimizer": args.optimizer,
        "learning_rate": float(args.learning_rate),
        "momentum": float(args.momentum) if args.optimizer == "sgd" else None,
        "weight_decay": float(args.weight_decay),
        "label_smoothing": float(args.label_smoothing),
        "mixup_alpha": float(args.mixup_alpha),
        "autoaugment": bool(args.autoaugment),
        "random_erasing_probability": float(args.random_erasing_probability),
        "distillation": {
            "enabled": teacher is not None,
            "teacher_checkpoint": str(args.teacher_checkpoint) if args.teacher_checkpoint else None,
            "teacher_architecture": args.teacher_architecture if teacher is not None else None,
            "teacher_channels": [int(value) for value in args.teacher_channels] if teacher is not None else [],
            "alpha": float(args.distillation_alpha),
            "temperature": float(args.distillation_temperature),
        },
        "best_eval_accuracy": best_accuracy,
        "best_epoch": best_epoch,
        "target_accuracy": args.target_accuracy,
        "training_stop_reason": stop_reason,
        "epochs_completed": len([item for item in history if item["epoch"] > 0]),
        "train_samples": len(train_indices),
        "eval_samples": len(eval_indices),
        "reference_samples": len(ref_rows),
        "reference_selection": "first correctly classified test samples, then fallback sequential samples",
        "history": history,
        "state_dict_path": str(state_path),
        "best_checkpoint_path": str(best_checkpoint_path) if best_checkpoint_path.exists() else str(state_path),
        "onnx_path": str(onnx_path),
        "reference_input_path": str(input_dat_path),
        "labels_path": str(labels_path),
        "python_predictions_path": str(predictions_path),
        "activation_ranges_path": str(activation_ranges_path),
    }
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    return 0 if metrics["status"] == "success" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
