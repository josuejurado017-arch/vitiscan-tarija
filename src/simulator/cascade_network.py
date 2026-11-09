"""Simulacion discreta determinista; no usa radio, red, reloj real ni dependencias."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace

if __package__:
    from .binary_protocol import (CONTRACT, FIRE_TRIGGERED, GAS_INVALID, SYNTHETIC,
                                  Header, MessageType, NodeReading, fragment_readings,
                                  pack_packet, unpack_packet)
else:
    from binary_protocol import (CONTRACT, FIRE_TRIGGERED, GAS_INVALID, SYNTHETIC,
                                 Header, MessageType, NodeReading, fragment_readings,
                                 pack_packet, unpack_packet)


@dataclass
class Node:
    node_id: int
    label: str
    level: int
    branch: int
    east_m: float
    north_m: float
    lat: float
    lon: float
    alive: bool = True
    primary_parent: int | None = None
    backup_parent: int | None = None
    observations: dict[int, tuple[float, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class RadioEvent:
    start_ms: int
    end_ms: int
    sender_id: int
    target_id: int
    received_by: tuple[int, ...]
    payload: bytes
    phase: str

    @property
    def kind(self) -> MessageType:
        return MessageType(self.payload[1])


@dataclass(frozen=True)
class ListenWindow:
    node_id: int
    start_ms: int
    end_ms: int


@dataclass
class AlertEntry:
    reading: NodeReading
    first_seen_ms: int
    transmissions: int = 0


@dataclass
class CascadeResult:
    epoch: int
    start_ms: int
    readings: dict[int, NodeReading]
    missing_node_ids: list[int]
    overflow_node_ids: list[int]
    failovers: list[tuple[int, int | None, int | None]]
    log: list[str]


class CascadeNetwork:
    """El epoch y reloj del padre son metadatos EXTERNOS del simulador.

    Descubrimiento en mantenimiento fuera de TDMA: BEACON solo desde nivel 0;
    niveles superiores oyen CASCADE_DATA de padres ya asociados. Una lectura
    por nodo y epoch; no se arrastran muestras de un epoch incompleto al siguiente.
    """

    def __init__(self, *, ack_losses: dict[tuple[int, int], int] | None = None,
                 data_losses: dict[tuple[int, int], int] | None = None):
        gateway = CONTRACT['topology']['gateway']
        self.nodes = {0: Node(0, gateway['label'], 0, 0, 0, 0, gateway['lat'], gateway['lon'])}
        for row in CONTRACT['topology']['nodes']:
            self.nodes[row['node_id']] = Node(**{name: row[name] for name in
                ('node_id', 'label', 'level', 'branch', 'east_m', 'north_m', 'lat', 'lon')})
        self.timing = CONTRACT['tdma']['timing_ms']
        self.rf = CONTRACT['simulation']['radio_model']
        self.clock_ms = 0
        self.epoch = 0
        self.discovered = False
        self.events: list[RadioEvent] = []
        self.listen_windows: list[ListenWindow] = []
        self.discovery_log: list[str] = []
        self.ack_losses = dict(ack_losses or {})
        self.data_losses = dict(data_losses or {})
        self.alert_cache: dict[int, dict[bytes, AlertEntry]] = defaultdict(dict)
        self.gateway_alerts: dict[bytes, int] = {}
        self.alert_overflow: list[tuple[int, int]] = []
        self._last_cascade_events: list[RadioEvent] = []

    def rssi(self, child_id: int, parent_id: int) -> float:
        a, b = self.nodes[child_id], self.nodes[parent_id]
        distance = max(1.0, math.hypot(a.east_m - b.east_m, a.north_m - b.north_m))
        return round(self.rf['reference_rssi_dbm_at_1m']
                     - 10 * self.rf['path_loss_exponent'] * math.log10(distance), 3)

    def _reachable(self, sender: int, receiver: int) -> bool:
        return (self.nodes[sender].alive and self.nodes[receiver].alive
                and self.rssi(sender, receiver) >= self.rf['sensitivity_dbm'])

    def _record(self, start: int, duration: int, sender: int, target: int,
                recipients: tuple[int, ...], payload: bytes, phase: str) -> None:
        unpack_packet(payload)
        self.events.append(RadioEvent(start, start + duration, sender, target,
                                      recipients, payload, phase))

    def sample(self, node_id: int) -> NodeReading:
        if node_id not in self.nodes or node_id == 0:
            raise ValueError('Nodo de campo desconocido.')
        sample = NodeReading(**CONTRACT['samples']['raw'])
        return replace(sample, node_id=node_id, soil_temp_x10=215 + node_id - 1,
                       soil_moisture=4230 - 45 * (node_id - 1),
                       gas_smoke_ppm=120 + (node_id - 1) * 3)

    def _candidates(self, node: Node, exclude: int | None = None) -> list[int]:
        valid = [parent for parent, (_, seen) in node.observations.items()
                 if parent != exclude and self._reachable(node.node_id, parent)
                 and self.nodes[parent].level == node.level - 1
                 and 0 <= self.clock_ms - seen <= self.rf['observation_valid_ms']]
        return sorted(valid, key=lambda parent: (-node.observations[parent][0], parent))

    def discover(self) -> list[str]:
        """Mantenimiento serializado; las muestras de sondeo no se ingieren."""
        log = []
        for node in self.nodes.values():
            node.observations.clear()
        for level in range(1, 5):
            children = [node for node in self.nodes.values() if node.level == level and node.alive]
            parents = [node for node in self.nodes.values() if node.level == level - 1 and node.alive]
            for parent in parents:
                if parent.node_id == 0:
                    payload = pack_packet(Header(MessageType.BEACON, 0, 0, 255, 0))
                    duration = 1
                elif parent.primary_parent is not None:
                    payload = pack_packet(Header(MessageType.CASCADE_DATA, parent.level,
                                          parent.node_id, parent.primary_parent, 1),
                                          [self.sample(parent.node_id)])
                    duration = self.timing['data_airtime']
                else:
                    continue
                heard = [node.node_id for node in children if self._reachable(parent.node_id, node.node_id)]
                recipients = set(heard)
                if parent.node_id and self._reachable(parent.node_id, parent.primary_parent):
                    recipients.add(parent.primary_parent)
                self._record(self.clock_ms, duration, parent.node_id,
                             255 if parent.node_id == 0 else parent.primary_parent,
                             tuple(sorted(recipients)), payload, 'discovery')
                for child_id in heard:
                    self.nodes[child_id].observations[parent.node_id] = (
                        self.rssi(child_id, parent.node_id), self.clock_ms)
                if parent.node_id and parent.primary_parent in recipients:
                    peer = self.nodes[parent.primary_parent]
                    ack = pack_packet(Header(MessageType.ACK, peer.level, peer.node_id, parent.node_id, 0))
                    self._record(self.clock_ms + duration, 1, peer.node_id,
                                 parent.node_id, (parent.node_id,), ack, 'discovery')
                self.clock_ms += self.timing['attempt'] + self.timing['guard']
            for child in children:
                candidates = self._candidates(child)
                child.primary_parent = candidates[0] if candidates else None
                child.backup_parent = candidates[1] if len(candidates) > 1 else None
                primary = child.primary_parent
                signal = f'{self.rssi(child.node_id, primary):.1f} dBm' if primary is not None else 'sin enlace'
                log.append(f'{child.label} N{level}: padre={primary}, respaldo={child.backup_parent}, {signal}')
        self.clock_ms = self._next_boundary(self.clock_ms)
        self.discovered = True
        self.discovery_log = log
        return log

    def _next_boundary(self, timestamp: int) -> int:
        frame = self.timing['superframe']
        return ((timestamp + frame - 1) // frame) * frame

    def set_node_alive(self, node_id: int, alive: bool) -> None:
        if node_id not in self.nodes or not isinstance(alive, bool):
            raise ValueError('ID o estado invalido.')
        self.nodes[node_id].alive = alive

    @staticmethod
    def _consume_loss(losses: dict[tuple[int, int], int], key: tuple[int, int]) -> bool:
        if losses.get(key, 0) > 0:
            losses[key] -= 1
            return True
        return False

    def run_cascade(self) -> CascadeResult:
        if not self.discovered:
            self.discover()
        base = self._next_boundary(self.clock_ms)
        self.epoch += 1
        event_offset = len(self.events)
        inbox = {node.node_id: ({node.node_id: self.sample(node.node_id)}
                 if node.node_id and node.alive else {}) for node in self.nodes.values()}
        log, failed, overflow = [], {}, set()
        # Recuperacion de orfanos solo al inicio del epoch con observaciones vigentes.
        for node in self.nodes.values():
            if node.node_id and node.alive and node.primary_parent is None:
                candidates = self._candidates(node)
                node.primary_parent = candidates[0] if candidates else None
                node.backup_parent = candidates[1] if len(candidates) > 1 else None
        for level in CONTRACT['tdma']['level_order']:
            level_start = base + CONTRACT['tdma']['level_offsets_ms'][str(level)]
            log.append(f'N{level}: [{level_start - base:4d}, {level_start - base + 300:4d}) ms')
            for node in sorted(self.nodes.values(), key=lambda node: node.node_id):
                if node.level != level or not node.alive:
                    continue
                parent_id = node.primary_parent
                if parent_id is None:
                    log.append(f'  {node.label}: huerfano, sin TX')
                    continue
                start = level_start + self.timing['guard'] + self.timing['subslot'] * (node.branch - 1)
                end = start + self.timing['subslot_active']
                cursor = start
                readings = [inbox[node.node_id][key] for key in sorted(inbox[node.node_id])]
                packets = fragment_readings(readings, level=level, sender_id=node.node_id, parent_id=parent_id)
                acknowledged = True
                for packet in packets:
                    packet_ack = False
                    attempts = 0
                    for attempt in range(self.rf['max_attempts']):
                        if cursor + self.timing['attempt'] > end:
                            overflow.update(reading.node_id for reading in readings)
                            break
                        attempts += 1
                        key = (node.node_id, parent_id)
                        delivered = self._reachable(*key) and not self._consume_loss(self.data_losses, key)
                        self._record(cursor, self.timing['data_airtime'], node.node_id, parent_id,
                                     (parent_id,) if delivered else (), packet, 'cascade')
                        if delivered:
                            _, decoded = unpack_packet(packet)
                            for reading in decoded:
                                existing = inbox[parent_id].get(reading.node_id)
                                if existing is not None and existing != reading:
                                    raise RuntimeError('Dos muestras diferentes de un nodo en un epoch.')
                                inbox[parent_id][reading.node_id] = reading
                            parent = self.nodes[parent_id]
                            ack = pack_packet(Header(MessageType.ACK, parent.level, parent_id, node.node_id, 0))
                            packet_ack = not self._consume_loss(self.ack_losses, key)
                            self._record(cursor + self.timing['data_airtime'], self.timing['ack_airtime'],
                                         parent_id, node.node_id, (node.node_id,) if packet_ack else (),
                                         ack, 'cascade')
                            node.observations[parent_id] = (self.rssi(*key), cursor)
                        cursor += self.timing['attempt']
                        if packet_ack:
                            break
                    if not packet_ack:
                        if attempts == self.rf['max_attempts']:
                            failed[node.node_id] = parent_id
                        acknowledged = False
                        break  # No otro paquete tras ACK ambiguo en el mismo subslot.
                state = ('ACK' if acknowledged else 'sin ACK; cambio al limite de epoch'
                         if node.node_id in failed else 'sin presupuesto; overflow')
                log.append(f'  {node.label}->{parent_id:02d}: {len(readings):2d} lecturas, '
                           f'{len(packets[0]):3d} B, {state}')
        self._last_cascade_events = self.events[event_offset:]
        self._run_alert_windows(base)
        self.clock_ms = base + self.timing['superframe']
        failovers = []
        for node_id, old_parent in sorted(failed.items()):
            node = self.nodes[node_id]
            candidates = self._candidates(node, exclude=old_parent)
            node.primary_parent = candidates[0] if candidates else None
            node.backup_parent = candidates[1] if len(candidates) > 1 else None
            failovers.append((node_id, old_parent, node.primary_parent))
        self.validate_trace()
        readings = inbox[0] if self.nodes[0].alive else {}
        return CascadeResult(self.epoch, base, readings, sorted(set(range(1, 21)) - readings.keys()),
                             sorted(overflow), failovers, log)

    def detects_fire(self, reading: NodeReading, previous: NodeReading | None = None,
                     elapsed_s: float | None = None) -> bool:
        reading.validate()
        thresholds = CONTRACT['fire_alerts']['thresholds_frozen']
        gas = not reading.status_flags & GAS_INVALID and reading.gas_smoke_ppm >= thresholds['gas_ppm_gte']
        temperature = False
        if previous is not None:
            previous.validate()
            if previous.node_id != reading.node_id:
                raise ValueError('La comparacion temporal debe ser del mismo nodo.')
            temperature = (elapsed_s is not None and 0 < elapsed_s <= thresholds['delta_window_max_s']
                           and not (reading.status_flags | previous.status_flags) & (1 << 2)
                           and reading.amb_temp_x10 - previous.amb_temp_x10 >= thresholds['delta_amb_temp_x10_gte'])
        return bool(gas or temperature)

    def _cache_alert(self, node_id: int, reading: NodeReading, timestamp: int) -> None:
        cache = self.alert_cache[node_id]
        for key, entry in list(cache.items()):
            if timestamp - entry.first_seen_ms >= 120000:
                del cache[key]
        key = reading.pack()
        if key in cache:
            return  # No reiniciar horizonte por reaparicion o cambio de bucket.
        if len(cache) >= CONTRACT['fire_alerts']['bounds']['max_pending_entries_per_node']:
            self.alert_overflow.append((node_id, reading.node_id))
            return
        cache[key] = AlertEntry(reading, timestamp)

    def trigger_fire(self, node_id: int, gas_smoke_ppm: int = 450) -> NodeReading:
        if not self.nodes[node_id].alive:
            raise ValueError('Un nodo caido no puede originar una alerta.')
        reading = replace(self.sample(node_id), gas_smoke_ppm=gas_smoke_ppm,
                          status_flags=SYNTHETIC | FIRE_TRIGGERED)
        if not self.detects_fire(reading):
            raise ValueError('La muestra no supera el umbral sintetico de incendio.')
        self._cache_alert(node_id, reading, self.clock_ms)
        return reading

    def _run_alert_windows(self, base: int) -> None:
        bounds = CONTRACT['fire_alerts']['bounds']
        for level in CONTRACT['tdma']['level_order']:
            start = base + self.timing['alert_start'] + self.timing['alert_round'] * (4 - level)
            senders = [node for node in self.nodes.values() if node.level == level and node.alive]
            receivers = [node for node in self.nodes.values() if node.level == level - 1 and node.alive]
            for node in senders:
                self.listen_windows.append(ListenWindow(node.node_id, start, start + 35))
            for node in receivers:
                self.listen_windows.append(ListenWindow(node.node_id, start + 5, start + 40))
            for node in senders:
                tx = start + 35 + node.branch - 1
                pending = [entry for entry in self.alert_cache[node.node_id].values()
                           if 0 <= tx - entry.first_seen_ms < bounds['forward_horizon_ms']
                           and entry.transmissions < bounds['max_transmissions_per_cache_entry']]
                if not pending:
                    continue
                entry = min(pending, key=lambda entry: entry.reading.node_id)
                payload = pack_packet(Header(MessageType.FIRE_ALERT, level, node.node_id, 255, 1),
                                      [entry.reading])
                heard = tuple(peer.node_id for peer in receivers if self._reachable(node.node_id, peer.node_id))
                self._record(tx, self.timing['alert_airtime'], node.node_id, 255, heard, payload, 'alert')
                entry.transmissions += 1
                _, (decoded,) = unpack_packet(payload)
                for peer in heard:
                    if peer == 0:
                        self.gateway_alerts.setdefault(decoded.pack(), tx + self.timing['alert_airtime'])
                    else:
                        self._cache_alert(peer, decoded, tx + self.timing['alert_airtime'])

    def run_fire_alerts(self, superframes: int = 4) -> dict[bytes, int]:
        if isinstance(superframes, bool) or not isinstance(superframes, int) or superframes < 1:
            raise ValueError('superframes debe ser entero positivo.')
        if not self.discovered:
            self.discover()
        for _ in range(superframes):
            base = self._next_boundary(self.clock_ms)
            self._run_alert_windows(base)
            self.clock_ms = base + self.timing['superframe']
        self.validate_trace()
        return dict(self.gateway_alerts)

    def validate_trace(self) -> None:
        """Verifica half-duplex, subslots completos y escucha de alerta de 35 ms."""
        occupied: dict[int, int] = {}
        for event in sorted(self.events, key=lambda event: event.start_ms):
            for node_id in (event.sender_id, *event.received_by):
                if occupied.get(node_id, -1) > event.start_ms:
                    raise RuntimeError(f'Colision half-duplex en nodo {node_id}.')
                occupied[node_id] = event.end_ms
            phase = event.start_ms % self.timing['superframe']
            duration = event.end_ms - event.start_ms
            if event.phase == 'cascade':
                child_id = event.target_id if event.kind == MessageType.ACK else event.sender_id
                child = self.nodes[child_id]
                start = (CONTRACT['tdma']['level_offsets_ms'][str(child.level)]
                         + self.timing['guard'] + self.timing['subslot'] * (child.branch - 1))
                if not start <= phase < phase + duration <= start + self.timing['subslot_active']:
                    raise RuntimeError('Cascada fuera del subslot activo; invade guarda u otro nivel.')
            if event.phase == 'alert':
                sender = self.nodes[event.sender_id]
                start = (self.timing['alert_start'] + self.timing['alert_round'] * (4 - sender.level)
                         + self.timing['alert_listen'] + sender.branch - 1)
                if phase != start or duration != self.timing['alert_airtime']:
                    raise RuntimeError('Alerta fuera de su mini-TX reservado.')
                for receiver in event.received_by:
                    if not any(window.node_id == receiver and window.start_ms <= event.start_ms
                               and event.end_ms <= window.end_ms for window in self.listen_windows):
                        raise RuntimeError('Receptor de alerta fuera de su ventana de escucha.')
                if any(window.node_id == event.sender_id and window.start_ms < event.end_ms
                       and event.start_ms < window.end_ms for window in self.listen_windows):
                    raise RuntimeError('TX de alerta durante escucha del mismo nodo.')
        for window in self.listen_windows:
            phase = window.start_ms % self.timing['superframe']
            if (window.end_ms - window.start_ms != self.timing['alert_listen']
                    or not 1200 <= phase < phase + self.timing['alert_listen'] <= 1420):
                raise RuntimeError('Escucha distinta de 35 ms o solapada con la cascada.')

    def battery_report(self, node_id: int, cells: int = 1,
                       telemetry_interval_s: float = 900) -> dict[str, float]:
        """Estimacion nominal conservadora, sin trafico de incendio continuo.

        Incluye escucha de 35ms, despertares, reserva RX de slots y muestreo a 45s.
        Corrientes/consumos ilustrativos. El calentador se informa por separado.
        """
        if node_id not in self.nodes or node_id == 0 or cells not in (1, 2):
            raise ValueError('Requiere nodo de campo y 1 o 2 celdas.')
        if not 900 <= telemetry_interval_s <= 1800 or not math.isclose(telemetry_interval_s % 1.5, 0):
            raise ValueError('Telemetria: 900..1800 s, multiplo de 1.5 s.')
        node = self.nodes[node_id]
        p = CONTRACT['simulation']['battery_model']
        rounds = 1 if node.level == 4 else 2
        frame_s = self.timing['superframe'] / 1000
        alert_rx_s = rounds * self.timing['alert_listen'] / 1000
        wake_s = rounds * p['wake_ms'] / 1000
        tx_s = sum((event.end_ms - event.start_ms) / 1000 for event in self._last_cascade_events
                   if event.sender_id == node_id)
        if not self._last_cascade_events:
            tx_s = (3 + (1 if node.level < 4 else 0)) / 1000
        # Escucha completa de cinco subslots de hijos, aun si solo tiene uno.
        cascade_s = (39 + (5 * 39 if node.level < 4 else 0)) / 1000
        rx_s = max(0.0, cascade_s - tx_s)
        sample_interval = CONTRACT['fire_alerts']['gas_sample_interval_s']
        sample_s = (p['sensor_active_ms_per_sample'] + p['wake_ms']) / 1000
        tx_fraction = tx_s / telemetry_interval_s
        rx_fraction = alert_rx_s / frame_s + rx_s / telemetry_interval_s
        awake_fraction = wake_s / frame_s + sample_s / sample_interval
        awake_fraction += 2 * p['wake_ms'] / 1000 / telemetry_interval_s
        sleep_fraction = 1 - tx_fraction - rx_fraction - awake_fraction
        if sleep_fraction < 0:
            raise RuntimeError('Presupuesto de actividad imposible.')
        current_ma = (p['tx_ma'] * tx_fraction + p['rx_ma'] * rx_fraction
                      + p['awake_ma'] * awake_fraction + p['sleep_ma'] * sleep_fraction
                      + p['sensor_current_ma'] * p['sensor_active_ms_per_sample'] / 1000 / sample_interval)
        electronic_mw = p['esp_voltage_v'] * current_ma / p['converter_efficiency']
        heater_mw = p['mq2_heater_mw'] / p['converter_efficiency']
        usable_wh = cells * p['cell_capacity_mah'] / 1000 * p['cell_voltage_v'] * p['usable_fraction']
        return {'electronics_ma': current_ma, 'electronics_days': usable_wh / (electronic_mw / 1000) / 24,
                'with_heater_days': usable_wh / ((electronic_mw + heater_mw) / 1000) / 24,
                'alert_rx_duty_pct': alert_rx_s / frame_s * 100, 'usable_wh': usable_wh}
