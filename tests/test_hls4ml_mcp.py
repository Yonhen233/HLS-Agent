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
    assert "Backend: Vivado" in (tmp_path / "hls4ml_config.yml").read_text(encoding="utf-8")


def test_hls4ml_backend_override_mock_config(tmp_path):
    adapter = HLS4MLAdapter(mock_mode=True, backend_override="Vitis")
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
    assert result["status"] == "success"
    assert "Backend: Vitis" in (tmp_path / "hls4ml_config.yml").read_text(encoding="utf-8")


def test_hls4ml_convert_mock(tmp_path):
    adapter = HLS4MLAdapter(mock_mode=True)
    result = adapter.convert({"model_path": "models/mlp.onnx", "output_dir": str(tmp_path)})
    assert result["status"] == "success"
    assert (tmp_path / "myproject.cpp").exists()


def test_hls4ml_real_onnx_layer_list_adapter_supports_gemm(tmp_path, monkeypatch):
    onnx = __import__("onnx")
    numpy = __import__("numpy")
    from onnx import TensorProto, helper, numpy_helper

    model_path = tmp_path / "mlp_gemm.onnx"
    x = helper.make_tensor_value_info("model_input", TensorProto.FLOAT, [1, 4])
    y = helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 2])
    weights = numpy_helper.from_array(numpy.ones((2, 4), dtype=numpy.float32), name="fc.weight")
    bias = numpy_helper.from_array(numpy.zeros((2,), dtype=numpy.float32), name="fc.bias")
    gemm = helper.make_node("Gemm", inputs=["model_input", "fc.weight", "fc.bias"], outputs=["logits"], name="fc", transB=1)
    graph = helper.make_graph([gemm], "gemm_graph", [x], [y], initializer=[weights, bias])
    onnx.save(helper.make_model(graph), str(model_path))

    adapter = HLS4MLAdapter(mock_mode=False)
    monkeypatch.setattr(adapter, "_installed", lambda: True)

    support = adapter.check_support({"task_type": "model", "name": "gemm_demo", "model_path": str(model_path), "frontend": "onnx"})
    config = adapter.generate_config(
        {
            "model_path": str(model_path),
            "frontend": "onnx",
            "backend": "Vivado",
            "part": "xc7z020clg400-1",
            "clock_period": 5,
            "precision": "fixed<16,6>",
            "reuse_factor": 1,
            "strategy": "Latency",
            "output_dir": str(tmp_path / "cfg"),
        }
    )
    converted = adapter.convert(
        {
            "model_path": str(model_path),
            "frontend": "onnx",
            "config_path": config["config_path"],
            "output_dir": str(tmp_path / "hls_project"),
        }
    )

    assert support["status"] == "supported"
    assert support["frontend_adapter"] == "onnx_layer_list"
    assert config["status"] == "success"
    assert converted["status"] == "success"
    assert (tmp_path / "hls_project" / "firmware").exists()


def test_hls4ml_run_csim_real_mode_does_not_mock_success(tmp_path):
    project_dir = tmp_path / "hls_project"
    project_dir.mkdir()
    adapter = HLS4MLAdapter(mock_mode=False)
    result = adapter.run_csim(str(project_dir))
    assert result["status"] == "error"
    assert result["error"]["error_type"] in {"HLS4MLNotInstalledError", "HLS4MLConversionError"}
    assert "Mock hls4ml csim completed successfully" not in (tmp_path / "logs" / "hls4ml_csim.log").read_text(encoding="utf-8", errors="ignore") if (tmp_path / "logs" / "hls4ml_csim.log").exists() else True


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
