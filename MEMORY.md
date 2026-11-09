# MEMORIA DE LARGO PLAZO - SISTEMA VIÑEDOS TARIJA
> Este archivo es consultado por OpenCode y Codex para mantener persistencia entre sesiones en el disco D.

## 1. Estado Actual del Proyecto
- **Carpeta de Trabajo:** D:\desarrollo
- **Fase Activa:** Prototipo funcional (Simulador Python + Firmware ESP32 + Backend FastAPI + Dashboard Leaflet).
- **Arquitectura de Red:** Cascada TDMA de afuera hacia adentro (Niveles 4 a 1 -> Gateway Nivel 0) sobre ESP-NOW. Trama binaria estricta de 12 bytes por lectura + 6 bytes de cabecera.
- **Contrato de Sistema:** ACTIVO y congelado, versión 2.0.0 (2026-11-09), en `.contracts/02_system_contract.json`; revisión incompatible autorizada para códigos de mensaje y gas sintético. v1.0.0 archivada íntegra en `.contracts/archive/02_system_contract.v1.0.0.json`. Registro: [[.obsidian-memory/decisions/02-protocolo-v2-gas-sintetico|ADR-002]].
- **Simulador:** IMPLEMENTADO en `src/simulator/` (protocolo binario, cascada, conmutación, flooding y autonomía ilustrativa); demo ejecutada y 18 pruebas aprobadas tanto en modo normal como con `python -O`. Backend IDW, dashboard y firmware siguen pendientes.

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
- **Módulo:** src/simulator/ (100% operativo, 21 tests aprobados).
- **Métricas verificadas:** Cabecera 6B, Payload 12B/nodo, fragmentación máx 246B.
- **Pruebas superadas:** Cascada 20/20, Failover V-01 -> V-02 (19/20), Alerta de incendio V-16 en ventanas de 35 ms.
- **Nota de contrato:** Rango 0-500 ppm cumple contrato congelado; 0-1000 ppm habilitado como perfil demo.
