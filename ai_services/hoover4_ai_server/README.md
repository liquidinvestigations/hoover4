# Serve embeddings, reranking, and named entities.

[The FastAPI server](hoover4_ai_server.py) provides separate model capabilities.
[The optional AI tier](../README.md) deploys this service and supplies its configuration.
The main pipeline and agent services call it through their configured endpoints.

## Verify configured and serving models.

| Capability | Source default | Selection |
|---|---|---|
| Embeddings | `intfloat/multilingual-e5-small`, 384 dimensions | `EMBEDDINGS_MODEL` and `EMBEDDINGS_DIM` |
| Reranking | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | `RERANKER_MODEL` |
| NER | `FacebookAI/xlm-roberta-large-finetuned-conll03-english` | `NER_MODEL` |

Deployment renders these values from `hoover4.ini`.
A deployment can select different values from the source defaults.
`AI_SERVER_ENABLE_EMBEDDINGS`, `AI_SERVER_ENABLE_RERANKER`, and `AI_SERVER_ENABLE_NER` enable their respective capabilities.
Startup loads the enabled models and verifies the embedding dimension.
An embedding request that names a different model returns an error.
`GET /health` reports readiness, model information, dimensions, admission counters, and available device information.

## Use the HTTP routes.

| Method and route | Result |
|---|---|
| `GET /` | Server information and available routes. |
| `GET /health` | Model readiness, configuration fingerprint, admission state, and device information. |
| `GET /v1/models` | The available model listing. |
| `POST /v1/embeddings` | An embedding for each supplied input. |
| `POST /v1/rerank` | Document relevance scores for a query. |
| `POST /v1/extract-entities` | Named entity spans and their model information. |
| `GET /performance-stats` | Current performance counters and configuration. |

Supply the configured base URL through the private command environment.
These examples use the environment variable `AI_SERVER_URL` for that base URL.
They do not select a deployment address.

```sh
curl -X POST "$AI_SERVER_URL/v1/embeddings" \
  -H 'Content-Type: application/json' \
  -d '{"input": ["A sample passage."]}'
```

The ingestion and search callers apply the selected model's query and passage prefix conventions.
[The pipeline prefix helper](../../main_services/processing/tasks/P5_chunk_embed/embedding_prefix.py) and [the agent prefix helper](../../main_services/agents/agent_common/agent_common/embeddings.py) must agree.

```sh
curl -X POST "$AI_SERVER_URL/v1/rerank" \
  -H 'Content-Type: application/json' \
  -d '{"query":"contract terms","documents":["Contract terms appear here.","A different topic."],"top_k":2}'

curl -X POST "$AI_SERVER_URL/v1/extract-entities" \
  -H 'Content-Type: application/json' \
  -d '{"input":"A sample document names London.","include_confidence":true}'
```

## Bound admission by capability.

[Admission control](admission.py) provides separate inference pools and queue limits.
`AI_SERVER_NER_CONCURRENCY`, `AI_SERVER_EMBED_CONCURRENCY`, and `AI_SERVER_RERANK_CONCURRENCY` set the active slots.
The associated queue-depth settings bound waiting requests.
A request above active and waiting capacity receives HTTP 503 with `Retry-After`.
Inference runs outside the request event loop so health requests can still proceed.
A busy response does not establish that a model endpoint is unreachable.

## Build and run through deployment.

[The Dockerfile](Dockerfile) builds the runtime environment from the service requirements.
[The requirements file](requirements.txt) pins the runtime dependencies.
[The Poetry manifest](pyproject.toml) also describes the package, but does not replace the container build contract.
Use the [AI deployment procedure](../README.md#deploy) to build and start this service.

`OPTIMAL_BATCH_SIZE` and `MAX_SEQUENCE_LENGTH` bound batch and sequence behavior.
`ENABLE_HALF_PRECISION` and `ENABLE_TORCH_COMPILE` control optional model execution settings.
The server selects CUDA when available and CPU otherwise.
That internal device choice does not create a deployed CPU embedding fallback.
[AI architecture](../../docs/architecture/AI_Services.md) defines the pipeline's capability and fallback behavior.

## Measure performance in the intended environment.

Record the model, device, input lengths, batch size, concurrency, and tested revision with each result.
The source does not establish throughput from a GPU core-count ratio.
A performance suggestion returned by the server is not a measured result for another deployment.
[Throughput tests](tests/test_throughput.py) and [batch tests](tests/test_batch_optimization.py) record measurements against a running service.

## Verify the running service.

[HTTP tests](tests/) require a reachable server and can skip when no server answers.
A skipped test does not verify the capability.
The runtime image does not include the test suite or test runner.
Use the container-based [test procedure](../README.md#testing) with the checkout mounted into the test image.
Select the health, embedding, reranking, NER, and admission tests required by the configured capabilities.
