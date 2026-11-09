"""Ejecutar desde la raiz: python src/simulator/cli_demo.py."""

from __future__ import annotations

if __package__:
    from .binary_protocol import (CONTRACT, HEADER_STRUCT, READING_STRUCT, Header,
                                  MessageType, NodeReading, fragment_readings,
                                  pack_packet, unpack_packet)
    from .cascade_network import CascadeNetwork
else:
    from binary_protocol import (CONTRACT, HEADER_STRUCT, READING_STRUCT, Header,
                                 MessageType, NodeReading, fragment_readings,
                                 pack_packet, unpack_packet)
    from cascade_network import CascadeNetwork


def main() -> None:
    print('VINEDOS TARIJA | simulador ESP-NOW | contrato ' + CONTRACT['version'])
    print('SOLO SIMULACION: gas 0..500 ppm sinteticos; no calibracion MQ-2 ni radio real.\n')
    network = CascadeNetwork()
    sample = NodeReading(**CONTRACT['samples']['raw'])
    reading_bytes = sample.pack()
    packet = pack_packet(Header(MessageType.CASCADE_DATA, 1, 1, 0, 1), [sample])
    if unpack_packet(packet)[1] != (sample,):
        raise RuntimeError('Fallo del round-trip binario.')
    print('[1] BINARIO LITTLE-ENDIAN')
    print(f'Header: {HEADER_STRUCT.size} bytes | NodeReading: {READING_STRUCT.size} bytes')
    print('Lectura HEX (12 B): ' + reading_bytes.hex(' '))
    print('Paquete HEX (18 B): ' + packet.hex(' '))
    print(f'Decodificado: suelo={sample.soil_temp_x10 / 10:.1f} C, '
          f'humedad={sample.soil_moisture / 100:.1f}%, '
          f'gas={sample.gas_smoke_ppm} ppm SINTETICOS, bateria={sample.battery_pct}%')
    readings = [network.sample(node_id) for node_id in range(1, 21)]
    fragments = fragment_readings(readings * 2 + readings[:5], level=1, sender_id=1, parent_id=0)
    print('Fragmentacion: 45 entradas (20 IDs, incluye reenvios) -> '
          + ', '.join(f'{len(payload)} B' for payload in fragments))
    print('Cada fragmento <=20 lecturas; el Gateway deduplica por nodo/epoch externo.\n')

    print('[2] DESCUBRIMIENTO Y CASCADA')
    network.discover()
    found = sum(node.primary_parent is not None for node in network.nodes.values() if node.node_id)
    beacon = next(event for event in network.events if event.kind == MessageType.BEACON)
    print(f'Gateway (-21.6485, -64.6342); 5 ramas x 4 niveles; 22 m por tramo.')
    print(f'BEACON nivel 0: {beacon.payload.hex(" ")} | asociados: {found}/20')
    for node_id in (6, 11, 16):
        node = network.nodes[node_id]
        print(f'{node.label}: padre={node.primary_parent}, respaldo={node.backup_parent}, '
              f'RSSI={network.rssi(node_id, node.primary_parent):.1f} dBm')
    normal = network.run_cascade()
    for level in CONTRACT['tdma']['level_order']:
        frames = [event for event in network._last_cascade_events
                  if event.kind == MessageType.CASCADE_DATA and network.nodes[event.sender_id].level == level]
        offset = CONTRACT['tdma']['level_offsets_ms'][str(level)]
        print(f'N{level} [{offset:4d},{offset + 300:4d}) ms: '
              f'{len(frames)} paquetes, {len(frames[0].payload)} B/paquete, ACK validos')
    print(f'Gateway: {len(normal.readings)}/20 lecturas unicas; faltantes={normal.missing_node_ids}')
    print('Superframe=1500 ms; cascada=[0,1200); escucha alerta=35 ms en [1200,1420).\n')

    print('[3] CAIDA Y CONMUTACION AUTOMATICA')
    network.set_node_alive(6, False)
    degraded = network.run_cascade()
    print(f'Caida V-06: {len(degraded.readings)}/20 lecturas; faltantes={degraded.missing_node_ids}')
    for node_id, old, new in degraded.failovers:
        print(f'V-{node_id:02d}: 3 intentos sin ACK -> padre {old} a {new}, al limite del epoch')
    recovered = network.run_cascade()
    print(f'Siguiente cascada: {len(recovered.readings)}/20; faltantes={recovered.missing_node_ids}')
    print('No se inventan lecturas de V-06 ni se reciclan muestras del epoch anterior.\n')

    print('[4] FLOODING DE INCENDIO FUERA DE CICLO')
    fire = network.trigger_fire(16)
    fire_started = network.clock_ms
    alerts = network.run_fire_alerts(4)
    delivered_at = alerts.get(fire.pack())
    if delivered_at is None:
        raise RuntimeError('La alerta de demostracion no llego al Gateway.')
    fire_events = [event for event in network.events if event.kind == MessageType.FIRE_ALERT]
    print(f'V-16: gas={fire.gas_smoke_ppm} ppm sinteticos; umbral=300 ppm')
    print(f'{len(fire_events)} broadcasts de 18 B; {len(alerts)} evento unico en Gateway (deduplicado).')
    print(f'Entrega simulada: {delivered_at - fire_started} ms desde inyeccion; '
          'sin garantia de latencia en hardware.')
    print('Escucha=35 ms; sin TX/RX simultaneos; replicas limitadas por cache y horizonte.\n')

    print('[5] AUTONOMIA ILUSTRATIVA (TELEMETRIA CADA 900 s)')
    print('Celda=2600 mAh, 3.7 V; util=80%; eficiencia=85%; MQ-2 continuo=900 mW.')
    print('Nodo  Nivel  Celdas  RX-alerta    Solo electronica     Con calentador MQ-2')
    for node_id, cells in ((16, 1), (1, 1), (1, 2)):
        power = network.battery_report(node_id, cells)
        print(f'V-{node_id:02d}   {network.nodes[node_id].level}       {cells}      '
              f'{power["alert_rx_duty_pct"]:5.2f}%       '
              f'{power["electronics_days"]:6.2f} dias           {power["with_heater_days"]:5.2f} dias')
    print('2 celdas = 1S2P protegido: mismo voltaje, doble capacidad; requiere BMS adecuado.')
    print('Sin calentador no se afirma deteccion MQ-2 valida; no es un diseno de seguridad.')
    network.validate_trace()
    print('\nDEMO OK: binario, TDMA, fallos, flooding y presupuesto energetico verificados.')


if __name__ == '__main__':
    main()
