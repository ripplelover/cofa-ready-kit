import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstallTest(unittest.TestCase):
    def test_dry_run_idempotence_and_conflict(self):
        installer = load_script('install')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = installer.install(root, dry_run=True)
            self.assertGreater(len(plan['skills']), 0)
            self.assertFalse((root / '.agents').exists())
            installer.install(root)
            again = installer.install(root)
            self.assertTrue(all(x['action'] == 'already present' for x in again['skills']))
            skill = next((root / '.agents').rglob('SKILL.md'))
            skill.write_text('user customization', encoding='utf-8')
            with self.assertRaises(ValueError):
                installer.install(root)
            self.assertEqual(skill.read_text(encoding='utf-8'), 'user customization')

    def test_mcp_config_is_local_and_has_explicit_root(self):
        installer = load_script('install')
        with tempfile.TemporaryDirectory() as temp:
            servers = installer.mcp_config(temp)['mcpServers']
            self.assertEqual(set(servers), {'cofa_local'})
            config = servers['cofa_local']
            self.assertNotIn('url', config)
            self.assertEqual(config['args'][-1], str(Path(temp).resolve()))
            self.assertEqual(config['command'], sys.executable)

    def test_mcp_json_cli_optional_docs_preserves_workspace_and_unicode_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '과제 폴더'
            root.mkdir()
            (root / '.codex').mkdir()
            (root / '.codex' / 'config.toml').write_text('# existing config\n', encoding='utf-8')
            (root / 'mcp.json').write_text('{"mcpServers":{"existing":{"command":"keep"}}}\n',
                                         encoding='utf-8')
            (root / 'AGENTS.md').write_text('Preserve the task instructions.\n', encoding='utf-8')
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            for with_docs in (False, True):
                with self.subTest(with_docs=with_docs):
                    command = [sys.executable, str(ROOT / 'scripts' / 'install.py'),
                               '--workspace', str(root), '--mcp-json']
                    if with_docs:
                        command.append('--with-openai-docs')
                    result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                            encoding='utf-8', timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    config = json.loads(result.stdout)
                    self.assertEqual(set(config), {'mcpServers'})
                    servers = config['mcpServers']
                    expected = {'cofa_local', 'openai_docs'} if with_docs else {'cofa_local'}
                    self.assertEqual(set(servers), expected)
                    self.assertEqual(servers['cofa_local'], {
                        'command': sys.executable,
                        'args': ['-u', str(ROOT / 'scripts' / 'mcp_server.py'), '--workspace', str(root.resolve())]})
                    self.assertTrue(Path(servers['cofa_local']['command']).is_file())
                    if with_docs:
                        self.assertEqual(servers['openai_docs'], {'url': 'https://developers.openai.com/mcp'})
                    self.assertFalse((root / '.agents').exists())
                    after = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    self.assertEqual(before, after)

    def test_docs_flag_without_mcp_json_is_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sentinel = root / 'AGENTS.md'
            sentinel.write_text('Existing task instructions\n', encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'install.py'),
                                     '--workspace', str(root), '--with-openai-docs'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--with-openai-docs requires --mcp-json', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(list(root.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'Existing task instructions\n')

    def test_install_preserves_extra_user_files_and_preflights_all_conflicts(self):
        installer = load_script('install')
        names = sorted(p.parent.name for p in (ROOT / 'skills').glob('*/SKILL.md'))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            conflict = root / '.agents' / 'skills' / names[-1]
            conflict.mkdir(parents=True)
            (conflict / 'SKILL.md').write_text('existing customized skill', encoding='utf-8')
            with self.assertRaises(ValueError):
                installer.install(root)
            self.assertEqual(sorted(p.name for p in conflict.parent.iterdir()), [names[-1]])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer.install(root)
            extra = root / '.agents' / 'skills' / names[0] / 'personal-notes.txt'
            extra.write_text('preserve my notes', encoding='utf-8')
            installer.install(root)
            self.assertEqual(extra.read_text(encoding='utf-8'), 'preserve my notes')


