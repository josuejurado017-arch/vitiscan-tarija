#include "bench_runtime.h"
#include "board_sensors.h"
#include <esp_timer.h>

using namespace cascade;
static_assert(bench::SELF_ID >= 1 && bench::SELF_ID <= 20, "Firmware sensor requiere ID 1..20");

static ParentTable parents;
static ReadingSet readings;
RTC_DATA_ATTR static AlertCache alerts;
static uint8_t frozenParent = 255;
static uint8_t outgoing[MAX_PAYLOAD_BYTES];
static size_t outgoingLength = 0;
static uint8_t attempts = 0;
static bool acknowledged = false, waiting = false, exhausted = false;
static int64_t attemptUs = 0;
static uint32_t lastAlertFrame = UINT32_MAX;
static uint64_t nextGasSample = 0, previousSampleMs = 0, nextProbe = 0;
static NodeReading previousSample{};
static uint32_t overflow = 0;

static void ackChild(uint8_t child, int64_t deadlineUs, bool maintenance = false) {
    const PacketHeader header{PROTOCOL_MAGIC, ACK, bench::LEVEL, bench::SELF_ID, child, 0};
    uint8_t bytes[6];
    const size_t length = protocol_encode(&header, nullptr, bytes, sizeof(bytes));
    bench::send(bytes, length, child, deadlineUs, maintenance);
}

static void newFrame() {
    const uint8_t oldParent = parents.primary;
    parents.epochBoundary(bench::retainedMillis()); // conmutar solo aqui, tras 3 DATA sin ACK
    if (oldParent != parents.primary) outgoingLength = 0;
    frozenParent = parents.primary;
    readings.clear();
    if (bench::clock.telemetry) readings.add(sensors::snapshot(bench::SELF_ID));
    outgoingLength = 0; attempts = 0;
    waiting = acknowledged = exhausted = false;
}

static void consumeRadio() {
    bench::Observation observed;
    while (bench::observation(observed)) parents.observe(bench::SELF_ID, observed.id, observed.rssi, observed.atMs);
    bench::Received event;
    while (bench::receive(event)) {
        RadioPacket packet;
        if (!protocol_decode(event.bytes, event.length, &packet)) continue;
        const auto &header = packet.header;
        if (header.msg_type == BEACON) continue; // presencia, JAMAS timestamp/fase de reloj
        if (bench::maintenance) {
            if (header.msg_type == CASCADE_DATA && header.parent_id == bench::SELF_ID && header.level == bench::LEVEL + 1)
                ackChild(header.sender_id, esp_timer_get_time() + 2000, true);
            continue; // sondeos no se agregan ni se atribuyen a un epoch operativo
        }
        uint32_t phase;
        if (!bench::clock.phaseAt(event.atUs, phase)) continue;
        if (header.msg_type == ACK && waiting && header.sender_id == frozenParent &&
            header.parent_id == bench::SELF_ID && event.atUs >= attemptUs && event.atUs <= attemptUs + 5000 &&
            dataWindow(bench::SELF_ID).contains(phase)) {
            acknowledged = true; waiting = false; parents.failedAttempts = 0;
        } else if (header.msg_type == CASCADE_DATA && bench::clock.telemetry &&
                   header.parent_id == bench::SELF_ID && header.level == bench::LEVEL + 1 &&
                   dataWindow(header.sender_id).contains(phase)) {
            const auto window = dataWindow(header.sender_id);
            if (!readings.canMerge(packet.readings, header.reading_count)) { ++overflow; continue; }
            for (uint8_t i = 0; i < header.reading_count; ++i) readings.add(packet.readings[i]);
            // Sin presupuesto de ACK, el hijo reintentara; se deduplica su muestra congelada.
            const int64_t deadline = min(bench::clock.deadline(window.end), event.atUs + 2000);
            ackChild(header.sender_id, deadline);
        } else if (header.msg_type == FIRE_ALERT && header.level == bench::LEVEL + 1 &&
                   receiverListen(header.level).contains(phase)) {
            alerts.add(packet.readings[0], bench::retainedMillis()); // conserva exactamente 12 bytes
        }
    }
}

