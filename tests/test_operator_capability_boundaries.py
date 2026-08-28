from __future__ import annotations

import pytest

from dl_op_to_hls.core.errors import AgentRuntimeError
from dl_op_to_hls.schemas.operator_schema import normalize_operator_task


def test_grouped_conv2d_is_rejected_before_candidate_generation() -> None:
    with pytest.raises(AgentRuntimeError) as raised:
        normalize_operator_task(
            {
                "task_type": "operator",
                "name": "grouped_conv",
                "op_type": "Conv2D",
                "input_shape": [8, 8, 4],
                "weight_shape": [3, 3, 2, 8],
                "output_shape": [6, 6, 8],
                "dtype": "ap_fixed<12,4>",
                "group": 2,
                "target": {"backend": "VivadoHLS", "part": "xc7z020", "clock_period": 10},
            }
        )
    assert raised.value.error.error_type == "UnsupportedOperatorError"
    assert raised.value.error.details == {"group": 2}


def test_non_integer_conv2d_group_is_invalid_task() -> None:
    with pytest.raises(AgentRuntimeError) as raised:
        normalize_operator_task(
            {
                "task_type": "operator",
                "name": "invalid_group",
                "op_type": "Conv2D",
                "input_shape": [8, 8, 4],
                "output_shape": [6, 6, 8],
                "group": "dynamic",
            }
        )
    assert raised.value.error.error_type == "InvalidTaskError"
