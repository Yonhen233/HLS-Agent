from __future__ import annotations

import importlib.util
from pathlib import Path


def _training_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "train_cifar10_tiny_vgg.py"
    spec = importlib.util.spec_from_file_location("cifar10_training_script", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cifar10_training_parser_exposes_student_only_distillation_options():
    parser = _training_script_module().build_parser()
    args = parser.parse_args(
        [
            "--architecture",
            "gap_cnn",
            "--channels",
            "8",
            "16",
            "32",
            "--teacher-checkpoint",
            "teacher.pt",
            "--distillation-alpha",
            "0.6",
            "--distillation-temperature",
            "4",
            "--autoaugment",
            "--random-erasing-probability",
            "0.2",
            "--mixup-alpha",
            "0.1",
        ]
    )

    assert args.channels == [8, 16, 32]
    assert args.teacher_checkpoint == "teacher.pt"
    assert args.distillation_alpha == 0.6
    assert args.distillation_temperature == 4.0
    assert args.autoaugment is True
    assert args.random_erasing_probability == 0.2
    assert args.mixup_alpha == 0.1
