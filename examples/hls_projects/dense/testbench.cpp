#include "existing_dense_project.h"
#include <cstdio>

int main() {
  data_t input[16];
  data_t output[16] = {0};
  for (int i = 0; i < 16; ++i) {
    input[i] = static_cast<data_t>(i - 8);
  }
  existing_dense_project(input, output);
  for (int i = 0; i < 16; ++i) {
    if (output[i] != input[i]) {
      std::printf("GOLDEN_CHECK_FAILED index=%d expected=%f actual=%f\n", i, input[i], output[i]);
      return 1;
    }
  }
  std::printf("GOLDEN_CHECK_PASSED\n");
  return 0;
}
