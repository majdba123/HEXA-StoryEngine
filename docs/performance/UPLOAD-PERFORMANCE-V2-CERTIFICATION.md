# Upload Performance V2: measured transport checkpoint

Status: **PARTIALLY COMPLETE; not production certified**. Base: `origin/montage` at `df0482c5b572a77ae706f97b642ec7f3a4e5d02b`. Feature branch: `feature/upload-performance-v2`. The base source tree and new worktree were clean before edits. The existing local `montage` worktree and stash were left untouched. No production rollout was performed.

## Root cause and protocol decision

V1 sends 256 KiB chunks, waits for each durable acknowledgement, then fetches full upload status after every chunk. On a 44 MiB ZIP plus small audio this means 355 HTTP requests; on 100 MiB it means 803. Every chunk is fsynced and its offset committed in SQLite. The browser also hashes every file twice: once for its bounded fingerprint and once for each outgoing slice. These effects were measured together. The benchmark does not isolate checksum, fsync, SQLite, proxy buffering, or CPU time, so none is claimed as the sole bottleneck.

V2 is explicitly negotiated in the manifest with `protocol: 2` and a 4 MiB chunk size. V1 manifests retain their original fingerprint and chunk-size semantics. The browser uses the authoritative committed offset in each chunk response and requests status only for recovery. V2 remains sequential. This avoids out-of-order storage, bitmap migration, overlapping writes, and unsafe completion while requests are outstanding. Its tradeoff is less throughput on paths where several parallel connections would help. The browser's per-chunk memory bound rises to 4 MiB; the server body guard rises to 4 MiB. The default V1 `HEXA_WEB_CHUNK_BYTES` remains 256 KiB. `HEXA_WEB_V2_ENABLED=0` is the safe default. Set it to `1` only after proxy and browser validation; disabling it stops new V2 sessions but existing V2 sessions remain resumable.

An acknowledgement follows file flush/fsync and SQLite commit. SQLite remains the offset authority. If a process stops after file write and before DB commit, the next write truncates unacknowledged bytes to the recorded offset. Duplicate committed chunks are checked against disk content. Finalization still rereads and verifies SHA-256, then validates ZIP, audio and Final Package before job admission. There is no change to render concurrency or the engine. Sessions already stored in SQLite keep their recorded chunk size, including when the V1 server default later changes. Pending browser initiation remains in localStorage and uses its old protocol and fingerprint size after refresh.

## Controlled local HTTP measurements

`tools/benchmark_upload_transport.py` starts an isolated Uvicorn server, creates disposable data and an authenticated session, sends real localhost HTTP requests, checks the server's committed offsets, then stops the server. The current harness checks stored SHA-256 against the deterministic source after timing; all table rows below are from those checksum-verified runs. The baseline source is the clean base checkout at the same SHA. V1 emulates the old browser's status request after each chunk; V2 consumes the chunk acknowledgement. The 50 ms profile sleeps once per request in the client. **It approximates RTT; it is not network shaping or a production internet measurement.** Each number below is one run on the same Windows host. The candidate uses the V2 capability enabled; the feature flag only controls new-session negotiation, so it does not alter the measured chunk path. Files are deterministic synthetic bytes, not a valid Final Package. The audio payload is small. JSON measurements: `upload-baseline.json`, `upload-baseline-100.json`, `upload-v2.json`, `upload-v2-100.json`, `upload-baseline-extra.json`, `upload-v2-extra.json` in this directory.

| Data | Added latency | V1 preparation + durable upload | V2 preparation + durable upload | Requests V1 to V2 | Time reduction |
|---|---:|---:|---:|---:|---:|
| 1 MiB | 0 ms | 0.50 s | 0.24 s | 11 to 3 | 53% |
| 44 MiB | 0 ms | 17.58 s | 3.82 s | 355 to 13 | 78% |
| 44 MiB | 50 ms | 70.58 s | 3.71 s | 355 to 13 | 95% |
| 44 MiB | 150 ms | 82.12 s | 5.71 s | 355 to 13 | 93% |
| 100 MiB | 0 ms | 41.81 s | 3.95 s | 803 to 27 | 91% |
| 100 MiB | 50 ms | 101.22 s | 11.77 s | 803 to 27 | 88% |
| 250 MiB | 0 ms | 95.26 s | 15.26 s | 2003 to 65 | 84% |

All rows were rerun with post-timing SHA-256 equality checks on stored files. Large run-to-run variance exists on this Windows host: an earlier 44 MiB 50 ms V1 run was 33.91 s versus 70.58 s here; earlier 100 MiB 0 ms V2 was 9.17 s versus 3.95 s here. The local relative speedup is robust, but the precise percentage is not a production prediction. The timing covers fingerprint preparation, upload creation and committed transfer. It excludes login, file selection, final verification, validation and render admission. CPU, peak memory, server write rate, SQLite transaction and fsync timings were not captured. A Windows temporary-directory cleanup error occurred after the 250 MiB V1 result was recorded; the result was saved and the harness now waits for process exit and tolerates late handle release.

