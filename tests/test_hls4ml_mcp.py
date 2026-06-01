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


def test_hls4ml_qkeras_h5_frontend_is_structured_unsupported(tmp_path, monkeypatch):
    model = tmp_path / "mnist_qkeras_cnn.h5"
    model.write_bytes(b"placeholder h5")
    adapter = HLS4MLAdapter(mock_mode=False)
    monkeypatch.setattr(adapter, "_installed", lambda: True)
    result = adapter.check_support(
        {
            "task_type": "model",
            "name": "mnist_qkeras_cnn",
            "model_path": str(model),
            "frontend": "qkeras",
        }
    )
    assert result["status"] == "unsupported"
    assert result["unsupported_layers"][0]["type"] == "QKerasH5"


def test_hls4ml_qkeras_h5_convert_does_not_parse_as_onnx(tmp_path, monkeypatch):
    model = tmp_path / "mnist_qkeras_cnn.h5"
    model.write_bytes(b"placeholder h5")
    adapter = HLS4MLAdapter(mock_mode=False)
    monkeypatch.setattr(adapter, "_installed", lambda: True)
    result = adapter.convert({"model_path": str(model), "frontend": "qkeras", "output_dir": str(tmp_path / "out")})
    assert result["status"] == "error"
    assert result["error"]["error_type"] == "HLS4MLConversionError"
    assert "ONNX" not in result["error"]["message"]