static void transmitCascade() {
    if (!bench::clock.telemetry || frozenParent == 255 || acknowledged || exhausted) return;
    const Window window = dataWindow(bench::SELF_ID);
    const uint32_t phase = bench::clock.phase();
    if (!window.contains(phase)) return;
    const int64_t now = esp_timer_get_time();
    if (waiting && now < attemptUs + ATTEMPT_MS * 1000) return;
    if (waiting) { waiting = false; ++parents.failedAttempts; }
    if (attempts == MAX_ATTEMPTS) { exhausted = true; return; }
    // Intento completo DATA<=3 + ACK wait<=2 + separacion>=1, sin invadir guards.
    if (now + ATTEMPT_MS * 1000 > bench::clock.deadline(window.end)) { ++overflow; exhausted = true; return; }
    if (!outgoingLength) {
        const PacketHeader header{PROTOCOL_MAGIC, CASCADE_DATA, bench::LEVEL, bench::SELF_ID, frozenParent, readings.count};
        outgoingLength = protocol_encode(&header, readings.readings, outgoing, sizeof(outgoing));
    }
    if (outgoingLength && bench::send(outgoing, outgoingLength, frozenParent,
                                    bench::clock.deadline(window.end), false, &attemptUs)) {
        ++attempts; waiting = true;
    }
}

static void transmitAlert() {
    if (lastAlertFrame == bench::clock.frame) return;
    const Window window = alertTx(bench::SELF_ID);
    if (!window.contains(bench::clock.phase())) return;
    auto *entry = alerts.pending(bench::retainedMillis());
    if (!entry) return;
    const PacketHeader header{PROTOCOL_MAGIC, FIRE_ALERT, bench::LEVEL, bench::SELF_ID, 255, 1};
    uint8_t bytes[18]; const size_t length = protocol_encode(&header, &entry->reading, bytes, sizeof(bytes));
    if (bench::send(bytes, length, 255, bench::clock.deadline(window.end))) {
        ++entry->transmissions; lastAlertFrame = bench::clock.frame;
    }
}

static void sampleFire() {
    const uint64_t now = bench::retainedMillis();
    if (now < nextGasSample) return;
    nextGasSample = now + 45000;
    NodeReading reading = sensors::snapshot(bench::SELF_ID);
    const bool gas = !(reading.status_flags & FLAG_GAS_INVALID) && reading.gas_smoke_ppm >= 300;
    const bool temperature = previousSampleMs && now > previousSampleMs && now - previousSampleMs <= 60000 &&
        !((reading.status_flags | previousSample.status_flags) & (1 << 2)) &&
        reading.amb_temp_x10 - previousSample.amb_temp_x10 >= 80;
    if (gas || temperature) { reading.status_flags |= FLAG_FIRE_TRIGGERED; alerts.add(reading, now); }
    previousSample = reading; previousSampleMs = now;
}

static void maintenanceProbe() {
    const uint64_t now = bench::retainedMillis();
    parents.primary = parents.best(now);
    parents.backup = parents.best(now, parents.primary);
    parents.failedAttempts = 0;
    if (now < nextProbe || parents.primary == 255) return;
    nextProbe = now + 2000 + bench::SELF_ID * 17;
    const auto reading = sensors::snapshot(bench::SELF_ID);
    const PacketHeader header{PROTOCOL_MAGIC, CASCADE_DATA, bench::LEVEL, bench::SELF_ID, parents.primary, 1};
    uint8_t bytes[18]; const size_t length = protocol_encode(&header, &reading, bytes, sizeof(bytes));
    bench::send(bytes, length, parents.primary, esp_timer_get_time() + 10000, true);
}

void setup() {
    Serial.begin(115200);
    sensors::begin(); bench::beginRadio();
    Serial.println("# VitiScan sensor: RX-only por defecto. BEACON no es reloj. Consultar README antes de habilitar TX.");
}

void loop() {
    if (bench::clock.poll()) {
        // El ultimo timeout puede vencer justo al terminar su slot, antes de otro loop.
        if (waiting && !acknowledged && esp_timer_get_time() >= attemptUs + ATTEMPT_MS * 1000) ++parents.failedAttempts;
        newFrame();
    }
    consumeRadio();
    if (bench::maintenance) maintenanceProbe();
    else if (bench::clock.valid()) { transmitCascade(); transmitAlert(); }
    const uint32_t phase = bench::clock.phase();
    if (!bench::clock.valid() || phase >= ALERT_END_MS) {
        char command[96];
        if (bench::readCommand(command, sizeof(command)) && !bench::handleMaintenance(command) &&
            strcmp(command, "FIRE") == 0 && VITISCAN_SYNTHETIC_SENSORS) {
            auto reading = sensors::snapshot(bench::SELF_ID);
            reading.gas_smoke_ppm = 450; reading.status_flags |= FLAG_FIRE_TRIGGERED;
            alerts.add(reading, bench::retainedMillis());
        }
        sensors::poll(!bench::clock.valid() || phase < 1450);
        sampleFire();
    }
    bench::idleDeepSleep(!bench::clock.valid() && parents.primary == 255 && !alerts.pending(bench::retainedMillis()));
    delayMicroseconds(100); // no delay de 1ms que se coma un mini-TX de alerta
}
