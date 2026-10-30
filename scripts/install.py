"""Copy only focused skills into a chosen workspace; never edit Codex config."""
import argparse
import json
from pathlib import Path
import shutil
import sys

KIT = Path(__file__).resolve().parents[1]


def install(workspace, dry_run=False):
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('workspace must be an existing directory')
    target = root / '.agents' / 'skills'
    if not target.resolve().is_relative_to(root):
        raise ValueError('skill destination escapes workspace through a symlink')
    sources = sorted((KIT / 'skills').glob('*/SKILL.md'))
    if not sources:
        raise ValueError('no packaged skills found')
    actions = []
    for source in sources:
        if any(p.is_symlink() for p in [source.parent, *source.parent.rglob('*')]):
            raise ValueError(f'packaged skill contains a symlink: {source.parent}')
        dest = target / source.parent.name
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink() or not dest.is_dir():
                raise ValueError(f'refusing existing non-directory: {dest}')
            if any(p.is_symlink() for p in dest.rglob('*')):
                raise ValueError(f'existing skill contains a symlink: {dest}')
            files = [p for p in source.parent.rglob('*') if p.is_file()]
            identical = all((dest / p.relative_to(source.parent)).is_file()
                            and (dest / p.relative_to(source.parent)).read_bytes() == p.read_bytes()
                            for p in files)
            if not identical:
                raise ValueError(f'existing skill differs; keep or rename it yourself: {dest}')
            actions.append((source.parent, dest, 'already present'))
        else:
            actions.append((source.parent, dest, 'copy'))
    for source, dest, action in actions:
        if not dry_run and action == 'copy':
            shutil.copytree(source, dest)
    return {'workspace': str(root), 'dry_run': dry_run,
            'skills': [{'name': a.name, 'action': c} for a, b, c in actions],
            'next': 'Use the provided Codex; if discovery fails, ask it to read the SKILL.md path directly.'}


def mcp_config(workspace):
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('workspace must be a directory')
    return {'mcpServers': {'cofa_local': {
        'command': sys.executable,
        'args': ['-u', str(KIT / 'scripts' / 'mcp_server.py'), '--workspace', str(root)]
    }}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', required=True)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--mcp-json', action='store_true', help='print optional stdio server JSON; make no changes')
    args = p.parse_args()
    try:
        result = mcp_config(args.workspace) if args.mcp_json else install(args.workspace, args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
