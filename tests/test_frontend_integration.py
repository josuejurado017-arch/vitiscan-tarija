"""Dashboard estatico, seguridad local y escenarios GIS contra API real de prueba."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from src.backend.database import ROOT
from src.backend.main import DEMO_COOKIE, Settings, create_app


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        if tag == 'script' and 'src' in attrs:
            self.assets.append(attrs['src'])
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.assets.append(attrs['href'])


class FrontendIntegrationTests(unittest.TestCase):
    def setUp(self):
        approved = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Temp' / 'opencode'
        temporary = tempfile.TemporaryDirectory(prefix='vitiscan-frontend-', dir=approved if approved.is_dir() else None)
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'dashboard.db'
        self.settings = Settings(ingest_token='private-ingest-test', operator_token='private-operator-test',
                                 sim_actions_enabled=True, dashboard_local_demo=True)
        self.app = create_app(self.path, settings=self.settings)
        self.client = self.new_client(self.app)

    def new_client(self, app, *, peer='127.0.0.1', host='127.0.0.1:8000'):
        client = TestClient(app, base_url='http://' + host, client=(peer, 52100))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def trigger(self, action, *, client=None, origin='http://127.0.0.1:8000', key=None):
        return (client or self.client).post('/api/v1/sim/trigger',
                                            headers={'Origin': origin} if origin else {},
                                            json={'action': action, 'idempotency_key': str(key or uuid4())})

    def test_root_serves_dashboard_and_controls(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.headers['content-type'])
        self.assertIn('VITISCAN', response.text)
        self.assertIn('lang="es"', response.text)
        for action in ('cascade', 'failover', 'fire', 'restore'):
            self.assertIn(f'data-action="{action}"', response.text)
        parser = AssetParser()
        parser.feed(response.text)
        self.assertTrue({'map', 'fire-banner', 'hex-viewer', 'heat-layer', 'active-count'} <= parser.ids)

    def test_all_local_assets_serve_200_with_expected_mime(self):
        parser = AssetParser()
        parser.feed(self.client.get('/').text)
        local = [asset for asset in parser.assets if asset.startswith('/')]
        self.assertEqual(set(local), {'/styles.css', '/app.js'})
        for asset in local:
            response = self.client.get(asset)
            self.assertEqual(response.status_code, 200, asset)
            self.assertIn('javascript' if asset.endswith('.js') else 'text/css', response.headers['content-type'])
        self.assertEqual(self.client.get('/index.html').status_code, 200)

    def test_api_docs_and_unknown_routes_not_shadowed_by_static_mount(self):
        self.assertEqual(len(self.client.get('/api/v1/nodes/status').json()['nodes']), 20)
        self.assertEqual(self.client.get('/docs').status_code, 200)
        schema = self.client.get('/openapi.json').json()
        self.assertIn('/api/v1/sim/trigger', schema['paths'])
        self.assertEqual(self.client.get('/api/v1/not-an-endpoint').status_code, 404)
        self.assertEqual(self.client.get('/not-a-file.js').status_code, 404)

    def test_static_mount_does_not_expose_backend_contract_or_database(self):
        for path in ('/main.py', '/database.py', '/.contracts/02_system_contract.json',
                     '/data/vitiscan_tarija.db', '/%2e%2e/backend/main.py'):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_public_config_has_timing_gateway_but_no_secrets(self):
        response = self.client.get('/api/v1/dashboard/config')
        config = response.json()
        self.assertEqual(config['gateway']['node_id'], 0)
        self.assertEqual(config['gateway']['lat'], -21.6485)
        self.assertEqual(config['gateway']['lon'], -64.6342)
        self.assertEqual(config['superframe_ms'], 1500)
        self.assertEqual(config['listen_window_ms'], 35)
        self.assertEqual(config['alert_poll_ms'], 500)
        self.assertEqual(config['auth_mode'], 'local_cookie')
        self.assertIn('no-store', response.headers['cache-control'])
        for path in ('/', '/app.js', '/styles.css', '/api/v1/dashboard/config'):
            text = self.client.get(path).text
            self.assertNotIn(self.settings.operator_token, text)
            self.assertNotIn(self.settings.ingest_token, text)

    def test_local_session_is_httponly_strict_scoped_and_required(self):
        self.assertEqual(self.trigger('cascade').status_code, 401)
        response = self.client.get('/')
        cookie = response.headers['set-cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=strict', cookie)
        self.assertIn('Path=/api/v1/sim', cookie)
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertNotIn(self.client.cookies.get(DEMO_COOKIE), response.text)
        result = self.trigger('cascade')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['reading_count'], 20)

    def test_same_origin_is_mandatory_for_cookie_actions(self):
        self.client.get('/')
        for origin in (None, 'null', 'https://untrusted.test', 'http://127.0.0.1:9000'):
            self.assertEqual(self.trigger('fire', origin=origin).status_code, 403)

    def test_invalid_cookie_is_rejected(self):
        self.client.cookies.set(DEMO_COOKIE, 'not-a-valid-session', path='/api/v1/sim')
        self.assertEqual(self.trigger('fire').status_code, 401)

    def test_remote_peer_cannot_bootstrap_or_use_stolen_cookie(self):
        self.client.get('/')
        remote = self.new_client(self.app, peer='192.0.2.9')
        self.assertNotIn('set-cookie', remote.get('/').headers)
        self.assertEqual(remote.get('/api/v1/dashboard/config').json()['auth_mode'], 'bearer')
        remote.cookies.set(DEMO_COOKIE, self.client.cookies.get(DEMO_COOKIE), path='/api/v1/sim')
        self.assertEqual(self.trigger('fire', client=remote).status_code, 401)

    def test_untrusted_host_cannot_enable_local_session(self):
        client = self.new_client(self.app, host='untrusted.test')
        self.assertNotIn('set-cookie', client.get('/').headers)
        self.assertEqual(client.get('/api/v1/dashboard/config').json()['auth_mode'], 'bearer')
        self.assertEqual(self.trigger('fire', client=client, origin='http://untrusted.test').status_code, 401)

    def test_forwarded_headers_do_not_turn_remote_client_into_loopback(self):
        client = self.new_client(self.app, peer='192.0.2.9')
        response = client.get('/', headers={'X-Forwarded-For': '127.0.0.1', 'X-Forwarded-Host': 'localhost'})
        self.assertNotIn('set-cookie', response.headers)

    def test_demo_cookie_never_authorizes_gateway_ingest(self):
        self.client.get('/')
        response = self.client.post('/api/v1/gateway/ingest', content=b'a5',
                                    headers={'Content-Type': 'application/octet-stream'})
        self.assertEqual(response.status_code, 401)

    def test_default_profile_remains_closed_and_manual_bearer_still_works(self):
        application = create_app(self.path, settings=replace(self.settings, dashboard_local_demo=False))
        client = self.new_client(application)
        self.assertNotIn('set-cookie', client.get('/').headers)
        self.assertEqual(client.get('/api/v1/dashboard/config').json()['auth_mode'], 'bearer')
        self.assertEqual(self.trigger('cascade', client=client).status_code, 401)
        response = client.post('/api/v1/sim/trigger', headers={'Authorization': 'Bearer private-operator-test'},
                               json={'action': 'cascade', 'idempotency_key': str(uuid4())})
        self.assertEqual(response.status_code, 200, response.text)

    def test_actions_disabled_even_with_local_demo_flag(self):
        application = create_app(self.path, settings=replace(self.settings, sim_actions_enabled=False))
        client = self.new_client(application)
        self.assertNotIn('set-cookie', client.get('/').headers)
        self.assertEqual(self.trigger('fire', client=client).status_code, 403)

    def test_restore_recovers_links_and_closes_only_demo_alert_state_without_deleting_history(self):
        self.client.get('/')
        failover = self.trigger('failover').json()
        self.assertEqual(failover['reading_count'], 19)
        nodes = self.client.get('/api/v1/nodes/status').json()['nodes']
        self.assertEqual(nodes[5]['operational_parent_id'], 2)
        fire = self.trigger('fire').json()
        self.assertEqual(fire['packets'][0]['msg_type'], 255)
        nodes = self.client.get('/api/v1/nodes/status').json()['nodes']
        self.assertEqual(nodes[15]['gas_smoke_ppm'], 450, 'Una alerta nueva no debe quedar detras de la cascada anterior.')
        heat = self.client.get('/api/v1/heatmap/gas_smoke_ppm').json()
        self.assertAlmostEqual(max(point[2] for point in heat['values']), 450, places=3)
        self.assertTrue(any(alert['state'] == 'active' for alert in self.app.state.database.alerts()))
        with self.app.state.database.connection() as connection:
            before = connection.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0]
        restored = self.trigger('restore').json()
        self.assertEqual(restored['reading_count'], 20)
        self.assertEqual(restored['closed_demo_alerts'], 1)
        nodes = self.client.get('/api/v1/nodes/status').json()['nodes']
        self.assertEqual(nodes[0]['state'], 'online')
        self.assertEqual(nodes[5]['operational_parent_id'], 1)
        self.assertFalse(nodes[5]['failover'])
        alerts = self.app.state.database.alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['state'], 'inactive')
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0], before + 20)

    def test_restore_action_is_idempotent(self):
        self.client.get('/')
        key = uuid4()
        first = self.trigger('restore', key=key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), self.trigger('restore', key=key).json())

    def test_launcher_prints_exact_commands_without_starting_server(self):
        result = subprocess.run([sys.executable, '-m', 'src.backend.run_demo', '--print-command'],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('http://127.0.0.1:8000', result.stdout)
        self.assertIn(r'.\venv\Scripts\python.exe -m src.backend.run_demo', result.stdout)
        self.assertIn('--no-proxy-headers', result.stdout)

    def test_contract_sha256_is_unchanged(self):
        self.assertEqual(sha256((ROOT / '.contracts/02_system_contract.json').read_bytes()).hexdigest().upper(),
                         'B7B5C98FDBEFE7D0DAADBBB4EEA04F21CD5601E186555836C5AE50A4228D1356')

    @unittest.skipUnless(shutil.which('node'), 'Node opcional solo para verificar logica JS, no para servir dashboard.')
    def test_javascript_binary_and_gis_logic(self):
        result = subprocess.run([shutil.which('node'), str(ROOT / 'tests/frontend_logic.cjs')],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('JS OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
