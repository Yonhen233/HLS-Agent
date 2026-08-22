from dl_op_to_hls.core.agent_messages import AgentMessageBus


def test_agent_message_bus_correlates_delegation(tmp_path):
    path = tmp_path / "messages.jsonl"
    bus = AgentMessageBus(path)
    request = bus.publish(
        message_type="delegation_request",
        sender="MainAgent",
        recipient="VerificationSpecialist",
        payload={"todo_id": "todo_001"},
    )
    bus.publish(
        message_type="delegation_result",
        sender="VerificationSpecialist",
        recipient="MainAgent",
        correlation_id=request.correlation_id,
        parent_message_id=request.message_id,
        payload={"status": "success"},
    )

    history = bus.history(correlation_id=request.correlation_id)
    assert [item["message_type"] for item in history] == ["delegation_request", "delegation_result"]

    path.write_text("{broken projection", encoding="utf-8")
    peer = AgentMessageBus(path)
    peer_history = peer.history(correlation_id=request.correlation_id)
    assert [item["message_type"] for item in peer_history] == ["delegation_request", "delegation_result"]
