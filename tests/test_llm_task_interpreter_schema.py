from dl_op_to_hls.llm.client import FakeLLMClient
from dl_op_to_hls.llm.task_interpreter import LLMTaskInterpreter


def test_llm_task_interpreter_schema():
    fake = FakeLLMClient(
        json_responses=[
            {
                "task": {
                    "task_type": "operator",
                    "name": "dense_16x32",
                    "op_type": "Dense",
                    "input_shape": [16],
                    "output_shape": [32],
                    "dtype": "ap_fixed<16,6>",
                    "target": {"backend": "VivadoHLS", "part": "xc7z020clg400-1", "clock_period": 5},
                    "objective": "latency",
                },
                "assumptions": ["static shape"],
                "reason_summary": "converted from NL",
            }
        ]
    )
    result = LLMTaskInterpreter().interpret("convert dense", fake)
    assert result["task"]["task_type"] == "operator"
    assert result["assumptions"]
