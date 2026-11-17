# Expected durations of cluster operations

Use these values to set the deadline of a wait and to judge progress.
They come from the deploy records of the three-node test site.
Two nodes of that site have 12 threads and 31 GiB, and one node has 4 slower threads.
A larger site must not be slower.

| Operation | Expected | Investigate after |
|---|---|---|
| `up` step `hosts:prepare` | 14 to 18 s | 1 min |
| `up` step `hosts:k3s` without a k3s restart | 26 to 56 s | 2 min |
| k3s agent restart, containerd start included | 2 to 12 s | 2 min |
| `up` steps `registry`, `ingress`, `frontend`, `hoover-data` | 5 to 25 s each | 1 min |
| `up` step `images` without a build | 1 to 41 s | 2 min |
| `up` step `images` with a build of every Hoover image from the layer cache | about 106 s | 5 min |
| `up` step `monitoring` | 23 to 34 s | 2 min |
| `up` step `stores`, no store change | 5 to 36 s | 2 min |
| `up` step `stores`, new stores | 228 to 270 s | 7 min |
| `up` step `prepull` | about 77 s | 3 min |
| `up` step `placement` | 2 to 3 s, 78 s with a new render and an empty chart cache | 3 min |
| `up --target all` without a zone change | about 243 s | 7 min |
| `up --target all` without any change (second run) | 72 s, of which each zone step 15 to 16 s | 3 min |
| `up` zone step that runs the openDesk waves (changed input or `--full`) | 127 to 146 s, of which the waves about 95 s | 5 min |
| Zone apply without a chart change | 127 s, of which about 95 s for the openDesk waves | 5 min |
| Zone create | 1036 to 1178 s | 25 min |
| Zone delete | 146 to 187 s | 5 min |
| ClickHouse export of a small collection | under 1 min | 3 min |
| Platform backup job with a 197 MB etcd snapshot, reader pod included | 6 s | 3 min |
| Compose website, first `dx serve` build | about 400 s | 10 min |

A pod that reports `FailedScheduling` (for example `Insufficient cpu` or `Insufficient memory`) does not start by
itself. Act on the first such event. Do not wait for the deadline.

Update a row when a deploy record shows a new stable value. Keep the table to measured values.
