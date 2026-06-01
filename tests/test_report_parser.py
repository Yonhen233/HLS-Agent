from dl_op_to_hls.tools.report_parser import parse_csynth_report_file


def test_report_parser_parses_fixture(sample_csynth_report_path):
    result = parse_csynth_report_file(str(sample_csynth_report_path))
    assert result["latency"]["min_cycles"] == 45

