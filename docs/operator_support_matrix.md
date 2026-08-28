# Operator Support Matrix

主生成策略为 LLM Candidate。确定性模板仅作为公平对照和已验证实现复用来源，不是默认降级路径。

| Operator | LLM | Template | Functional cases | Real CSim | Real CSynth | Mock | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| Dense | yes | yes | 24 | 3 | 3 | 3 | functional_reference_ready |
| MatMul | yes | yes | 24 | 3 | 3 | 0 | functional_reference_ready |
| ReLU | yes | yes | 18 | 3 | 3 | 0 | functional_reference_ready |
| Add | yes | yes | 18 | 3 | 3 | 0 | functional_reference_ready |
| ScaleShift | yes | no | 18 | 3 | 3 | 0 | functional_reference_ready |
| Conv2D | yes | no | 18 | 3 | 3 | 1 | functional_reference_ready |

## 口径

- `functional_case_count` 表示独立 Python 数学/位精确 Golden Case，不表示 HLS 已验证。
- `real_csim_count` 与 `real_csynth_count` 只接受当前 Run 内、有哈希且明确标记为真实工具的证据。
- Mock、Fixture 和历史未迁移 Run 单独统计，不参与真实成功率。
