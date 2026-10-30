"""Optional, local, read-only MCP stdio adapter. No sockets or model/API calls."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

KIT = Path(__file__).resolve().parents[1]
VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
MAX_MESSAGE = 64 * 1024
MAX_OUTPUT = 128 * 1024
TOOLS = [
    {'name': 'workspace_check',
     'description': 'Check required artifact/evidence existence and declared completion. This does NOT prove functional correctness.',
     'inputSchema': {'type': 'object', 'properties': {'manifest': {'type': 'string', 'default': 'requirements.json'}}, 'additionalProperties': False},
     'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'profile_csv',
     'description': 'Summarize a local CSV within the workspace: missing values, duplicates, and numeric ranges, with a bounded row sample.',
     'inputSchema': {'type': 'object', 'properties': {
         'path': {'type': 'string'}, 'encoding': {'type': 'string', 'enum': ['utf-8-sig', 'cp949'], 'default': 'utf-8-sig'},
         'max_rows': {'type': 'integer', 'minimum': 1, 'maximum': 10000, 'default': 10000}}, 'required': ['path'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}}
]


def reject_non_json_number(value):
    raise ValueError(f'Invalid JSON number: {value}')


def local_path(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError('path must be a nonempty workspace-relative path')
    path = (root / value).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('path must be a file inside the workspace')
    return path


def call_tool(root, name, args):
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object')
    if name == 'workspace_check':
        if set(args) - {'manifest'}:
            raise ValueError('unknown argument')
        manifest = local_path(root, args.get('manifest', 'requirements.json'))
        command = ['check', '--workspace', str(root), '--manifest', str(manifest.relative_to(root))]
    elif name == 'profile_csv':
        if set(args) - {'path', 'encoding', 'max_rows'}:
            raise ValueError('unknown argument')
        path = local_path(root, args.get('path'))
        encoding = args.get('encoding', 'utf-8-sig')
        rows = args.get('max_rows', 10000)
        if encoding not in ('utf-8-sig', 'cp949') or type(rows) is not int or not 1 <= rows <= 10000:
            raise ValueError('invalid encoding or max_rows')
        command = ['profile', str(path), '--format', 'csv', '--encoding', encoding, '--max-rows', str(rows)]
    else:
        raise ValueError('unknown tool')
    # Disk-backed capture avoids unbounded process-output memory. The CLI has its own input bounds.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run([sys.executable, '-X', 'utf8', str(KIT / 'scripts' / 'cofa.py'), *command],
                                cwd=root, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=30)
        stdout.seek(0)
        stderr.seek(0)
        data = stdout.read(MAX_OUTPUT + 1)
        errors = stderr.read(4096)
    if len(data) > MAX_OUTPUT:
        raise ValueError('result exceeds MCP output limit; use the CLI locally')
    text = data.decode('utf-8', errors='replace') or errors.decode('utf-8', errors='replace')
    return {'content': [{'type': 'text', 'text': text}], 'isError': result.returncode != 0}


class Server:
    def __init__(self, root):
        self.root = root
        self.initialized = False
        self.ready = False

    def handle(self, request):
        if not isinstance(request, dict):
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}
        req_id = request.get('id')
        # Invalid IDs must not be echoed as objects/arrays (or Python's bool-as-int).
        if 'id' in request and (type(req_id) not in (str, int, float)
                                or isinstance(req_id, float) and not math.isfinite(req_id)):
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request ID'}}
        def error(code, message):
            return {'jsonrpc': '2.0', 'id': req_id, 'error': {'code': code, 'message': message}}
        method = request.get('method')
        if request.get('jsonrpc') != '2.0' or not isinstance(method, str):
            return error(-32600, 'Invalid Request')
        if 'id' not in request:
            if (method == 'notifications/initialized' and self.initialized
                    and isinstance(request.get('params', {}), dict)):
                self.ready = True
            return None
        params = request.get('params', {})
        if not isinstance(params, dict):
            return error(-32602, 'params must be an object')
        if method == 'initialize':
            version = params.get('protocolVersion')
            if not isinstance(version, str) or not isinstance(params.get('capabilities'), dict) or not isinstance(params.get('clientInfo'), dict):
                return error(-32602, 'initialize requires protocolVersion, capabilities, clientInfo')
            self.initialized = True
            self.ready = False
            result = {'protocolVersion': version if version in VERSIONS else VERSIONS[0],
                      'capabilities': {'tools': {'listChanged': False}},
                      'serverInfo': {'name': 'cofa-local', 'version': '1.0.0'}}
        elif method == 'ping':
            result = {}
        elif not self.ready:
            return error(-32000, 'Initialize and send notifications/initialized first')
        elif method == 'tools/list':
            result = {'tools': TOOLS}
        elif method == 'tools/call':
            name = params.get('name')
            if not isinstance(name, str) or name not in {t['name'] for t in TOOLS}:
                return error(-32602, 'Unknown tool')
            try:
                result = call_tool(self.root, params['name'], params.get('arguments', {}))
            except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
        else:
            return error(-32601, 'Method not found')
        return {'jsonrpc': '2.0', 'id': req_id, 'result': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()
    root = Path(args.workspace).resolve(strict=True)
    if not root.is_dir():
        parser.error('workspace must be a directory')
    server = Server(root)
    while True:
        raw = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
        if not raw:
            break
        if len(raw) > MAX_MESSAGE:
            print('MCP message exceeds 64 KiB; closing', file=sys.stderr)
            return 2
        try:
            response = server.handle(json.loads(raw.decode('utf-8'), parse_constant=reject_non_json_number))
        except (ValueError, UnicodeError, RecursionError):
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
