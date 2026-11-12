#!/usr/bin/env bash
# (Re)creates workbench/node_modules/@saengine/{fem-viewer,cad-editor} as the symlinks to
# packages/<name> that `npm ci` makes for the workbench's file:../packages/* dependencies.
#
#   scripts/ci/link-saengine-packages.sh unlink   # before archiving node_modules for the cache
#   scripts/ci/link-saengine-packages.sh link     # after extracting it (or archiving)
#
# Code - OSS's node_modules cache (workbench/.github/workflows/node_modules_cache/cache.sh)
# follows symlinks, so without this it would store a stale copy of the packages' sources in
# place of the links, and the workbench would type-check against that copy instead of the
# freshly built packages/*/dist.
set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
scope="$root/workbench/node_modules/@saengine"

case "${1:-}" in
	unlink)
		rm -rf "$scope"
		;;
	link)
		rm -rf "$scope"
		mkdir -p "$scope"
		for package in fem-viewer cad-editor; do
			ln -s "../../../packages/$package" "$scope/$package"
		done
		;;
	*)
		echo "usage: $0 link|unlink" >&2
		exit 2
		;;
esac
