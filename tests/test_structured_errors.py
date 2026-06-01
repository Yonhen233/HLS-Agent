from dl_op_to_hls.core.errors import build_error


def test_structured_error_format():
    error = build_error("VivadoNotFoundError", "missing", recoverable=True, source="vivado.run_csynth")
    payload = error.to_dict()
    assert payload["error_type"] == "VivadoNotFoundError"
    assert payload["recoverable"] is True

