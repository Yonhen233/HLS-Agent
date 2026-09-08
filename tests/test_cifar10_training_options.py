"""Test contracts and regression checks for test_cifar10_training_options.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _training_script_module():
    """Verify the _training_script_module contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "train_cifar10_tiny_vgg.py"
    spec = importlib.util.spec_from_file_location("cifar10_training_script", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cifar10_training_parser_exposes_student_only_distillation_options():
    """Verify the test_cifar10_training_parser_exposes_student_only_distillation_options contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
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


def test_cifar10_training_parser_exposes_custom_gap_stage_counts():
    """Verify the test_cifar10_training_parser_exposes_custom_gap_stage_counts contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    parser = _training_script_module().build_parser()
    args = parser.parse_args(
        [
            "--architecture",
            "custom_gap",
            "--channels",
            "12",
            "24",
            "48",
            "--convs-per-stage",
            "1",
            "2",
            "1",
        ]
    )

    assert args.architecture == "custom_gap"
    assert args.convs_per_stage == [1, 2, 1]
