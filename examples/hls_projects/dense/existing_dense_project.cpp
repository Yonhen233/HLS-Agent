#include "existing_dense_project.h"

void existing_dense_project(const data_t input[16], data_t output[16]) {
  for (int i = 0; i < 16; ++i) {
    output[i] = input[i];
  }
}

