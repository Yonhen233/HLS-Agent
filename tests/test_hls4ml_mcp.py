import pytest

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


def test_hls4ml_accumulator_precision_extension_keeps_default_precision():
    adapter = HLS4MLAdapter(mock_mode=True)
    payload = {"hls_config": {"Model": {"Precision": "fixed<24,8>"}}}

    adapter._apply_hls4ml_config_extensions(payload, {"accumulator_precision": "fixed<32,14>"})

    assert payload["hls_config"]["Model"]["Precision"] == {
        "default": "fixed<24,8>",
        "accum": "fixed<32,14>",
    }


def test_hls4ml_layer_list_uses_dedicated_global_average_pooling(tmp_path):
    onnx = pytest.importorskip("onnx")
    numpy = pytest.importorskip("numpy")
    from onnx import TensorProto, helper, numpy_helper

    model_path = tmp_path / "global_average_pool.onnx"
    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 8, 8])
    y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, 1, 1])
    reduce = helper.make_node("GlobalAveragePool", ["input"], ["output"], name="gap")
    graph = helper.make_graph([reduce], "gap_graph", [x], [y])
    model = helper.make_model(graph, opset_imports=[helper.make_operatorsetid("", 13)])
    onnx.save(model, model_path)

    adapter = HLS4MLAdapter(mock_mode=False)
    layers, _input, _output, rewrites = adapter._build_layer_list_from_onnx(onnx.load(model_path))

    gap_layer = next(layer for layer in layers if layer["name"] == "gap")
    assert gap_layer["class_name"] == "GlobalAveragePooling2D"
    assert gap_layer["in_height"] == 8
    assert gap_layer["n_filt"] == 3
    assert any("GlobalAveragePooling2D" in rewrite for rewrite in rewrites)


def test_hls4ml_layer_list_maps_spatial_reduce_mean_to_global_pooling(tmp_path):
    onnx = pytest.importorskip("onnx")
    numpy = pytest.importorskip("numpy")
    from onnx import TensorProto, helper, numpy_helper

    model_path = tmp_path / "reduce_mean_pool.onnx"
    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 8, 8])
    y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, 1, 1])
    axes = numpy_helper.from_array(numpy.asarray([2, 3], dtype=numpy.int64), name="axes")
    reduce = helper.make_node("ReduceMean", ["input", "axes"], ["output"], name="gap", keepdims=1)
    graph = helper.make_graph([reduce], "reduce_mean_graph", [x], [y], initializer=[axes])
    model = helper.make_model(graph, opset_imports=[helper.make_operatorsetid("", 13)])
    onnx.save(model, model_path)

    adapter = HLS4MLAdapter(mock_mode=False)
    layers, _input, _output, rewrites = adapter._build_layer_list_from_onnx(onnx.load(model_path))

    gap_layer = next(layer for layer in layers if layer["name"] == "gap")
    assert gap_layer["class_name"] == "GlobalAveragePooling2D"
    assert any("ReduceMean spatial axes" in rewrite for rewrite in rewrites)


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
    onnx = pytest.importorskip("onnx")
    numpy = pytest.importorskip("numpy")
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


def test_hls4ml_layer_list_adapter_supports_matmul_add_dense_pattern(tmp_path):
    onnx = pytest.importorskip("onnx")
    numpy = pytest.importorskip("numpy")
    from onnx import TensorProto, helper, numpy_helper

    x = helper.make_tensor_value_info("model_input", TensorProto.FLOAT, [1, 4])
    y = helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 2])
    weights = numpy_helper.from_array(numpy.ones((4, 2), dtype=numpy.float32), name="fc.weight")
    bias = numpy_helper.from_array(numpy.array([0.25, -0.25], dtype=numpy.float32), name="fc.bias")
    matmul = helper.make_node("MatMul", inputs=["model_input", "fc.weight"], outputs=["mm"], name="fc_matmul")
    add = helper.make_node("Add", inputs=["mm", "fc.bias"], outputs=["logits"], name="fc_bias")
    graph = helper.make_graph([matmul, add], "matmul_add_graph", [x], [y], initializer=[weights, bias])
    model = helper.make_model(graph)

    adapter = HLS4MLAdapter(mock_mode=False)
    layer_list, _input_layer, output_layer, rewrites = adapter._build_layer_list_from_onnx(model)
    dense_layers = [layer for layer in layer_list if layer.get("class_name") == "Dense"]

    assert output_layer == "fc_matmul"
    assert len(dense_layers) == 1
    assert dense_layers[0]["use_bias"] is True
    assert dense_layers[0]["n_in"] == 4
    assert dense_layers[0]["n_out"] == 2
    assert "MatMul static weight -> Dense layer-list" in rewrites
    assert "Add static bias -> folded into previous Dense/Conv2D" in rewrites


