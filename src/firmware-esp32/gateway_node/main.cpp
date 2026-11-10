#include "bench_runtime.h"
#include <esp_system.h>
#include <esp_timer.h>
#include <time.h>

using namespace cascade;
static_assert(bench::SELF_ID == 0, "Gateway requiere ID 0");

struct ForwardFrame {
    uint8_t bytes[MAX_PAYLOAD_BYTES]; uint16_t length;
    char cycle[37]; int64_t receivedUtcUs; bool utcValid;
};
static ForwardFrame fifo[16];
static uint8_t fifoHead = 0, fifoCount = 0;
static ReadingSet epochReadings;
static AlertCache alertCache;
static char epochCycle[37];
static int64_t utcOffsetUs = 0;
static bool utcValid = false;
static uint32_t overflow = 0;
static uint64_t nextBeacon = 0;
static char uartLine[1024]; static size_t uartLength = 0, uartWritten = 0;

static void uuid(char output[37]) {
    uint8_t b[16]; esp_fill_random(b, sizeof(b)); b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    snprintf(output, 37, "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]);
}

static bool enqueue(const bench::Received &event, bool fire) {
    if (fifoCount == 16) { ++overflow; return false; }
    auto &item = fifo[(fifoHead + fifoCount) % 16];
    memcpy(item.bytes, event.bytes, event.length); item.length = event.length;
    if (fire) uuid(item.cycle); else memcpy(item.cycle, epochCycle, 37);
    item.receivedUtcUs = event.atUs + utcOffsetUs; item.utcValid = utcValid;
    ++fifoCount; return true;
}

static void ackData(uint8_t child, int64_t deadline, bool maintenance = false) {
    const PacketHeader header{PROTOCOL_MAGIC, ACK, 0, 0, child, 0};
    uint8_t bytes[6]; const auto size = protocol_encode(&header, nullptr, bytes, sizeof(bytes));
    bench::send(bytes, size, child, deadline, maintenance);
}

static void consume() {
    bench::Observation ignored; while (bench::observation(ignored)) {} // no padres en N0
    bench::Received event;
    while (bench::receive(event)) {
        RadioPacket packet;
        if (!protocol_decode(event.bytes, event.length, &packet)) continue;
        const auto &h = packet.header;
        if (bench::maintenance) {
            if (h.msg_type == CASCADE_DATA && h.parent_id == 0 && h.level == 1)
                ackData(h.sender_id, esp_timer_get_time() + 2000, true);
            continue; // nunca ingestamos sondeos de mantenimiento
        }
        uint32_t phase;
        if (!bench::clock.phaseAt(event.atUs, phase)) continue;
        if (h.msg_type == CASCADE_DATA && h.parent_id == 0 && h.level == 1 &&
            bench::clock.telemetry && dataWindow(h.sender_id).contains(phase)) {
            if (!epochReadings.canMerge(packet.readings, h.reading_count)) { ++overflow; continue; }
            uint8_t newReadings = 0;
            for (uint8_t i = 0; i < h.reading_count; ++i) {
                bool known = false;
                for (uint8_t j = 0; j < epochReadings.count; ++j) known |= packet.readings[i].node_id == epochReadings.readings[j].node_id;
                if (!known) ++newReadings;
            }
            // Una mezcla parcial con timestamps distintos se cuarentena, no se inventa identidad.
            if (newReadings && newReadings != h.reading_count) { ++overflow; continue; }
            if (newReadings && !enqueue(event, false)) continue;
            for (uint8_t i = 0; i < h.reading_count; ++i) epochReadings.add(packet.readings[i]);
            ackData(h.sender_id, min(bench::clock.deadline(dataWindow(h.sender_id).end), event.atUs + 2000));
        } else if (h.msg_type == FIRE_ALERT && h.level == 1 && receiverListen(1).contains(phase)) {
            bool seen = false;
            const uint64_t now = bench::retainedMillis();
            for (const auto &entry : alertCache.entries)
                if (entry.used && now >= entry.firstSeen && now - entry.firstSeen < ALERT_RETAIN_MS &&
                    memcmp(&entry.reading, &packet.readings[0], 12) == 0) seen = true;
            if (!seen && fifoCount < 16 && alertCache.add(packet.readings[0], now)) enqueue(event, true);
        }
    }
}

static void beacon() {
    const auto now = bench::retainedMillis();
    if (!bench::maintenance || now < nextBeacon) return;
    nextBeacon = now + 2000;
    const PacketHeader header{PROTOCOL_MAGIC, BEACON, 0, 0, 255, 0};
    uint8_t bytes[6]; const auto size = protocol_encode(&header, nullptr, bytes, sizeof(bytes));
    bench::send(bytes, size, 255, esp_timer_get_time() + 2000, true);
}

static void serviceUart() {
    if (uartWritten == uartLength && fifoCount) {
        const auto &item = fifo[fifoHead];
        RadioPacket packet;
        if (!protocol_decode(item.bytes, item.length, &packet)) { ++overflow; return; }
        bool synthetic = true, real = true;
        for (uint8_t i = 0; i < packet.header.reading_count; ++i) {
            synthetic &= (packet.readings[i].status_flags & FLAG_SYNTHETIC) != 0;
            real &= (packet.readings[i].status_flags & FLAG_SYNTHETIC) == 0;
        }
        char hex[493];
        for (size_t i = 0; i < item.length; ++i) snprintf(hex + 2 * i, 3, "%02x", item.bytes[i]);
        if (!item.utcValid || (!synthetic && !real)) {
            uartLength = snprintf(uartLine, sizeof(uartLine), "{\"kind\":\"quarantine\",\"error\":\"UTC_REQUIRED_OR_MIXED_MODE\",\"payload_hex\":\"%s\"}\n", hex);
        } else {
            const time_t seconds = item.receivedUtcUs / 1000000;
            tm utc{}; gmtime_r(&seconds, &utc);
            char datePart[24]{}; char timeText[40]{};
            strftime(datePart, sizeof(datePart), "%Y-%m-%dT%H:%M:%S", &utc);
            snprintf(timeText, sizeof(timeText), "%s.%06luZ", datePart,
                     static_cast<unsigned long>(item.receivedUtcUs % 1000000));
            uartLength = snprintf(uartLine, sizeof(uartLine),
                "{\"gateway_id\":\"GW-00\",\"mode\":\"%s\",\"cycle_id\":\"%s\",\"received_at\":\"%s\",\"payload_hex\":\"%s\"}\n",
                synthetic ? "simulation" : "real", item.cycle, timeText, hex);
        }
        uartWritten = 0; fifoHead = (fifoHead + 1) % 16; --fifoCount;
    }
    const size_t available = Serial.availableForWrite();
    const size_t chunk = min(available, uartLength - uartWritten);
    if (chunk) uartWritten += Serial.write(reinterpret_cast<const uint8_t *>(uartLine + uartWritten), chunk);
}

void setup() {
    Serial.begin(115200); bench::beginRadio(); uuid(epochCycle);
    Serial.println("# VitiScan Gateway: BEACON=presencia, sync externo, UTC externo requerido para puente JSONL.");
}

void loop() {
    if (bench::clock.poll()) { epochReadings.clear(); uuid(epochCycle); }
    consume(); beacon();
    if (bench::maintenance || !bench::clock.valid() || bench::clock.phase() >= ALERT_END_MS) {
        char command[96];
        if (bench::readCommand(command, sizeof(command)) && !bench::handleMaintenance(command) && strncmp(command, "UTC ", 4) == 0) {
            char *end = nullptr;
            const int64_t unixUs = strtoll(command + 4, &end, 10);
            // Canal de control UART externo, no timestamp encubierto en ESP-NOW.
            if (end && !*end && unixUs >= 1577836800000000LL && unixUs <= 4102444800000000LL) {
                utcOffsetUs = unixUs - esp_timer_get_time(); utcValid = true;
            }
        }
        serviceUart();
    }
    delayMicroseconds(100);
}
