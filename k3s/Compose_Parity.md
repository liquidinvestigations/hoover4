# Compose parity of the cluster render

This table names every service of the Compose files and its form in the cluster.
[manifests.py](hoover/manifests.py) holds the same classification in `SERVICES`.
The render suite compares the two, and it compares both with the Compose files of both sides.
A Compose service without a row stops the render with an error that names the service and its file.

The render has two store layouts and two Temporal backends.
The site file sets both for each Hoover installation.
See [the k3s Readme](Readme.md) for the site file.

- The local layout runs the Compose stores in the Hoover namespace on claims of the home node.
- The zone layout runs ClickHouse, Manticore and Garage in Kata on block volumes in the zone namespace.
- The `cassandra` backend runs Temporal, Cassandra and Elasticsearch as Compose runs them.
- The `postgresql` backend runs Temporal on the PostgreSQL of the zone. Existing remote zones use it.

## Services

| Service | Role | Compose file | Local layout | Zone layout | Notes |
|---|---|---|---|---|---|
| `hoover4-website` | app | `docker-compose.yaml`, `website-release.yaml` | Deployment `hoover-website` | Deployment `hoover-website` | Release image, `/app/server`. oauth2-proxy is the only client. Upload space on the claim `upload-tmp`. |
| `hoover4-worker` | app | `docker-compose.yaml` | StatefulSet `hoover-workers` on the home node, and Deployment `hoover-singletons` | Deployment `hoover-workers` spread over the nodes, and Deployment `hoover-singletons` | Plan files on one claim for each worker pod in the local layout. `hoover-singletons` runs the migrations, the index planner, the email graph and the chat worker once. |
| `hoover4-ops` | app | `docker-compose.yaml` | Deployment `hoover-operations` with `/backups` and the store claims | Deployment `hoover-operations` with `/backups` | The zone layout has no `/stores` mounts, so store backup and Manticore restore need the local layout. |
| `hoover4-pdf-search` | app | `docker-compose.yaml` | Deployment and Service on port 13500 | Same | |
| `hoover4-tika` | app | `tika.yaml` | Deployment, ConfigMap `tika-config` | Same | The tika configuration comes from deploy.py. |
| `hoover4-regex-entity-scanner` | app | `regex-entity-scanner.yaml` | Deployment | Same | |
| `hoover4-tesseract-cpu` | app | `tesseract-cpu.yaml` | Deployment when `tesseract_cpu_enabled` | Same | |
| `hoover4-ocr-pdf` | app | `ocr-pdf.yaml` | Deployment when `ocr_pdf_enabled` | Same | |
| `hoover4-clamav` | app | `clamav.yaml` | Deployment on a public node when `clamav_enabled` | Same | It loads its signatures from the internet. |
| `hoover4-mcp-collections` | app | `agents.yaml` | Deployment | Same | The shared secret comes from the Secret `hoover-runtime`. |
| `hoover4-mcp-todo` | app | `agents.yaml` | Deployment | Same | Same as above. |
| `hoover4-mcp-whois` | app | `internet-tools.yaml` | Deployment on a public node when `internet_tools_enabled` | Same | |
| `hoover4-mcp-metasearch` | app | `internet-tools.yaml` | Deployment on a public node when `internet_tools_enabled` | Same | |
| `hoover4-mcp-browser` | app | `internet-tools.yaml` | Deployment on a public node when `internet_tools_enabled` | Same | Memory `/dev/shm` of 2 GiB. It reaches ClickHouse and Garage only. |
| `hoover4-web-tor` | app | `web-tor.yaml` | Deployment on a public node when both internet switches are on | Same | Read-only root file system, memory `/tmp`. |
| `hoover4-internal-search-agent` | app | `research-agents.yaml` | Deployment when the model server is on | Same | |
| `hoover4-full-research-agent` | app | `research-agents.yaml` | Deployment when the model server is on | Same | |
| `clickhouse` | store | `docker-compose.yaml` | StatefulSet on the claim `clickhouse-data`, with `ops-backups` | ExternalName to the zone store | The users override and the rendered server override are a ConfigMap. |
| `manticore` | store | `docker-compose.yaml` | StatefulSet on the claim `manticore-data` | ExternalName to the zone store | An init container seeds `auth.json` as deploy.py does. |
| `manticore-vectors` | store | `docker-compose.yaml` | StatefulSet on the claim `manticore-vectors-data` | ExternalName to the zone store | Same as above. |
| `garage` | store | `docker-compose.yaml` | StatefulSet on the claims `garage-meta` and `garage-data` | ExternalName to the zone store | `garage.toml` is a ConfigMap. |
| `zookeeper` | store | `docker-compose.yaml` | StatefulSet without a claim | Not rendered | The ClickHouse override names it. The zone ClickHouse has its own configuration. |
| `garage-init` | store-init | `docker-compose.yaml` | Job for each source revision | setup.py creates the buckets and keys | The capacity follows the size of the claim `garage-data`. |
| `temporal` | temporal | `docker-compose.yaml` | Deployment on Cassandra and Elasticsearch | Deployment on Cassandra and Elasticsearch, or on the zone PostgreSQL | The dynamic configuration is a ConfigMap. A Job sets the retention of the default namespace. |
| `temporal-cassandra` | temporal-store | `docker-compose.yaml` | StatefulSet on the claim `temporal-cassandra` | Same with the `cassandra` backend | Same image as Compose. |
| `temporal-elasticsearch` | temporal-store | `docker-compose.yaml` | StatefulSet on the claim `temporal-elasticsearch` | Same with the `cassandra` backend | Same image as Compose. |
| `temporal-ui` | ui | `docker-compose.yaml` | Deployment and Service, no ingress | Not rendered | The development relay of a later stage makes the interfaces reachable. |
| `clickhouse-monitoring` | ui | `docker-compose.yaml` | Deployment on the claim `clickhouse-monitoring` | Not rendered | The zone layout has no operator user of its stores. |
| `ch-ui` | ui | `docker-compose.yaml` | Deployment and Service, no ingress | Not rendered | Same as above. |
| `hoover4-vllm` | gpu | `ai_services/compose/vllm.yaml` | Forwarder `gpu`, port 21960 | Same | The shared GPU pool serves it. The pool checks the key of the model server. |
| `hoover4-ai-server` | gpu | `ai_services/compose/ai-server.yaml` | Forwarder `gpu`, port 21961 | Same | NER, embeddings and reranking. |
| `hoover4-easyocr-gpu` | gpu | `ai_services/compose/easyocr.yaml` | Forwarder `gpu`, port 21962 | Same | |
| `redis` | excluded | `docker-compose.yaml` | Not rendered | Not rendered | No Hoover service connects to Redis. |
| `hoover4-processing-pdf-to-html` | excluded | `docker-compose.yaml` | Not rendered | Not rendered | No Hoover service calls it. The website names its address only. |
| `hoover4-development-auth-backdoor` | excluded | `development-auth-backdoor.yaml` | Not rendered | Not rendered | oauth2-proxy with Keycloak signs in every user. |

