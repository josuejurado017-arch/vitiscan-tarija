---
title: Contrato y arquitectura inicial — Viñedos Tarija
date: 2026-11-09
status: frozen
contract_version: 1.0.0
tags:
  - viniedos-tarija
  - arquitectura
  - decisiones
---

# Inicio del prototipo: fases 0 y 1 completadas

## Decisión

El **contrato binario y la topología de Tarija han sido congelados** por autorización expresa del usuario para esta fase. El Contrato de Sistema está activo y es la única fuente de verdad para implementar posteriormente simulador, firmware, backend y dashboard.

- Raíz de trabajo: `D:\desarrollo`. No se migraron ni modificaron archivos del disco C.
- Contrato: [[../../.contracts/02_system_contract.json|02_system_contract.json]], ID `viniedos-tarija-system-02`, versión `1.0.0`, estado `frozen`.
- Memoria rectora de la sesión: [[../../MEMORY.md|MEMORY.md]].
- SHA-256 del contrato congelado: `9B90D26AA06D6F1F10AA768BBDADF79C294948B83E0EB2768DC665FEAFD38C4D`.
- Cualquier modificación requiere nueva versión, aprobación explícita del usuario y coordinación con los consumidores. El hash permite detectar cambios; no constituye un bloqueo físico del archivo.

## Interfaces congeladas

- Little-endian; cabecera de 6 bytes: `magic=0xA5`, `msg_type`, `level`, `sender_id`, `parent_id`, `reading_count`. Formato declarativo Python: `<6B`.
- Lectura de 12 bytes: `node_id`, `soil_temp_x10`, `soil_moisture`, `amb_temp_x10`, `amb_humidity`, `gas_smoke`, `battery_pct`, `status_flags`. Formato declarativo Python: `<BhHhBHBB`. C/C++ deberá usar `__attribute__((packed))` y verificar tamaños.
- Máximo 20 lecturas y 246 bytes utilizados por paquete, dentro del límite de 250 bytes. JSON se construye únicamente en el Gateway.
- Sensores analógicos exclusivamente ADC1: humedad capacitiva GPIO34 y MQ-2 GPIO35. ADC2 prohibido. MQ-2 requiere protección eléctrica, calibración y calentamiento; no es un detector certificado.
- Gateway en latitud `-21.6485`, longitud `-64.6342`; 20 nodos `V-01` a `V-20`, cinco ramas radiales y cuatro niveles, 22 m entre niveles de cada rama. Coordenadas y estados iniciales son **semillas sintéticas**, no un relevamiento real.
- Cascada half-duplex nivel 4 -> 3 -> 2 -> 1 -> Gateway: 300 ms por nivel, 1200 ms por cascada. Cada nivel: guarda inicial de 15 ms, cinco sub-slots de 54 ms (39 ms activos + 15 ms de guarda) y guarda final de 15 ms.
- Alertas con escucha de 35 ms y flooding acotado; cuatro rondas fuera de la cascada, en superframes de 1500 ms. Muestreo de seguridad cada 45 s, sueño segmentado y telemetría cada 900-1800 s, según contrato.
- Seis rutas REST congeladas: ingesta del Gateway, alertas de incendio, topología, heatmap por capa y acciones de simulación `run-cascade` y `trigger-fire`. Las acciones requieren modo simulación y habilitación expresa; nunca activan radio real.

## Límites explícitos antes del despliegue físico

La cabecera estricta no tiene timestamp, cycle ID, secuencia, TTL ni índice de fragmento. El prototipo usa reloj y epochs coordinados externamente por el simulador; no añade bytes ocultos. La sincronización con timestamp del padre y las garantías físicas requieren un contrato de control futuro antes de firmware operativo.

Los tiempos de aire, alcance, RSSI, autonomía y calentamiento del MQ-2 deben validarse en hardware. No se promete recepción durante Deep Sleep ni latencia garantizada de incendio. Este prototipo **no es un sistema certificado de seguridad**.

## Verificación y siguiente paso

Se verificaron JSON válido, offsets y tamaños 6/12, capacidad de paquete, muestra binaria, 20 IDs únicos, padres de nivel anterior, separación radial de 22 m, temporización y los seis endpoints. Se verificó la existencia de `.contracts/`, `.obsidian-memory/` y los cuatro directorios de `src/`.

No se escribió código de aplicación. Próxima fase pendiente de instrucción: simulador de red y empaquetador binario Python en `src/simulator/`, consumiendo este contrato sin modificarlo.
