#!/bin/bash
set -ex
    
# vllm serve Qwen/Qwen3-4B --gpu-memory-utilization 0.88 --enforce-eager --rope-scaling '{"rope_type":"yarn","factor":4.0,"original_max_position_embeddings":32768}' --max-model-len 131072   --max-num-seqs 15

vllm serve Qwen/Qwen3-4B --gpu-memory-utilization 0.92 --enforce-eager --rope-scaling '{"rope_type":"yarn","factor":4.0,"original_max_position_embeddings":32768}' --max-model-len 94592   --max-num-seqs 15  --enable-auto-tool-choice --tool-call-parser hermes --reasoning-parser deepseek_r1