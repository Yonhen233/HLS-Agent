from __future__ import annotations

from dl_op_to_hls.core.design_objectives import (
    get_objective_mode,
    list_objective_modes,
    normalize_objective_mode,
    objective_requires_llm_search,
)
from dl_op_to_hls.tools.parameter_advisor import _resource_cost


def test_objective_mode_aliases_are_normalized():
    assert normalize_objective_mode("area") == "resource"
    assert normalize_objective_mode("ii") == "throughput"
    assert normalize_objective_mode("speed") == "performance"
    assert normalize_objective_mode("hls4ml") == "standard"


def test_objective_modes_explain_agent_policy():
    mode = get_objective_mode("throughput")
    assert mode.primary_metric == "ii_cycles"
    assert "II" in mode.acceptance_rule
    assert "VivadoSpecialist" in mode.specialist_effect


def test_standard_mode_does_not_require_llm_search():
    assert objective_requires_llm_search("standard") is False
    assert objective_requires_llm_search("resource") is True


def test_list_objective_modes_contains_configurable_modes():
    names = {item["name"] for item in list_objective_modes()}
    assert {"standard", "resource", "latency", "throughput", "performance", "balanced"}.issubset(names)


def test_parameter_advisor_objective_cost_changes_ranking_signal():
    report_fast_high_resource = {
        "latency": {"max_cycles": 500},
        "interval": {"max_ii": 500},
        "resources": {"lut": 30000, "ff": 10000, "dsp": 0, "bram": 100},
    }
    report_slow_low_resource = {
        "latency": {"max_cycles": 150000},
        "interval": {"max_ii": 150000},
        "resources": {"lut": 900, "ff": 300, "dsp": 0, "bram": 18},
    }
    assert _resource_cost(report_slow_low_resource, "resource") < _resource_cost(report_fast_high_resource, "resource")
    assert _resource_cost(report_fast_high_resource, "latency") < _resource_cost(report_slow_low_resource, "latency")
    assert _resource_cost(report_fast_high_resource, "throughput") < _resource_cost(report_slow_low_resource, "throughput")
