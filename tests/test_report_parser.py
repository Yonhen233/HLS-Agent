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
                "|Available        |      280|  220|  106400|  53200|",
                "|Utilization (%)  |       16|   29|       5|     33|",
                "Timing (ns): Target = 10.00, Estimated = 8.00",
            ]
        ),
        encoding="utf-8",
    )

    result = parse_csynth_report_file(str(report))

    assert result["latency"]["max_cycles"] == 2135
    assert result["interval"]["min_ii"] == 1024
    assert result["interval"]["max_ii"] == 1024
    assert result["resource_available"] == {"bram": 280, "dsp": 220, "ff": 106400, "lut": 53200}
    assert result["resource_utilization_percent"] == {"bram": 16, "dsp": 29, "ff": 5, "lut": 33}
    assert result["resource_feasible"] is True


def test_report_parser_marks_resource_infeasible(tmp_path):
    report = tmp_path / "too_large_csynth.rpt"
    report.write_text(
        "\n".join(
            [
                "+ Latency (clock cycles):",
                "| 465 | 465 | 465 | 465 | none |",
                "== Utilization Estimates",
                "|       Name      | BRAM_18K| DSP48E|   FF   |  LUT  |",
                "|Total            |        0|      0|   38783|  68311|",
                "|Available        |      280|    220|  106400|  53200|",
                "|Utilization (%)  |        0|      0|      36|    128|",
                "Timing (ns): Target = 10.00, Estimated = 8.00",
            ]
        ),
        encoding="utf-8",
    )

    result = parse_csynth_report_file(str(report))

    assert result["resources"]["lut"] == 68311
    assert result["resource_available"]["lut"] == 53200
    assert result["resource_utilization_percent"]["lut"] == 128
    assert result["resource_feasible"] is False


def test_report_parser_rejects_missing_timing_section(tmp_path):
    report = tmp_path / "missing_timing_csynth.rpt"
    report.write_text(
        "\n".join(
            [
                "| 10 | 10 | 1 | 1 | none |",
                "|Total | 0 | 1 | 10 | 20 |",
            ]
        ),
        encoding="utf-8",
    )
    result = parse_csynth_report_file(str(report))
    assert result["status"] == "error"
    assert result["error"]["error_type"] == "ReportParseError"
    assert "timing" in result["error"]["details"]["missing_sections"]
