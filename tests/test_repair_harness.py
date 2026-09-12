from types import SimpleNamespace

from dl_op_to_hls.adapters.legacy_vivado_env import HLSVerificationEnv
from dl_op_to_hls.adapters.vivado_hls_adapter import VivadoHLSAdapter
from dl_op_to_hls.core.repair_evidence import collect_repair_evidence
from dl_op_to_hls.skills.policy import SkillPolicy


def test_repair_evidence_escalates_to_bounded_vivado_tail(tmp_path):
    log = tmp_path / "csynth.log"
    log.write_text(
        "Starting synthesis...\n"
        "Dataflow strict check failed\n"
        "INFO: [Common 17-206] Exiting vivado_hls\n",
        encoding="utf-8",
    )

    evidence = collect_repair_evidence({"details": {"log_path": str(log)}})

    assert evidence["status"] == "available"
    assert evidence["diagnosis"] == "synthesis_schedule_error"
    assert "Dataflow strict check failed" in evidence["matched_lines"]
    assert str(log) in evidence["log_paths"]


def test_vivado_adapter_surfaces_schedule_failure_as_structured_error(tmp_path):
    log = tmp_path / "csynth.log"
    log.write_text("Dataflow strict check failed\n", encoding="utf-8")

    assert "Dataflow strict check failed" in VivadoHLSAdapter._hls_log_errors(log)


def test_vivado_tcl_stages_candidate_inputs(tmp_path):
    code = tmp_path / "relu.cpp"
    testbench = tmp_path / "testbench.cpp"
    code.write_text("void relu() {}\n", encoding="utf-8")
    testbench.write_text("int main() { return 0; }\n", encoding="utf-8")

    tcl = HLSVerificationEnv("missing-vivado").create_project_tcl(
        project_dir=str(tmp_path),
        project_name="candidate_project",
        top_function="relu",
        code_file=str(code),
        testbench_file=str(testbench),
    )
    contents = (tmp_path / "run_candidate_project.tcl").read_text(encoding="utf-8")

    assert tcl.endswith("run_candidate_project.tcl")
    assert contents.count("open_project -reset candidate_project") == 1
    assert "add_files relu.cpp" in contents
    assert "add_files -tb testbench.cpp" in contents
    assert contents.count("open_solution -reset \"solution1\"") == 1


def test_runtime_owned_summary_is_not_a_skill_capability_error():
    skill = SimpleNamespace(
        status="approved",
        name="llm_candidate_verification_flow",
        tags=[],
        budget_policy={"max_steps": 8},
        preconditions=[],
        verification_policy={},
        allowed_tools={"task.validate_schema"},
        allowed_specialists=set(),
    )
    plan = {
        "todos": [
            {
                "assigned_tool": "summary.write_summary",
                "assigned_specialist": None,
            }
        ]
    }

    result = SkillPolicy().validate_llm_plan_against_skill(plan, skill, {})

    assert result["status"] == "valid"
