#!/usr/bin/env bash
# Step 2 on the desktop, inside Ubuntu (WSL2): installs N GitHub Actions runners for SAEngine's CI
# as systemd services, labelled "saengine-desktop".
# Usage: bash setup-runner.sh <registration-token> [runners=2]
# The token comes from GitHub: repo Settings > Actions > Runners > New self-hosted runner (valid
# for one hour). Details: docs/ci-desktop-runner.md
set -euo pipefail
TOKEN=${1:?usage: setup-runner.sh <registration-token> [runners]}
COUNT=${2:-2}
REPO=https://github.com/The-Studio-of-Sadiq/SAEngine
LABELS=saengine-desktop

# systemd (runner services) and passwordless sudo (CI installs apt packages).
if ! grep -q '^systemd=true' /etc/wsl.conf 2>/dev/null; then
	printf '\n[boot]\nsystemd=true\n' | sudo tee -a /etc/wsl.conf >/dev/null
	echo "systemd enabled: in Windows PowerShell run 'wsl --shutdown', reopen Ubuntu and run this again."
	exit 0
fi
echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/90-saengine-runner >/dev/null
sudo apt-get update -q
sudo apt-get install -y -q curl git jq tar zstd build-essential

cd "$HOME"
# The newest runner release (GitHub refuses runners that are too old).
VERSION=$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name)
VERSION=${VERSION#v}
archive=actions-runner-linux-x64-$VERSION.tar.gz
[ -f "$archive" ] || curl -fsSLo "$archive" "https://github.com/actions/runner/releases/download/v$VERSION/$archive"
for n in $(seq 1 "$COUNT"); do
	dir="$HOME/saengine-runner-$n"
	if [ -f "$dir/.runner" ]; then
		echo "runner $n is already configured ($dir)"
		continue
	fi
	mkdir -p "$dir"
	tar -xzf "$archive" -C "$dir"
	(cd "$dir" && sudo ./bin/installdependencies.sh >/dev/null &&
		./config.sh --unattended --url "$REPO" --token "$TOKEN" \
			--name "$(hostname)-saengine-$n" --labels "$LABELS" --work _work --replace &&
		sudo ./svc.sh install "$USER" && sudo ./svc.sh start)
done
echo "Done: $COUNT runner(s) online with the label '$LABELS'."