The removed services `hoover4-ner-spacy`, `serena` and the two earlier GPU ports 21963 and 21964 have no form in the cluster.

## Volume folders

Each folder of `[storage] volumes_path` in deploy.py has one form in the cluster.
The operator settings `volume.<claim>` hold the claim sizes.

| Folder | Compose use | Cluster form |
|---|---|---|
| `clickhouse_data` | ClickHouse data, read by the operations worker | Claim `clickhouse-data` in the local layout |
| `clickhouse_monitoring` | Data of `clickhouse-monitoring` | Claim `clickhouse-monitoring` in the local layout |
| `manticore_data_v14` | Manticore data, read and restored by the operations worker | Claim `manticore-data` in the local layout |
| `manticore_vectors_data_v14` | Manticore vectors data | Claim `manticore-vectors-data` in the local layout |
| `temporal_cassandra` | Temporal history | Claim `temporal-cassandra` with the `cassandra` backend |
| `temporal_elasticsearch` | Temporal visibility | Claim `temporal-elasticsearch` with the `cassandra` backend |
| `garage_meta` | Garage metadata and node key | Claim `garage-meta` in the local layout |
| `garage_data` | Garage blocks | Claim `garage-data` in the local layout |
| `ops_backups` | Backup root of the operations worker and ClickHouse | Claim `ops-backups` |
| `hoover4-website-target` | Build folder of the development website | Not rendered. The release image holds the server. |
| `worker_temp_files` | Plan files of the worker | Claim of each worker pod in the local layout, emptyDir in the zone layout |
| `easyocr_models_cache` | EasyOCR models of the worker, and of the GPU side | emptyDir, a cache |
| `hoover4-upload-tmp` | Upload space of the website | Claim `upload-tmp` |
| `ai_models_cache` | Models of the GPU AI server | GPU pool |
| `qwen_flash_hf` | Checkpoint of the model server | GPU pool |
| `qwen_flash_cache` | Compile caches of the model server | GPU pool |

## Other mounts

| Compose mount | Cluster form |
|---|---|
| `[dataset_mount.<name>]` of a migrated install | Read-only folders stay host folders of the home node. Each is a PersistentVolume with the claim `host-dataset-<name>`, which the pods mount read-only, because the pod policy refuses a host path in a pod. Writable folders are claims `dataset-<name>`. The container paths stay the same. |
| Dataset folders of a new install | NFS folders of the data node below `/data` |
| `chat_control_dir` at `/control` | The `chat_control_dir` of the site file, as the PersistentVolume of the claim `host-chat-control`, mounted read-only |
| Key files below `/run/secrets` | Items of the Secret `hoover-runtime` |
| Source folders of a built service | Left out. The image of the same commit holds them. |
| `/mirror/processing-tasks`, `/mirror/website-backend-src` | ConfigMap `mirror` with the three files that the services read |