def test_hls4ml_layer_list_adapter_folds_batchnorm_after_conv():
    onnx = pytest.importorskip("onnx")
    numpy = pytest.importorskip("numpy")
    from onnx import TensorProto, helper, numpy_helper

    x = helper.make_tensor_value_info("model_input", TensorProto.FLOAT, [1, 1, 4, 4])
    y = helper.make_tensor_value_info("bn_out", TensorProto.FLOAT, [1, 2, 2, 2])
    conv_w = numpy_helper.from_array(numpy.ones((2, 1, 3, 3), dtype=numpy.float32), name="conv.weight")
    scale = numpy_helper.from_array(numpy.array([1.0, 2.0], dtype=numpy.float32), name="bn.scale")
    beta = numpy_helper.from_array(numpy.array([0.0, 0.5], dtype=numpy.float32), name="bn.beta")
    mean = numpy_helper.from_array(numpy.array([0.25, -0.25], dtype=numpy.float32), name="bn.mean")
    var = numpy_helper.from_array(numpy.array([1.0, 4.0], dtype=numpy.float32), name="bn.var")
    conv = helper.make_node("Conv", inputs=["model_input", "conv.weight"], outputs=["conv_out"], name="conv")
    bn = helper.make_node(
        "BatchNormalization",
        inputs=["conv_out", "bn.scale", "bn.beta", "bn.mean", "bn.var"],
        outputs=["bn_out"],
        name="bn",
        epsilon=1e-5,
    )
    graph = helper.make_graph([conv, bn], "conv_bn_graph", [x], [y], initializer=[conv_w, scale, beta, mean, var])
    model = helper.make_model(graph)

    adapter = HLS4MLAdapter(mock_mode=False)
    layer_list, _input_layer, output_layer, rewrites = adapter._build_layer_list_from_onnx(model)
    conv_layer = next(layer for layer in layer_list if layer.get("class_name") == "Conv2D")

    assert output_layer == "conv"
    assert conv_layer["use_bias"] is True
    assert conv_layer["bias_data"].shape == (2,)
    assert "BatchNormalization -> folded into previous Dense/Conv2D" in rewrites


def test_hls4ml_layer_list_adapter_rewrites_onnx18_spatial_reduce_mean():
    onnx = pytest.importorskip("onnx")
    numpy = pytest.importorskip("numpy")
    from onnx import TensorProto, helper, numpy_helper

    x = helper.make_tensor_value_info("model_input", TensorProto.FLOAT, [1, 1, 4, 4])
    y = helper.make_tensor_value_info("gap_out", TensorProto.FLOAT, [1, 2, 1, 1])
    conv_w = numpy_helper.from_array(numpy.ones((2, 1, 3, 3), dtype=numpy.float32), name="conv.weight")
    axes = numpy_helper.from_array(numpy.array([-1, -2], dtype=numpy.int64), name="reduce_axes")
    conv = helper.make_node(
        "Conv",
        inputs=["model_input", "conv.weight"],
        outputs=["conv_out"],
        name="conv",
        pads=[1, 1, 1, 1],
    )
    reduce_mean = helper.make_node(
        "ReduceMean",
        inputs=["conv_out", "reduce_axes"],
        outputs=["gap_out"],
        name="global_average",
        keepdims=1,
    )
    graph = helper.make_graph([conv, reduce_mean], "reduce_mean_graph", [x], [y], initializer=[conv_w, axes])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])

    adapter = HLS4MLAdapter(mock_mode=False)
    layer_list, _input_layer, output_layer, rewrites = adapter._build_layer_list_from_onnx(model)
    pool = next(layer for layer in layer_list if layer.get("class_name") == "AveragePooling2D")

    assert output_layer == "global_average"
    assert pool["pool_height"] == 4
    assert pool["pool_width"] == 4
    assert pool["n_filt"] == 2
    assert "ReduceMean spatial axes -> channels_last AveragePooling2D" in rewrites