## Tests and limits

Focused V2 test: 4 MiB acknowledgement, duplicate delivery and byte equality. Legacy test: idempotent V1 session survives a changed server default. Existing upload tests exercise corruption, disk-full, restart, validation and render-admission restrictions. A V2 test uploads a native Unified Final Package 2.0 ZIP and real WAV, runs actual ZIP/audio/package validation, and verifies the admitted job association; only `Jobs.start` is replaced with a spy to avoid rendering. A separate headless Firefox run (`tools/browser_upload_smoke.py`) refreshed after 4,194,304 server-committed bytes of a 104,857,600-byte synthetic file, reselected the same files, and reached 104,857,600 committed bytes on the same upload ID with stored SHA-256 equality. The browser run caught and led to fixes for missing V2 manifest negotiation and a session-restoration click race; it is transport proof, not valid-media certification. Final web suite: 63 tests, 0 failures, 0 errors, 0 skips. Full repository run: 10,229 tests, 0 failures, 0 errors, 38 skips, 1,713.7 s. Three additional upload tests and the V2 feature flag were added after that full run started; those final upload tests passed in the final web suite, but a second full run on the exact final tree was not executed. Ruff, Python compileall, JavaScript syntax and `git diff --check` passed locally. Automated retry and packet-loss injection, encoded upload-to-render smoke, 300 ms network profile, disk quota contention, CPU/memory/fsync breakdown, and proxy behavior are **not yet certified**. The current V2 changes should not be represented as production-ready until those gaps are closed.

## Production prerequisites and later rollout plan

The repository documents Uvicorn with one worker behind a TLS reverse proxy, but does not contain an authoritative Nginx config. Before rollout, inspect the live configuration without printing secrets: body limit must permit 4 MiB plus headers; verify proxy request buffering, timeouts, HTTPS forwarding, cookie and CSRF handling, connection reuse and free disk. Confirm the exact certified SHA, review compatibility with latest `montage`, inspect active uploads and renders, back up SQLite, and ensure sufficient storage. Existing V1 sessions must keep working across the release. Set `HEXA_WEB_V2_ENABLED=1` for a controlled canary and return it to `0` for fallback; canary with one authenticated real ZIP/audio upload, refresh recovery, validation, job creation and admin history. Monitor request counts, retries, throughput, CPU, disk, fsync and SQLite busy errors. Roll back the new client negotiation to V1 if necessary while retaining existing V2 sessions and their files. Do not delete incomplete sessions. Do not push `bayer` or restart the VPS until separately authorized.

## Future work

Measure real browser hashing and UI responsiveness; instrument fsync/SQLite and finalization; test real proxy behavior; compare 1, 2 and 4 MiB chunks and concurrency 1–4 under controlled bandwidth and RTT. A parallel protocol needs independently durable chunk records and crash-safe assembly before it can be accepted. V2 currently chooses the safe sequential 4 MiB path based on the local transport measurements above.

## 2026-10-17 integration rerun

The browser progress copy was repaired after the initial checkpoint: several newly added Arabic strings had become literal question marks. The feature code passed Ruff, compileall, JavaScript syntax, and whitespace checks. A fresh headless Firefox run uploaded 100 MiB, refreshed after 4 MiB were durably committed, reselected the files, and completed under the same upload ID with matching SHA-256. This verifies refresh recovery in the actual browser, not just the API.

The same isolated localhost HTTP harness was rerun on the unchanged V1 base and the final V2 candidate on this Windows host. Each row is one checksum-verified run; `50 ms` is an application sleep per HTTP request, not network shaping. These numbers cover preparation through durable upload, not package validation or render admission.

| Size | Approximate RTT | V1 time | V2 time | Requests V1 → V2 | Time reduction |
|---|---:|---:|---:|---:|---:|
| 44 MiB | 0 ms | 20.151 s | 1.998 s | 355 → 13 | 90.1% |
| 44 MiB | 50 ms | 72.864 s | 4.655 s | 355 → 13 | 93.6% |
| 100 MiB | 0 ms | 43.937 s | 4.098 s | 803 → 27 | 90.7% |
| 100 MiB | 50 ms | 87.098 s | 10.402 s | 803 → 27 | 88.1% |

Machine-readable evidence is `upload-baseline-final.json` and `upload-v2-final.json` beside this report. The improvement is attributable to larger negotiated chunks and elimination of the per-chunk status GET; this harness does not apportion the gain between those two changes or predict VPS throughput. V2 remains behind `HEXA_WEB_V2_ENABLED=0` by default until a controlled production canary is separately authorized.
