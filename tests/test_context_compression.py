from dl_op_to_hls.core.context import ContextCompressor


def test_context_compression_log(tmp_path):
    log_path = tmp_path / "csynth.log"
    log_path.write_text("WARNING: demo warning\n", encoding="utf-8")
    compressor = ContextCompressor()
    summary = compressor.compress_vivado_log(str(log_path))
    assert "warning" in summary["summary"].lower()

