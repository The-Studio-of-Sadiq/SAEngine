# CI on a desktop PC (self-hosted runner)

SAEngine's CI (`.github/workflows/ci.yml`) can run on an office desktop instead of GitHub's
runners. Self-hosted runs cost no Actions minutes (the private repository has a monthly quota),
and they take the heavy checks (full pytest, typecheck, the Electron unit tests) off the laptops
people work on. The runners run Ubuntu 24.04 inside WSL2, so the Linux CI steps work unchanged.

Tested set-up: Windows 10, Intel i3-10300 (4 cores), 16 GB RAM, two runners (one per CI job).

## 1. WSL2 and Ubuntu (Windows, once)

Copy `scripts/ci/desktop-runner/install-wsl.ps1` to the desktop and, in PowerShell **as
Administrator**:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-wsl.ps1
```

The first run installs WSL2 and Ubuntu 24.04: restart Windows if asked, open **Ubuntu 24.04**
from the Start menu once and create a Linux user, then run the script again. The second run adds
the logon task *SAEngine WSL keep-alive*, which keeps WSL (and so the runners) running while you
are logged in.

## 2. The runners (Ubuntu, once)

1. On GitHub: the repository's **Settings → Actions → Runners → New self-hosted runner**. Copy
   the token from the `./config.sh --url … --token <TOKEN>` line (it is valid for one hour).
2. Copy `scripts/ci/desktop-runner/setup-runner.sh` into Ubuntu (for example to `~`) and run:

   ```bash
   bash setup-runner.sh <TOKEN> 2
   ```

   The first run enables systemd and stops: run `wsl --shutdown` in Windows PowerShell, open
   Ubuntu again and run the same command again. It then installs two runners as services,
   labelled `saengine-desktop`.
3. The runners show as **Idle** under Settings → Actions → Runners.

## 3. Switch CI to the desktop

Settings → Secrets and variables → Actions → **Variables** → New repository variable:

| Name | Value |
|---|---|
| `CI_RUNS_ON` | `["self-hosted", "saengine-desktop"]` |

Both CI jobs then run on the desktop. Delete the variable to go back to GitHub's runners (for
example when the desktop is off for a long time: queued jobs wait for a runner otherwise).

## Running CI on a branch by hand

```bash
gh workflow run ci.yml --ref side/my-branch            # quick: no slow tests, no verification pack
gh workflow run ci.yml --ref side/my-branch -f full=true
gh run watch
```

## Notes

- A power cut stops the running jobs; they show as failed or cancelled. Re-run them from the
  Actions page once the desktop is back (the runners start again at logon).
- The runners only take jobs from this private repository. Never point a self-hosted runner at a
  public repository: pull requests from forks could run code on the desktop.
- The release build (`release.yml`) still runs on Windows (`windows-2022`, or the runner named by
  the variable `SAENGINE_RELEASE_RUNNER`); a native Windows runner on the desktop can take it
  later.