class MCPTest(unittest.TestCase):
    @staticmethod
    def ready_server(module, root):
        server = module.Server(root)
        server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}})
        server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return server

    def test_stdio_handshake_and_real_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'data.csv').write_text('name,value\na,3\nb,\na,3\n', encoding='utf-8')
            messages = [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                    'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'profile_csv', 'arguments': {'path': 'data.csv'}}},
                {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'profile_csv', 'arguments': {'path': '../outside.csv'}}},
            ]
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/mcp_server.py'), '--workspace', temp],
                                    input='\n'.join(json.dumps(m) for m in messages) + '\n',
                                    capture_output=True, text=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            replies = [json.loads(x) for x in result.stdout.splitlines()]
            self.assertEqual([x['id'] for x in replies], [1, 2, 3, 4])
            self.assertEqual({tool['name'] for tool in replies[1]['result']['tools']},
                             {'workspace_check', 'profile_csv', 'semiconductor_yield', 'spc_monitor', 'csv_join_audit', 'evidence_freshness'})
            self.assertFalse(replies[2]['result']['isError'], replies[2])
            self.assertIsInstance(json.loads(replies[2]['result']['content'][0]['text']), dict)
            self.assertTrue(replies[3]['result']['isError'])

    def test_lifecycle_invalid_params_and_escape(self):
        module = load_script('mcp_server')
        with tempfile.TemporaryDirectory() as temp:
            server = module.Server(Path(temp))
            self.assertIn('error', server.handle({'jsonrpc': '2.0', 'id': 0, 'method': 'tools/list'}))
            self.assertIn('error', server.handle([]))
            self.assertIn('error', server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}))
            with self.assertRaises(ValueError):
                module.local_path(Path(temp), str(ROOT / 'README.md'))

    def test_malformed_tool_names_do_not_crash_server(self):
        module = load_script('mcp_server')
        with tempfile.TemporaryDirectory() as temp:
            server = self.ready_server(module, Path(temp))
            for name in ([], {}, None, 1, True):
                with self.subTest(name=name):
                    reply = server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': name}})
                    self.assertEqual(reply['error']['code'], -32602)
            self.assertIn('result', server.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'}))

    def test_invalid_ids_are_rejected_and_not_echoed(self):
        module = load_script('mcp_server')
        with tempfile.TemporaryDirectory() as temp:
            server = module.Server(Path(temp))
            for req_id in ([], {}, None, True, float('nan'), float('inf')):
                with self.subTest(req_id=req_id):
                    reply = server.handle({'jsonrpc': '2.0', 'id': req_id, 'method': 'ping'})
                    self.assertEqual(reply['error']['code'], -32600)
                    self.assertIsNone(reply['id'])
            self.assertEqual(server.handle({'jsonrpc': '2.0', 'id': 'valid-id', 'method': 'ping'})['result'], {})

    def test_stdio_parse_errors_do_not_end_session(self):
        with tempfile.TemporaryDirectory() as temp:
            malformed = [
                '{',
                '{"jsonrpc":"2.0","id":NaN,"method":"ping"}',
                '[' * 2000 + '0' + ']' * 2000,
            ]
            valid = json.dumps({'jsonrpc': '2.0', 'id': 'alive', 'method': 'ping'})
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/mcp_server.py'), '--workspace', temp],
                                    input='\n'.join(malformed + [valid]) + '\n', capture_output=True,
                                    text=True, encoding='utf-8', timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            replies = [json.loads(x) for x in result.stdout.splitlines()]
            self.assertEqual([x['error']['code'] for x in replies[:-1]], [-32700] * 3)
            self.assertEqual(replies[-1], {'jsonrpc': '2.0', 'id': 'alive', 'result': {}})

    def test_workspace_check_runs_real_manifest_validation(self):
        module = load_script('mcp_server')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'requirements.json').write_text(json.dumps({
                'required_files': ['answer.txt'],
                'criteria': [{'id': 'R1', 'requirement': 'Return a result', 'priority': 'must',
                              'status': 'todo', 'evidence': []}]}), encoding='utf-8')
            reply = module.call_tool(root, 'workspace_check', {})
            self.assertTrue(reply['isError'])
            data = json.loads(reply['content'][0]['text'])
            self.assertIsInstance(data, dict)

    def test_row_limit_and_arguments_are_validated_before_tool_execution(self):
        module = load_script('mcp_server')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data.csv').write_text('a\n1\n', encoding='utf-8')
            for arguments in ({'path': 'data.csv', 'max_rows': True},
                              {'path': 'data.csv', 'max_rows': 10001},
                              {'path': 'data.csv', 'encoding': 'latin-1'},
                              {'path': 'data.csv', 'unknown': 'value'}):
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    module.call_tool(root, 'profile_csv', arguments)

    def test_existing_external_file_is_rejected(self):
        module = load_script('mcp_server')
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root = parent / 'workspace'
            root.mkdir()
            outside = parent / 'outside.csv'
            outside.write_text('private\nvalue\n', encoding='utf-8')
            for path in ('../outside.csv', str(outside)):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    module.local_path(root, path)

    def test_semiconductor_yield_tool_uses_weighted_counts_and_rejects_duplicate_keys(self):
        module = load_script('mcp_server')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'counts.csv').write_text('lot,tool,tested,passed\nL1,A,100,99\nL2,A,2,1\n', encoding='utf-8')
            args = {'path': 'counts.csv', 'group_by': ['tool'], 'key': ['lot']}
            reply = module.call_tool(root, 'semiconductor_yield', args)
            self.assertFalse(reply['isError'], reply)
            data = json.loads(reply['content'][0]['text'])
            self.assertEqual(data['totals']['tested'], 102)
            self.assertAlmostEqual(data['totals']['pass_rate_pct'], 10000 / 102)
            (root / 'counts.csv').write_text('lot,tool,tested,passed\nL1,A,100,99\nL1,A,2,1\n', encoding='utf-8')
            self.assertTrue(module.call_tool(root, 'semiconductor_yield', args)['isError'])

    def test_spc_tool_freezes_prefix_and_includes_boundary_moving_range(self):
        module = load_script('mcp_server')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'sensor.csv').write_text(
                'timestamp,value,tool\n2026-01-01T00:00:00,10,A\n2026-01-01T00:01:00,11,A\n'
                '2026-01-01T00:02:00,10,A\n2026-01-01T00:03:00,14,A\n', encoding='utf-8')
            reply = module.call_tool(root, 'spc_monitor', {'path': 'sensor.csv', 'value_col': 'value',
                'time_col': 'timestamp', 'baseline_count': 3, 'series_cols': ['tool']})
            self.assertFalse(reply['isError'], reply)
            data = json.loads(reply['content'][0]['text'])
            self.assertAlmostEqual(data['baseline']['mean'], 31 / 3)
            self.assertEqual(data['evaluation'][0]['moving_range'], 4)
            self.assertTrue(data['evaluation'][0]['i_signal'])
            self.assertTrue(data['evaluation'][0]['mr_signal'])

    def test_semiconductor_tool_invalid_options_do_not_run(self):
        module = load_script('mcp_server')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data.csv').write_text('a\n1\n', encoding='utf-8')
            cases = [
                ('semiconductor_yield', {'group_by': 'tool', 'key': ['id']}),
                ('semiconductor_yield', {'group_by': ['tool'], 'key': []}),
                ('semiconductor_yield', {'group_by': ['tool', 'tool'], 'key': ['id']}),
                ('semiconductor_yield', {'group_by': ['tool'], 'key': ['id'], 'tested_col': []}),
                ('spc_monitor', {'value_col': 'v', 'time_col': 't', 'baseline_count': True}),
                ('spc_monitor', {'value_col': 'v', 'time_col': 't', 'baseline_count': 2}),
                ('spc_monitor', {'value_col': 'v', 'time_col': 't', 'baseline_count': 3, 'series_cols': ['a,b']}),
                ('spc_monitor', {'value_col': 'v', 'time_col': 't', 'baseline_count': 3, 'output': 'unexpected.json'}),
            ]
            for name, args in cases:
                with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                    module.call_tool(root, name, {'path': 'data.csv', **args})
            self.assertFalse((root / 'unexpected.json').exists())


if __name__ == '__main__':
    unittest.main()
