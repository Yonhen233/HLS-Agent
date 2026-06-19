# MNIST LLM Candidate Resource Optimization

Date: 2026-06-19

This note records the direct LLM-generated HLS candidate experiment for the trained MNIST MLP demo. The goal was resource reduction under real Vivado HLS 2018.3, while keeping the 20-sample golden recognition accuracy at the existing 19/20 threshold.

## Baseline

Baseline is the best hls4ml resource-priority profile recorded before this experiment.

| Path | Accuracy | Latency | BRAM | DSP | FF | LUT | Resource Score |
|---|---:|---:|---:|---:|---:|---:|---:|
| hls4ml resource-priority | 19/20 | 2135 | 47 | 64 | 5999 | 17899 | 41398 |

Resource score is a local comparison metric:

```text
score = LUT + FF + 200 * DSP + 100 * BRAM
```

## LLM Candidate Method

The LLM did not receive the full weight matrix. Instead, it received the model contract, baseline metrics, previous attempt summaries, and the fixed top-function contract:

```cpp
void mnist_llm_candidate(data_t input[784], data_t output[10]);
```

The script then injects the real ONNX weights and 20 golden MNIST samples into generated HLS artifacts, scans the candidate with `CandidateSandbox`, and runs real Vivado HLS `csim_design + csynth_design`.

Script:

```powershell
python scripts\llm_mnist_hls_candidate.py --continue-run --attempts 1 --clock-period 15 --required-correct 19
```

## Attempt Matrix

| Attempt | Candidate | Golden CSim | Latency | BRAM | DSP | FF | LUT | Score | Notes |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `mnist_minimal_serial_8bit` | failed | - | - | - | - | - | - | 8-bit activation path failed csim. |
| 2 | `mnist_mixed_fixed_16_8` | passed | 105409 | 34 | 3 | 302 | 602 | 4904 | First verified direct candidate. |
| 3 | `mnist_serial_32bit_fix` | passed | 107777 | 35 | 3 | 356 | 733 | 5189 | Wider accumulators did not improve score. |
| 4 | `mnist_fixed32_nosat` | failed | - | - | - | - | - | - | LLM used `accum_t` instead of `acc_t`; compile failed. |
| 5 | `mnist_serial_narrow_16_4` | passed | 157953 | 18 | 0 | 422 | 1443 | 3665 | 8-bit weights and serial MAC removed DSP. |
| 6 | `mnist_narrow_accum_24` | passed | 157953 | 18 | 0 | 371 | 911 | 3082 | Narrower accumulator reduced LUT/FF. |
| 7 | `mnist_narrow_accum_20` | passed | 157953 | 18 | 0 | 347 | 899 | 3046 | Best verified resource profile. |
| 8 | `mnist_narrow_accum_15_14` | failed | - | - | - | - | - | - | Accuracy collapsed to 3/20, proving the lower precision boundary. |

## Best Candidate

Best verified candidate:

```text
candidate = mnist_narrow_accum_20
data_t    = ap_fixed<16,4,AP_RND,AP_SAT>
weight_t  = ap_fixed<8,4,AP_RND,AP_SAT>
acc_t     = ap_fixed<20,16,AP_RND>
```

| Metric | hls4ml Baseline | LLM Candidate | Change |
|---|---:|---:|---:|
| BRAM | 47 | 18 | -61.7% |
| DSP | 64 | 0 | -100.0% |
| FF | 5999 | 347 | -94.2% |
| LUT | 17899 | 899 | -95.0% |
| Score | 41398 | 3046 | -92.6% |
| Latency | 2135 | 157953 | +74.0x |

## Interpretation

This is a resource-first Pareto point, not a low-latency point. The LLM discovered a serial shared-MAC implementation that removes parallelism and hls4ml overhead, dramatically reducing area at the cost of much higher latency.

The result is useful because it demonstrates two complementary paths:

- hls4ml path: better latency and more standard generated project structure.
- LLM candidate path: aggressive resource minimization when latency is less important.

The golden testbench is the safety gate. Attempt 8 shows that a plausible LLM suggestion can be rejected when real C simulation proves accuracy loss.

## Objective-Specific Follow-Up: Resource / Balanced / Throughput

After the resource-first run, the script was extended with explicit objectives:

```powershell
python scripts\llm_mnist_hls_candidate.py --objective resource --continue-run --attempts 1 --clock-period 15 --required-correct 19
python scripts\llm_mnist_hls_candidate.py --objective balanced --continue-run --attempts 3 --clock-period 15 --required-correct 19
python scripts\llm_mnist_hls_candidate.py --objective throughput --continue-run --attempts 4 --clock-period 15 --required-correct 19
```

Objective contracts:

| Objective | Contract |
|---|---|
| `resource` | Minimize resource score while passing golden CSim. |
| `balanced` | Keep resource score below hls4ml baseline and improve latency/II versus the serial LLM resource candidate. |
| `throughput` | Improve latency and top interval/II versus hls4ml baseline; resources may increase. |

