# MCP Tools

P0 采用 in-process MCP 风格接口：虽然没有强制拆成独立进程，但工具定义、输入输出和注册方式已经对齐 MCP 思想。

## hls4ml tools

- `hls4ml.inspect_model`
- `hls4ml.check_support`
- `hls4ml.generate_config`
- `hls4ml.convert`
- `hls4ml.run_csim`

## Vivado HLS tools

- `vivado.create_project`
- `vivado.run_csim`
- `vivado.run_csynth`
- `vivado.parse_report`
- `vivado.parse_log`

## Local tools

- `graph_rewrite.rewrite`
- `fallback.generate_operator_hls`
- `fallback.generate_testbench`
- `llm.generate_candidate`
- `verify_candidate.run`
- `db.save_*`
- `rag.retrieve_experience`
- `rag.index_artifact`
- `summary.write_summary`
- `suggestion.suggest_optimization`

