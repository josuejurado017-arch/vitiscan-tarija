# MEMORIA DE LARGO PLAZO - SISTEMA VIÑEDOS TARIJA
> Este archivo es consultado por OpenCode y Codex para mantener persistencia entre sesiones en el disco D.

## 1. Estado Actual del Proyecto
- **Carpeta de Trabajo:** D:\desarrollo
- **Fase Activa:** Prototipo demo auditado (Python/FastAPI/SQLite/Leaflet + firmware ESP32 de banco, no certificado).
- **Arquitectura de Red:** Cascada TDMA de afuera hacia adentro (Niveles 4 a 1 -> Gateway Nivel 0) sobre ESP-NOW. Trama binaria estricta de 12 bytes por lectura + 6 bytes de cabecera.
- **Contrato de Sistema:** ACTIVO y congelado, versión 2.0.0 (2026-11-09), en `.contracts/02_system_contract.json`; revisión incompatible autorizada para códigos de mensaje y gas sintético. v1.0.0 archivada íntegra en `.contracts/archive/02_system_contract.v1.0.0.json`. Registro: [[.obsidian-memory/decisions/02-protocolo-v2-gas-sintetico|ADR-002]].
- **Estado auditado:** simulador, backend SQLite/IDW y dashboard operativos en simulación; firmware de banco implementado, ambos targets compilados con `-Werror`. Suite actual **103/103**, también con `python -O`, sin warnings ni omisiones. Validación física y API HTTP contractual completa siguen pendientes.

## 2. Decisiones Técnicas Inmutables
- **Pines Hardware ESP32:** Sensores analógicos (humedad capacitiva y MQ-2) obligatoriamente en pines **ADC1** (GPIO34, GPIO35). ADC2 prohibido por conflicto con Wi-Fi.
- **Formato de Paquete en Aire:** Prohibido enviar JSON por radio. Solo binario (struct en Python, __attribute__((packed)) en C/C++).
- **Alerta de Incendio:** Disparo fuera de ciclo por flooding con micro-ventanas de escucha de 35ms en repetidores.
- **Protocolo v2:** Cabecera `<BBBBBB>` (6 B), lectura `<BhHhBHBB>` (12 B). BEACON=0x01, CASCADE_DATA=0x02, ACK=0x03, FIRE_ALERT=0xFF. Campo `gas_smoke_ppm` uint16 en rango 0..500: exclusivamente ppm sintéticos, no calibrados; umbral demostrativo 300 ppm. No reinterpretar tramas v1 como v2.


## 3. Decisiones de Red y Temporización (Actualizado)
- **Superframes TDMA:** 1500 ms con slots de 300 ms por nivel.
- **Micro-ventanas de Alerta (MQ-2):** 35 ms de escucha periódica sin colisionar con la cascada.
- **Integridad Binaria:** Cabecera exacta de 6 bytes sin timestamp integrado ni ID de ciclo; el simulador usa reloj virtual común y epochs externos. La marca temporal del padre por un canal de control externo queda pendiente antes del firmware físico.
- **Registro en Obsidian:** [[.obsidian-memory/decisions/01-sincronizacion-ventanas-alerta|ADR-001: Sincronización y Ventanas de Alerta]]

## 4. Estado de Implementación - Fase 1 Completada
- **Módulo:** src/simulator/ (operativo en simulación, 24 tests aprobados tras auditoría).
- **Métricas verificadas:** Cabecera 6B, Payload 12B/nodo, fragmentación máx 246B.
- **Pruebas superadas:** Cascada 20/20, Failover V-01 -> V-02 (19/20), Alerta de incendio V-16 en ventanas de 35 ms.
- **Nota de contrato:** Rango 0-500 ppm cumple contrato congelado; 0-1000 ppm habilitado como perfil demo.

## 5. Estado de Implementación - Fase 3 Completada
- **Módulo:** src/backend/ (FastAPI + SQLite WAL + Interpolación IDW).
- **Datos inicializados:** 1.920 lecturas históricas + ciclo en vivo 20/20 nodos.
- **Pruebas superadas:** 39/39 en Backend tras auditoría; total actual del proyecto 103/103 en modo normal y `-O`.
- **Seguridad y Documentación:** Configuración, tokens y habilitación de acciones API documentadas en src/backend/README.md. Contrato base SHA-256 intacto.

## 6. Estado de Implementación - Fase 4 Completada
- **Módulo:** src/frontend/ integrado en FastAPI (src.backend.run_demo).
- **Funcionalidades:** Mapa GIS del Valle Central de Tarija, vectores de topología TDMA/failover, capas de calor IDW, visor HEX en vivo y 4 controles de simulación.
- **Métricas y Pruebas:** 20/20 de integración frontend; total auditado 103/103, incluyendo `-O`. Chrome verifica botones, cinco capas, failover, polling externo, móvil y reintento idempotente tras 503. Tiempos locales medidos, no garantía RF. Contrato SHA-256 intacto.

## 7. Firmware - Estado real de la Fase 2
- **Módulo:** `src/firmware-esp32/`, targets `node_sensor` y `gateway_node` compilados; 20/20 pruebas de paridad C/C++/Python y puente UART/HTTP. Sin flash ni ensayos físicos.
- **Seguridad de banco:** BEACON anuncia presencia, no reloj. Pulso externo GPIO32 + gate GPIO39 propuestos para banco; flags de sincronía/TX deshabilitados por defecto. Deep Sleep conservador solo huérfanos/sin sincronía; repetidores y consumo real pendientes de validación.
- **Sensores:** MQ-2 físico siempre `gas_invalid=1` hasta calibración; calefactor externo por MOSFET, no desde GPIO. Demo sintética separada.
- **Pines:** humedad GPIO34/ADC1_CH6; MQ-2 GPIO35/ADC1_CH7; OneWire4; DHT22 digital27; SDA21/SCL22 batería MAX17048; gate MOSFET33; UART TX1/RX3.

## 8. Auditoría integral y arranque
- **Arranque:** `.\venv\Scripts\python.exe -m src.backend.run_demo` abre `http://127.0.0.1:8000`, sin copiar tokens; sesión local HttpOnly y Origin estricto.
- **QA completa:** `.\venv\Scripts\python.exe tools/run_tests.py` y `.\venv\Scripts\python.exe -O tools/run_tests.py`; warnings como errores, sin skips. Simulador24 + Backend39 + Frontend20 + Firmware20 = **103**.
- **Correcciones:** TTL de alertas Gateway, IDs estrictos, cota 246 B, dedup/motivo 0xFF/latencia y orden de alertas, caducidad de metadatos, JSON RFC3339/UTF-8/profundidad, IDW finito, reintentos UI sin identidad nueva ante 5xx, sesión en index.html, presupuesto TX y asociación de padre entre telemetrías de 900 s.
- **Higiene:** `venv/`, caches y journals ignorados. Se retiraron 1.428 archivos de venv solo del índice, con autorización explícita; se conserva el entorno local y no se hizo commit.
- **Finales de línea:** `.gitattributes` fija LF para fuentes; contratos congelados excluidos de normalización automática.
- **Contrato SHA-256:** `B7B5C98FDBEFE7D0DAADBBB4EEA04F21CD5601E186555836C5AE50A4228D1356`, intacto. Diferencias demo (0..1000 gas, HTTP binario, cookie/polling) y bloqueos físicos en `docs/AUDIT.md`; no afirmar conformidad contractual completa ni certificación de campo.