The script now records `objective_met` separately from CSim/csynth success. This matters because a candidate can be functionally correct and synthesizable but still miss the chosen design objective.

## Pareto Points Found

| Path | Candidate | Golden CSim | Latency | II / Interval | BRAM | DSP | FF | LUT | Resource Score | Interpretation |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| hls4ml baseline | hls4ml resource profile | passed | 2135 | 1024 | 47 | 64 | 5999 | 17899 | 41398 | Standard hls4ml project with dataflow. |
| LLM resource-first | `mnist_narrow_accum_20` | passed | 157953 | 157953 | 18 | 0 | 347 | 899 | 3046 | Very small area, very low throughput. |
| LLM balanced | `balanced_UF8_layerwise` | passed | 6776 | 6776 | 24 | 0 | 1391 | 4158 | 7949 | About 23x faster than serial LLM while still far below hls4ml resources. |
| LLM throughput-first | `throughput_pipe_II1` | passed | 465 | 465 | 0 | 0 | 38783 | 68311 | 107094 | Beats hls4ml II/latency, but LUT exceeds the current xc7z020 capacity. |

## Updated Feasible Pareto Points

Follow-up controlled repair experiments tightened the objective definitions:

- `balanced` now keeps `resource_score <= 12000`.
- `throughput` must beat hls4ml latency/II and fit the xc7z020 report capacity.
- Orphan attempt results are merged from disk with `--continue-run --attempts 0`.

Latest verified points:

| Path | Candidate | Golden CSim | Latency | II / Interval | BRAM | DSP | FF | LUT | Resource Score | Fits xc7z020 | Interpretation |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| hls4ml baseline | hls4ml resource profile | passed | 2135 | 1024 | 47 | 64 | 5999 | 17899 | 41398 | yes | Standard hls4ml baseline. |
| LLM resource-first | `mnist_narrow_accum_20` | passed | 157953 | 157953 | 18 | 0 | 347 | 899 | 3046 | yes | Minimum-resource serial design. |
| LLM strict-balanced | `balanced_UF16_8_10_II1` | passed | 3906 | 3906 | 24 | 0 | 2577 | 5540 | 10517 | yes | Best under the current balanced resource budget. |
| LLM performance-balanced | `balanced_control_UF32_8_10` | passed | 2388 | 2388 | 40 | 0 | 3883 | 7715 | 15598 | yes | Faster than strict-balanced, but above the strict score budget. |
| LLM feasible-throughput | `throughput_control_UF64_input2_UF32_10` | passed | 545 | 545 | 126 | 0 | 4209 | 33364 | 50173 | yes | Current best feasible II/latency candidate. |
| LLM throughput boundary | `throughput_control_UF64_input4_UF32_10` | passed | 545 | 545 | 2 | 0 | 8342 | 49891 | 58433 | yes | More input unroll did not improve II and cost more LUT. |

Compared with hls4ml, the feasible-throughput candidate reduces latency by 74.5% and II by 46.8%, while using no DSP. The trade-off is higher LUT and BRAM usage.

## Recovered Orphan Results

During a long Vivado run, several results had been written to `attempt_*/attempt_result.json` but not merged into `summary.json`. The recovery pass found and merged them. The most important lesson from those orphan attempts is that not every low-II candidate is deployable:

| Candidate | Latency / II | Main Failure |
|---|---:|---|
| `throughput_pipe_II1_input_cyclic16_repair` | 490 | LUT exceeded xc7z020 capacity. |
| `throughput_pipe_input_cyclic8_w1_8_repair` | 514 | BRAM and LUT exceeded capacity. |
| `throughput_pipe_no_input_partition_repair` | 857 | LUT exceeded capacity. |
| `throughput_pipe_no_input_weight16_dsp_repair` | 944 | DSP and LUT exceeded capacity. |

These recovered failures are useful memory: they explain why the final feasible-throughput design uses 2-way input parallelism rather than 4/8/16-way or forced-DSP variants.

## Lessons From Real HLS Feedback

- The LLM can generate qualitatively different HLS architectures when the objective is explicit.
- A high-parallelism candidate is not automatically a balanced candidate; objective-specific acceptance checks are necessary.
- `ap_fixed<W,I>` without `AP_SAT` may pass width checks but fail golden accuracy because default overflow can wrap.
- Vivado HLS 2018.3 pragma syntax must be guarded. The tool rejected `type=cyclic` in generated `ARRAY_PARTITION` pragmas.
- `DATAFLOW` and `STREAM` pragmas on ordinary arrays may look parallel but can synthesize poorly; real report feedback is the judge.

The most interview-relevant takeaway is that this is not a one-shot code generation demo. The Agent records real synthesis and verification observations, tightens prompts and guards, and uses objective-specific scoring to explore the HLS Pareto surface.
