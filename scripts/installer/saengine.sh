#!/usr/bin/env sh
# SAEngine command line (python -m saengine.cli, docs/cli.md) for Git Bash and other POSIX
# shells on Windows. build-installer.ps1 installs it as <install folder>/bin/saengine next to
# saengine.cmd; the Code - OSS launcher that opens the app window is bin/saengine-app.
here=$(dirname "$(realpath "$0")")
python="$here/../resources/python/python.exe"
if [ ! -f "$python" ]; then
	echo "saengine: the bundled Python is missing: $python. Repair or reinstall SAEngine." >&2
	exit 127
fi
exec "$python" -I -m saengine.cli "$@"
