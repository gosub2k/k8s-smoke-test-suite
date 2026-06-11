#!/usr/bin/env bats
# 1-GPU pod with nvidia runtime can run torch + CUDA.
load helpers

@test "GPU torch pod runs" {
  skip "need to figure out torch and cuda version first"
}
