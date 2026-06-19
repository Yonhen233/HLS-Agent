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

