# Vivado HLS Failure Playbook

## VivadoNotFoundError

`VivadoNotFoundError` means the `vivado_hls` executable or configured `vivado_hls.bat` path cannot be found by the runtime.

This is a recoverable toolchain failure:

1. Mark the synthesis todo as skipped.
2. Keep generated HLS C++ / TCL / testbench artifacts.
3. Set the run status to `partial_success`, not `success`.
4. Explain that synthesis was skipped because Vivado HLS is unavailable.
5. Suggest rerunning on a machine with Vivado HLS installed or setting `DL_OP_TO_HLS_VIVADO_HLS_PATH`.

The Agent should not fabricate latency, II, DSP, BRAM, LUT, FF, or timing metrics when synthesis is skipped.

Useful query terms:

- VivadoNotFoundError
- recoverable
- skipped synthesis
- partial_success
- Vivado HLS path
