"""Mirror one module of SAEngine into its own repository (one way: SAEngine -> module repository).

A module (``scripts/modules/<id>.json``) is a part of SAEngine that will one day live in its own
repository, such as steel design. Until then SAEngine stays the only place it is edited: the
module repository is a read-only copy of the module's ``paths``, at the same paths, refreshed from
a commit of SAEngine. Every mirror run replaces the whole content of the module repository, so a
change made there is overwritten; ``MIRROR.json`` records the SAEngine commit it came from.

    python -I scripts/modules/mirror.py steel-design                 (dry run: prints what changes)
    python -I scripts/modules/mirror.py steel-design --push          (commits and pushes)
    python -I scripts/modules/mirror.py --list

The paths must be committed and clean in SAEngine, so a mirror is always a real commit of it.
The module repository is cloned with ``git`` over HTTPS (credentials from ``gh auth setup-git``
or the Git credential manager). Standard library only, Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = Path(__file__).resolve().parent
SOURCE_REPOSITORY = 'The-Studio-of-Sadiq/SAEngine'
GENERATED = ('README.md', 'LICENSE', 'MIRROR.json')


def git(*args: str, cwd: Path) -> str:
    """Runs git and returns its standard output; a failure stops the mirror."""
    result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        sys.exit(f'git {" ".join(args)} failed in {cwd}:\n{result.stderr.strip()}')
    return result.stdout.strip()


def load_module(module_id: str) -> dict:
    manifest = MODULES / f'{module_id}.json'
    if not manifest.is_file():
        sys.exit(f'No module {module_id!r}: {manifest} does not exist (see --list).')
    module = json.loads(manifest.read_text(encoding='utf-8'))
    missing = [path for path in module['paths'] if not (ROOT / path).exists()]
    if missing:
        sys.exit('These paths of the module do not exist in SAEngine:\n  ' + '\n  '.join(missing))
    return module


def check_clean(paths: list[str]) -> None:
    """Refuses uncommitted or untracked changes under the module's paths."""
    status = git('status', '--porcelain', '--', *paths, cwd=ROOT)
    if status:
        sys.exit('Commit these changes first; a mirror is always a commit of SAEngine:\n' + status)


def readme(module: dict, commit: str) -> str:
    notes = ''.join(f'- {note}\n' for note in module.get('notes', []))
    paths = ''.join(f'- `{path}`\n' for path in module['paths'])
    return (
        f'# {module["name"]}\n\n'
        f'{module["description"]}\n\n'
        f'**This repository is a read-only mirror.** The code is developed in '
        f'[SAEngine](https://github.com/{SOURCE_REPOSITORY}) and copied here from commit '
        f'[`{commit[:10]}`](https://github.com/{SOURCE_REPOSITORY}/commit/{commit}) '
        f'by `scripts/modules/mirror.py`. Every update replaces the whole content, so open issues '
        f'and pull requests in SAEngine, not here. Once the module interface is stable the module '
        f'will move here and SAEngine will install it as a package.\n\n'
        f'The files keep their paths in SAEngine:\n\n{paths}\n'
        + (f'Not in this module:\n\n{notes}\n' if notes else '')
        + f'Licence: {module["licence"]} (see LICENSE), the same as SAEngine.\n'
    )


def fill(target: Path, module: dict, commit: str) -> None:
    """Replaces everything in the clone (except .git) with the module's files and the generated ones."""
    for entry in target.iterdir():
        if entry.name == '.git':
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for path in module['paths']:
        source, destination = ROOT / path, target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            # Only tracked files: no __pycache__ or build output.
            for tracked in git('ls-files', '--', path, cwd=ROOT).splitlines():
                file = target / tracked
                file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / tracked, file)
        else:
            shutil.copy2(source, destination)
    (target / 'README.md').write_text(readme(module, commit), encoding='utf-8', newline='\n')
    shutil.copy2(ROOT / 'LICENSE', target / 'LICENSE')
    mirror = {
        'source': SOURCE_REPOSITORY,
        'commit': commit,
        'mirrored': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'paths': module['paths'],
    }
    (target / 'MIRROR.json').write_text(json.dumps(mirror, indent=2) + '\n', encoding='utf-8', newline='\n')


def mirror(module_id: str, push: bool) -> None:
    module = load_module(module_id)
    check_clean(module['paths'])
    commit = git('rev-parse', 'HEAD', cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix=f'saengine-mirror-{module_id}-') as folder:
        target = Path(folder) / 'repo'
        git('clone', '--quiet', f'https://github.com/{module["repository"]}.git', str(target), cwd=Path(folder))
        fill(target, module, commit)
        git('add', '--all', cwd=target)
        # MIRROR.json always changes (its date); only the module's own files make a new mirror.
        changed = [line for line in git('status', '--porcelain', cwd=target).splitlines() if line[3:] != 'MIRROR.json']
        if not changed:
            print(f'{module["repository"]} already has the module as of {commit[:10]}; nothing to do.')
            return
        print(f'{len(changed)} changes for {module["repository"]} from SAEngine {commit[:10]}:')
        print('\n'.join(f'  {line}' for line in changed))
        if not push:
            print('Dry run: nothing committed. Run again with --push to publish.')
            return
        git('commit', '--quiet', '-m', f'Mirror SAEngine {commit[:10]}\n\nFrom {SOURCE_REPOSITORY}@{commit}.', cwd=target)
        git('push', '--quiet', 'origin', 'HEAD:main', cwd=target)
        print(f'Pushed to https://github.com/{module["repository"]}.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('module', nargs='?', help='module id, the name of scripts/modules/<id>.json')
    parser.add_argument('--push', action='store_true', help='commit and push (default: dry run)')
    parser.add_argument('--list', action='store_true', help='list the modules')
    args = parser.parse_args()
    if args.list or not args.module:
        for manifest in sorted(MODULES.glob('*.json')):
            module = json.loads(manifest.read_text(encoding='utf-8'))
            print(f'{module["id"]:<20} {module["repository"]}')
        return
    mirror(args.module, args.push)


if __name__ == '__main__':
    main()
