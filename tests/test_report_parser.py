from dl_op_to_hls.tools.report_parser import parse_csynth_report_file


def test_report_parser_parses_fixture(sample_csynth_report_path):
    result = parse_csynth_report_file(str(sample_csynth_report_path))
    assert result["latency"]["min_cycles"] == 45


def test_report_parser_parses_vitis_timing_with_ns_units(tmp_path):
    report = tmp_path / "myproject_csynth.rpt"
    report.write_text(
        "\n".join(
            [
                "+ Timing:",
                "|  Clock |  Target  | Estimated| Uncertainty|",
                "|ap_clk  |  10.00 ns|  9.070 ns|     2.70 ns|",
                "+ Latency:",
                "| 6826 | 6972 | 6826 | 6972 | none |",
                "== Utilization Estimates",
                "|       Name      | BRAM_18K| DSP |   FF   |  LUT  | URAM|",
                "|Total            |       10|    0|  133712| 111638|    0|",
            ]
        ),
        encoding="utf-8",
    )

    result = parse_csynth_report_file(str(report))

    assert result["status"] == "success"
    assert result["timing"]["target_ns"] == 10.0
    assert result["timing"]["estimated_ns"] == 9.07
    assert result["timing"]["uncertainty_ns"] == 2.7
    assert result["timing"]["effective_budget_ns"] == 7.3
    assert result["timing"]["met"] is False
    assert result["resources"]["lut"] == 111638


def test_report_parser_prefers_vivado_latency_summary_interval(tmp_path):
    report = tmp_path / "myproject_csynth.rpt"
    report.write_text(
        "\n".join(
            [
                "+ Latency (clock cycles):",
                "    * Summary:",
                "    +------+------+------+------+----------+",
                "    |   Latency   |   Interval  | Pipeline |",
                "    |  min |  max |  min |  max |   Type   |",
                "    +------+------+------+------+----------+",
                "    |  2132|  2135|  1024|  1024| dataflow |",
                "    +------+------+------+------+----------+",
                "|Total            |       47|   64|    5999|  17899|",
            ]
        ),
        encoding="utf-8",
    )

    result = parse_csynth_report_file(str(report))

    assert result["latency"]["max_cycles"] == 2135
    assert result["interval"]["min_ii"] == 1024
    assert result["interval"]["max_ii"] == 1024
