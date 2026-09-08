from __future__ import annotations

from ..core.tool_registry import ToolSpec


def register_mcp_proxy_tools(registry, local_specs: list[ToolSpec], client) -> None:
    """Expose remote MCP tools through the same policy/trace/budget harness as local tools."""
    remote = {item["name"]: item for item in client.list_tools()}
    for local in local_specs:
        manifest = remote.get(local.name)
        if manifest is None:
            continue

        def handler(arguments, context, *, tool_name=local.name):
            cancellation = context.get("cancellation_token")
            if cancellation is not None and cancellation.cancelled:
                return {"status": "interrupted", "reason": cancellation.reason}
            return client.call_tool(
                tool_name,
                arguments,
                timeout_seconds=local.timeout_seconds,
                cancellation_token=cancellation,
            )

        remote_output_schema = manifest.get("outputSchema")
        if remote_output_schema and remote_output_schema != local.output_schema:
            raise ValueError(f"MCP output schema mismatch for {local.name}")

        registry.register(
            ToolSpec(
                name=local.name,
                description=str(manifest.get("description") or local.description),
                input_schema=dict(manifest.get("inputSchema") or local.input_schema),
                output_schema=dict(remote_output_schema or local.output_schema),
                permission_level=local.permission_level,
                handler=handler,
                server=client.name,
                tags=list(local.tags or []) + ["remote"],
                idempotent=local.idempotent,
                cacheable=local.cacheable,
                parallel_safe=local.parallel_safe,
                max_retries=local.max_retries,
                required_capabilities=local.required_capabilities,
                risk_level=local.risk_level,
                timeout_seconds=local.timeout_seconds,
            )
        )
