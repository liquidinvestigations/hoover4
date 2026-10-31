# The ClamAV service scans file bytes.

`hoover4-clamav` runs clamd and a small HTTP front ([scan_http.py](scan_http.py)).
The worker stage `clamav_scan_batch` sends each file to it before parsing.
[deploy.py](../../deploy.py) starts it when `clamav_enabled` is true.

## The image holds signatures of its build time.

The [Dockerfile](Dockerfile) runs freshclam during the build, so the service can scan
without network access. [start.sh](start.sh) starts the freshclam daemon only when
`CLAMAV_UPDATE_SIGNATURES` is `true`. A signature update applies to new scans and to the
scans of the Virus scan update step. No periodic rescan exists.

The clamd configuration sets `StreamMaxLength` and `MaxFileSize` to 501M, `MaxScanSize`
to 2000M and `AlertExceedsMax` to yes. A recursive limit therefore gives an alert with
the name `Heuristics.Limits.Exceeded...`, and the front reports it as `incomplete`.

## `POST /scan` streams one file.

The request body is the file. `Content-Length` is required. The front sends the body to
clamd with the INSTREAM command in 64 KiB chunks, so it never holds a whole file.

| Answer | When |
|---|---|
| `200` with `status` `clean` or `infected` | clamd gave a verdict. `signature` names the match. |
| `200` with `status` `incomplete` | clamd stopped at a recursive limit. |
| `200` with `status` `error` | clamd gave another reply. |
| `411` | The request has no `Content-Length`. |
| `413` | The body is larger than 500 MiB. A body of exactly 500 MiB is scanned. |
| `502` | clamd did not answer, or the body ended early. |
| `503` | The scan slots and the waiting places are all in use. |

Every `200` answer has `engine_version`, `database_version` and `config_fingerprint`.
The fingerprint is a hash of the clamd keys that change a verdict.

At most `CLAMAV_CONCURRENCY` scans run at once. At most 4 times that number of requests
wait for a slot. clamd uses the same number as `MaxThreads`.

## `GET /health` reports readiness.

The answer is `200` only when clamd answers VERSION with an engine version and a
signature database version. Otherwise it is `503`. The compose health check uses it.
