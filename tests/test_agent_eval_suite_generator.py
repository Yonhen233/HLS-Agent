import json


def test_checked_in_expansion_suite_is_partitioned():
    payload = json.loads(open("benchmarks/agent_interview_open_tasks_v2.json", encoding="utf-8").read())
    cases = payload["cases"]
    assert len(cases) == 30
    assert len({case["id"] for case in cases}) == 30
    assert sum(case["split"] == "dev" for case in cases) == 10
    assert sum(case["split"] == "test_semantic_variation" for case in cases) == 20
    assert all(case.get("source_case_id") for case in cases)
    assert all(case["id"].startswith("v2_dev_") for case in cases if case["split"] == "dev")