def test_hls4ml_layer_list_adapter_supports_static_shape_helpers_for_reshape():
    onnx = pytest.importorskip("onnx")
    numpy = pytest.importorskip("numpy")
    from onnx import TensorProto, helper, numpy_helper

    x = helper.make_tensor_value_info("model_input", TensorProto.FLOAT, [1, 2, 2])
    y = helper.make_tensor_value_info("flat", TensorProto.FLOAT, [1, 4])
    c0 = helper.make_node(
        "Constant",
        inputs=[],
        outputs=["shape_dim0"],
        value=numpy_helper.from_array(numpy.array([1], dtype=numpy.int64)),
        name="shape_dim0_const",
    )
    c1 = helper.make_node(
        "Constant",
        inputs=[],
        outputs=["shape_dim1"],
        value=numpy_helper.from_array(numpy.array([4], dtype=numpy.int64)),
        name="shape_dim1_const",
    )
    concat = helper.make_node("Concat", inputs=["shape_dim0", "shape_dim1"], outputs=["target_shape"], name="shape_concat", axis=0)
    reshape = helper.make_node("Reshape", inputs=["model_input", "target_shape"], outputs=["flat"], name="flat_reshape")
    graph = helper.make_graph([c0, c1, concat, reshape], "reshape_helpers_graph", [x], [y])
    model = helper.make_model(graph)

    adapter = HLS4MLAdapter(mock_mode=False)
    layer_list, _input_layer, output_layer, rewrites = adapter._build_layer_list_from_onnx(model)
    reshape_layer = next(layer for layer in layer_list if layer.get("class_name") == "Reshape")

    assert output_layer == "flat_reshape"
    assert reshape_layer["target_shape"] == [4]
    assert "Constant -> static shape helper eliminated" in rewrites
    assert "Concat -> static shape helper eliminated" in rewrites
    assert "Reshape -> static Reshape" in rewrites


def test_hls4ml_layer_list_adapter_rejects_branching_dataflow():
    onnx = pytest.importorskip("onnx")
    numpy = pytest.importorskip("numpy")
    from onnx import TensorProto, helper, numpy_helper

    x = helper.make_tensor_value_info("model_input", TensorProto.FLOAT, [1, 4])
    y = helper.make_tensor_value_info("out", TensorProto.FLOAT, [1, 2])
    w1 = numpy_helper.from_array(numpy.ones((4, 2), dtype=numpy.float32), name="w1")
    w2 = numpy_helper.from_array(numpy.ones((4, 2), dtype=numpy.float32), name="w2")
    branch_a = helper.make_node("MatMul", inputs=["model_input", "w1"], outputs=["a"], name="branch_a")
    branch_b = helper.make_node("MatMul", inputs=["model_input", "w2"], outputs=["b"], name="branch_b")
    add = helper.make_node("Add", inputs=["a", "b"], outputs=["out"], name="residual_add")
    graph = helper.make_graph([branch_a, branch_b, add], "branch_graph", [x], [y], initializer=[w1, w2])
    model = helper.make_model(graph)

    adapter = HLS4MLAdapter(mock_mode=False)
    with pytest.raises(ValueError, match="Branched/residual graphs need a real graph compiler"):
        adapter._build_layer_list_from_onnx(model)


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
