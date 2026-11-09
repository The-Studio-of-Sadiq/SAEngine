# Office server (opt-in)

An office machine runs analyses for the office's engineers: the app sends a project, the server
runs Run All's steps on it and the app brings the results back. It is **off by default**. Project
data goes only to the server address the engineer enters; there is no third-party cloud.

## On the office machine

```
saengine office-server --workspace D:\saengine-jobs --host 0.0.0.0 --port 8737 ^
    --certfile office.pem --keyfile office-key.pem
```

- The first start prints a token once; the server keeps only its SHA-256 in
  `<workspace>/office-server.json`. `--new-token` replaces it (the old one stops working).
- Without `--host` it listens on this machine only (127.0.0.1).
- On a network address use TLS (`--certfile`, `--keyfile`): without it the server warns that the
  token and the projects travel unencrypted on the office network.
- `--workers` jobs run at once (default 1); `--max-upload` MB per project (default 512);
  `--keep-days` days finished jobs are kept (default 7).
- Each job runs `python -m saengine.cli run-all` in a process of its own (cancel stops it), on
  the project extracted from its `.civil` archive (checked: paths, sizes, checksums).

## In the app

1. Settings: **SAEngine Office Server: Enabled** on, **Url** `https://<machine>:8737`.
2. **SAEngine: Set Office Server Token...** (kept in the system's secret storage).
3. **SAEngine: Check Office Server**, then **SAEngine: Run on Office Server**.

The app saves the open part files, sends the project without results, versions or exports,
shows the server's progress, and puts back every file the run wrote. A file you changed while the
job ran is kept as you left it (listed in the message). The last job is recorded in
`.saengine-office-job.json` (not versioned, not archived).

## Protocol

Every request needs `Authorization: Bearer <token>` (else `401`; five failures from one address
lock it out for a minute, `429`). `POST /rpc` (JSON-RPC 2.0): `office/info`, `office/createJob
{name?, steps?}`, `office/startJob {jobId}`, `office/status {jobId}`, `office/cancel {jobId}`,
`office/deleteJob {jobId}`, `office/listJobs`. `PUT /jobs/<id>/archive` uploads the `.civil`
archive; `GET /jobs/<id>/results` downloads a zip of the files the run wrote.

## Open questions for the owner

Whether to refuse (not just warn about) network addresses without TLS, per-engineer tokens, and
how long jobs stay on the server.
