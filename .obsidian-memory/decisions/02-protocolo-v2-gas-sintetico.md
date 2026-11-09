---
title: Protocolo v2 y gas sintético para el prototipo
date: 2026-11-09
status: accepted
contract_version: 2.0.0
tags:
  - viniedos-tarija
  - protocolo
  - simulador
---

# ADR-002 — Revisión incompatible autorizada y simulador inicial

## Contexto y autorización

El usuario solicitó códigos de mensaje distintos del contrato v1 y un formato que, aunque sumaba 12 bytes, asignaba un byte al gas, dos a batería y temperatura ambiente sin signo. Tras consultar, eligió revisar primero el contrato y pidió ppm para la demostración. Finalmente autorizó **valores sintéticos/normalizados 0..1023 o simulados 0..500 ppm**, sin fórmula de calibración física del MQ-2 todavía. Se elige la segunda alternativa: **0..500 ppm exclusivamente sintéticos**.

## Decisión congelada

- Contrato activo: `.contracts/02_system_contract.json`, **2.0.0**, `frozen`.
- SHA-256 v2: `B7B5C98FDBEFE7D0DAADBBB4EEA04F21CD5601E186555836C5AE50A4228D1356`.
- v1 conservada byte por byte en `.contracts/archive/02_system_contract.v1.0.0.json`; SHA-256: `9B90D26AA06D6F1F10AA768BBDADF79C294948B83E0EB2768DC665FEAFD38C4D`.
- Mensajes: BEACON `0x01`, CASCADE_DATA `0x02`, ACK `0x03`, FIRE_ALERT `0xFF`.
- Cabecera little-endian `<BBBBBB>`, equivalente a `<6B>`, exactamente 6 bytes.
- Lectura corregida `<BhHhBHBB>`, exactamente 12 bytes: `node_id` uint8, `soil_temp_x10` int16, `soil_moisture` uint16, `amb_temp_x10` int16, `amb_humidity` uint8, `gas_smoke_ppm` uint16, `battery_pct` uint8, `status_flags` uint8.
- `gas_smoke_ppm` va de 0 a 500; no representa una especie química ni una lectura calibrada. Gas válido requiere bit `synthetic`. Modo real: `gas_invalid=1` y placeholder cero hasta revisión de calibración futura.
- Umbral de demostración: 300 ppm sintéticos; inyección de incendio: 450 ppm. No son umbrales de seguridad física.
- IDW futuro usa la misma magnitud sintética para el índice visual; no se implementó backend ni IDW en esta fase.
- Máximo 20 lecturas y 246 bytes por paquete. Sin versión dentro de la trama: versión de protocolo provisionada externamente, no mezclar v1/v2.

## Temporización conservada

Se mantiene [[01-sincronizacion-ventanas-alerta|ADR-001]]: slots de 300 ms, guard time de 15 ms, escucha de 35 ms y superframe de 1500 ms. La cascada ocupa `[0,1200)`, las cuatro rondas de alertas `[1200,1420)` y queda silencio hasta 1500 ms. Reloj común y epoch externos solo en simulación; no se añaden timestamp, TTL ni índice de fragmento ocultos.

El cambio a padre alternativo ocurre al límite del epoch después de tres intentos sin ACK. El muestreo previsto es cada 45 s, telemetría cada 900–1800 s; la demo ejecuta epochs manuales consecutivos y alerta inyectada, sin esperar tiempo de pared.

## Resultado de implementación

Archivos en `src/simulator/`: `binary_protocol.py`, `cascade_network.py`, `cli_demo.py`, `test_simulator.py`, `README.md`. Biblioteca estándar, Python >=3.11, sin radio real ni dependencias externas.

- Empaquetado/decodificado estricto con validaciones activas también bajo `-O`.
- 20/20 lecturas en la cascada nominal.
- Caída de V-06: 17/20 en el epoch fallido; V-11 conmuta de padre 6 a 7; siguiente epoch 19/20, solo V-06 ausente.
- Alerta de V-16: 450 ppm sintéticos, broadcasts de 18 bytes, recepción deduplicada en Gateway y validación half-duplex.
- Pruebas: **18 aprobadas en modo normal y 18 con `-O`**, incluyendo archivo v1 intacto, negativos, gas de dos bytes, fragmentación, entradas inválidas, ACK perdidos, caídas, dos orígenes de incendio y energía.
- Solo hay 20 IDs válidos; la prueba de fragmentación de 45 entradas incluye reenvíos, no 45 nodos distintos. Un nodo tiene una muestra por epoch y se deduplica en Gateway.

## Energía y entorno

Supuestos ilustrativos explícitos en el contrato: 2600 mAh/celda, 3.7 V, 80% útil y 85% de conversión. Se informa autonomía electrónica separada de calentador MQ-2 continuo de 900 mW. Dos celdas significan 1S2P protegido, no doble voltaje. No se garantiza validez de detección sin calentador/calibración, ni autonomía real.

No había intérprete instalado accesible: `python` era el alias Microsoft Store. Se utilizó paquete embebible oficial **Python 3.15.2**, en `%LOCALAPPDATA%\Temp\opencode\python-3.15.2-tarija`, con SHA-256 y firma Authenticode verificados. Alias PowerShell temporal; sin modificar PATH ni instalar globalmente. El runtime temporal puede limpiarse; instrucciones de repetición en README.

**No es un sistema certificado de seguridad.** Las mediciones RF, la sincronización física y la calibración MQ-2 siguen pendientes.
