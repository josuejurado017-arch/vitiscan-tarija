r"""Arranque local: .\venv\Scripts\python.exe -m src.backend.run_demo."""

from __future__ import annotations

import argparse
import secrets
import threading
import webbrowser
from dataclasses import replace

import uvicorn

from src.backend.database import Database
from src.backend.main import Settings, create_app
from src.backend.seed_tarija import run_live_simulation, seed_history

POWERSHELL_COMMAND = r'.\venv\Scripts\python.exe -m src.backend.run_demo'
UVICORN_COMMAND = r'.\venv\Scripts\python.exe -m uvicorn src.backend.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true', help='No abrir navegador automaticamente.')
    parser.add_argument('--print-command', action='store_true', help='Solo imprimir instrucciones PowerShell.')
    args = parser.parse_args()
    print('PowerShell, desde D:\\desarrollo:')
    print(POWERSHELL_COMMAND)
    print('URL: http://127.0.0.1:8000')
    print('Equivalente manual (en esta misma consola):')
    print("$env:APP_MODE='simulation'")
    print("$env:SIM_ACTIONS_ENABLED='true'")
    print("$env:DASHBOARD_LOCAL_DEMO='true'")
    print(UVICORN_COMMAND)
    print("# En otra consola: Start-Process 'http://127.0.0.1:8000'")
    if args.print_command:
        return
    settings = Settings.from_env()
    if settings.app_mode != 'simulation':
        parser.error('APP_MODE debe ser simulation; no se sobreescribe una configuracion real.')
    settings = replace(settings, sim_actions_enabled=True, dashboard_local_demo=True,
                       operator_token=settings.operator_token or secrets.token_urlsafe(32),
                       ingest_token=settings.ingest_token or secrets.token_urlsafe(32))
    application = create_app(settings=settings)
    database: Database = application.state.database
    history = seed_history(database)
    baseline = run_live_simulation(database, 'cascade')
    print(f'Seed sintetico: {history["accepted"]} nuevas, {history["duplicates"]} existentes; '
          f'red nominal {baseline["reading_count"]}/20.')
    print('Sesion demo HttpOnly; sin tokens en HTML, JavaScript, URL o consola.')
    print('Solo loopback; Ctrl+C para detener. Leaflet/CDN y cartografia requieren Internet.')
    if not args.no_browser:
        opener = threading.Timer(1.5, webbrowser.open, args=('http://127.0.0.1:8000',))
        opener.daemon = True
        opener.start()
    uvicorn.run(application, host='127.0.0.1', port=8000, proxy_headers=False, workers=1)


if __name__ == '__main__':
    main()
