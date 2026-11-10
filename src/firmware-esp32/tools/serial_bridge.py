"""Puente UART/HTTP del perfil demo existente; nunca mezcla muestras reales.

Ejecutar con --port COM3 (pyserial) o JSONL por stdin. No se abren puertos al
importar. Credencial solo desde GATEWAY_INGEST_TOKEN; URL local por defecto.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.simulator.binary_protocol import SYNTHETIC, MessageType, unpack_packet


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None  # no reenviar Bearer a otro origen mediante redireccion


def validate_envelope(document: dict) -> dict:
    fields = {'gateway_id', 'mode', 'cycle_id', 'received_at', 'payload_hex'}
    if not isinstance(document, dict) or set(document) != fields:
        raise ValueError('Envelope UART incompleto, diagnostico o en cuarentena.')
    if any(not isinstance(document[field], str) for field in fields):
        raise ValueError('Todos los campos UART deben ser cadenas, sin timestamps null.')
    if document['gateway_id'] != 'GW-00' or document['mode'] != 'simulation':
        raise ValueError('El backend actual solo admite simulacion; datos reales quedan en cuarentena.')
    UUID(document['cycle_id'])
    timestamp = datetime.fromisoformat(document['received_at'].replace('Z', '+00:00'))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError('Timestamp Gateway debe llevar zona horaria.')
    header, readings = unpack_packet(bytes.fromhex(document['payload_hex']))
    if header.msg_type not in (MessageType.CASCADE_DATA, MessageType.FIRE_ALERT):
        raise ValueError('No se ingieren paquetes de control.')
    if header.msg_type == MessageType.CASCADE_DATA and header.parent_id != 0:
        raise ValueError('DATA no dirigido al Gateway.')
    if any(not reading.status_flags & SYNTHETIC for reading in readings):
        raise ValueError('No cambiar bits para fingir que una medicion real es sintetica.')
    return document


def post_envelope(document: dict, url: str, token: str) -> dict:
    validate_envelope(document)
    parsed = urlsplit(url)
    if parsed.path != '/api/v1/gateway/ingest' or parsed.query or parsed.fragment or parsed.username is not None:
        raise ValueError('Usar URL exacta de ingesta, sin credenciales/query/fragment.')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise ValueError('HTTPS obligatorio fuera de localhost.')
    if not token:
        raise ValueError('Falta GATEWAY_INGEST_TOKEN.')
    payload = json.dumps(document, separators=(',', ':')).encode('utf-8')
    opener = build_opener(NoRedirect())
    # Reintentos conservan exactamente UUID, timestamp y bytes del Gateway.
    for attempt in range(3):
        request = Request(url, payload, {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
        try:
            with opener.open(request, timeout=10) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code < 500 or attempt == 2:
                raise RuntimeError(f'Ingesta HTTP {error.code}; no confirmada.') from None
        except (URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError('Sin confirmacion HTTP; conservar envelope para reintento.') from None
        time.sleep(0.2 * (attempt + 1))
    raise RuntimeError('Ingesta no confirmada.')


def uart_lines(source, *, continuous: bool = False):
    """Acumula fragmentos entre reservas UART; timeout no equivale a fin de linea."""
    pending = bytearray()
    while True:
        chunk = source.readline(2049)
        if not chunk:
            if continuous:
                continue
            if pending:
                raise ValueError('EOF con envelope UART truncado.')
            return
        pending.extend(chunk)
        if len(pending) > 2048:
            raise ValueError('Envelope UART demasiado grande; no se descarta silenciosamente.')
        if chunk.endswith(b'\n'):
            yield bytes(pending)
            pending.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='COM3, /dev/ttyUSB0; omitir para stdin JSONL.')
    parser.add_argument('--url', default='http://127.0.0.1:8000/api/v1/gateway/ingest')
    args = parser.parse_args()
    token = os.environ.get('GATEWAY_INGEST_TOKEN', '')
    if not token:
        parser.error('Definir GATEWAY_INGEST_TOKEN en el entorno; no pasarlo por linea de comandos.')
    port = None
    if args.port:
        import serial  # dependencia de PlatformIO; opcional para stdin
        port = serial.Serial(args.port, 115200, timeout=1, write_timeout=1)
        # Reset DTR puede reiniciar el ESP32: esperar arranque antes de provisionar UTC.
        time.sleep(2)
        port.write(f'UTC {time.time_ns() // 1000}\n'.encode('ascii'))
    source = port if port else sys.stdin.buffer
    try:
        for line in uart_lines(source, continuous=bool(port)):
            if line.startswith(b'#'): continue
            try:
                result = post_envelope(json.loads(line), args.url, token)
                print(json.dumps(result, ensure_ascii=False), flush=True)
            except (ValueError, TypeError, RuntimeError) as error:
                print(f'CUARENTENA: {error}', file=sys.stderr)
                # No declarar entrega ni descartar silenciosamente una muestra fallida.
                raise SystemExit(1) from None
    except ValueError as error:
        print(f'CUARENTENA: {error}', file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if port: port.close()


if __name__ == '__main__':
    main()
