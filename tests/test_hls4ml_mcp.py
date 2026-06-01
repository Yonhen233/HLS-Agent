from dl_op_to_hls.adapters.hls4ml_adapter import HLS4MLAdapter


def test_hls4ml_inspect_model_mock():
    adapter = HLS4MLAdapter(mock_mode=True)
    result = adapter.inspect_model("models/mlp.onnx", "onnx")
    assert result["status"] == "success"


def test_hls4ml_check_support_supported_mock():
    adapter = HLS4MLAdapter(mock_mode=True)
    result = adapter.check_support({"task_type": "model", "model_path": "models/mlp.onnx"})
    assert result["status"] == "supported"


def test_hls4ml_check_support_unsupported_mock():
    adapter = HLS4MLAdapter(mock_mode=True)
    result = adapter.check_support({"task_type": "model", "model_path": "models/unsupported.onnx"})
    assert result["status"] == "unsupported"


def test_hls4ml_generate_config_mock(tmp_path):
    adapter = HLS4MLAdapter(mock_mode=True)
    result = adapter.generate_config(
        {
            "model_path": "models/mlp.onnx",
            "frontend": "onnx",
            "backend": "Vivado",
            "part": "xc7z020clg400-1",
            "clock_period": 5,
            "precision": "fixed<16,6>",
            "reuse_factor": 1,
            "strategy": "Latency",
            "output_dir": str(tmp_path),
        }
    )
    assert (tmp_path / "hls4ml_config.yml").exists()
    assert result["status"] == "success"


def test_hls4ml_convert_mock(tmp_path):
    adapter = HLS4MLAdapter(mock_mode=True)
    result = adapter.convert({"model_path": "models/mlp.onnx", "output_dir": str(tmp_path)})
    assert result["status"] == "success"
    assert (tmp_path / "myproject.cpp").exists()

