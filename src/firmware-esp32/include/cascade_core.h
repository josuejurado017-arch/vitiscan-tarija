#pragma once

#include "protocol.h"

namespace cascade {
constexpr bool sameReading(const NodeReading &a, const NodeReading &b) {
    return a.node_id == b.node_id && a.soil_temp_x10 == b.soil_temp_x10 &&
        a.soil_moisture == b.soil_moisture && a.amb_temp_x10 == b.amb_temp_x10 &&
        a.amb_humidity == b.amb_humidity && a.gas_smoke_ppm == b.gas_smoke_ppm &&
        a.battery_pct == b.battery_pct && a.status_flags == b.status_flags;
}
constexpr uint32_t SUPERFRAME_MS = 1500;
constexpr uint32_t LEVEL_MS = 300;
constexpr uint32_t CASCADE_END_MS = 1200;
constexpr uint32_t ALERT_END_MS = 1420;
constexpr uint32_t ALERT_LISTEN_MS = 35;
constexpr uint32_t ALERT_ROUND_MS = 55;
constexpr uint32_t SUBSLOT_MS = 54;
constexpr uint32_t ACTIVE_MS = 39;
constexpr uint32_t ATTEMPT_MS = 6;
constexpr uint32_t MAX_ATTEMPTS = 3;
constexpr uint32_t OBSERVATION_MS = 60000;
constexpr uint32_t ALERT_RETAIN_MS = 120000;
constexpr uint32_t ALERT_HORIZON_MS = 6000;

struct Window {
    uint32_t begin, end;
    constexpr bool contains(uint32_t value) const { return begin <= value && value < end; }
    constexpr bool fits(uint32_t value, uint32_t budget) const {
        return contains(value) && budget <= end - value;
    }
};

constexpr uint8_t branch(uint8_t id) { return (id - 1) % 5; }
constexpr Window dataWindow(uint8_t id) {
    return {uint32_t((4 - protocol_level(id)) * LEVEL_MS + 15 + branch(id) * SUBSLOT_MS),
            uint32_t((4 - protocol_level(id)) * LEVEL_MS + 15 + branch(id) * SUBSLOT_MS + ACTIVE_MS)};
}
constexpr uint32_t alertRound(uint8_t level) { return CASCADE_END_MS + (4 - level) * ALERT_ROUND_MS; }
constexpr Window senderListen(uint8_t level) { return {alertRound(level), alertRound(level) + ALERT_LISTEN_MS}; }
constexpr Window receiverListen(uint8_t childLevel) { return {alertRound(childLevel) + 5, alertRound(childLevel) + 40}; }
constexpr Window alertTx(uint8_t id) {
    return {alertRound(protocol_level(id)) + 35 + branch(id), alertRound(protocol_level(id)) + 36 + branch(id)};
}

constexpr uint32_t txReservationUs(uint8_t type) { return type == CASCADE_DATA ? 6000 : 500; }
constexpr uint32_t txAirtimeUs(uint8_t type) { return type == CASCADE_DATA ? 3000 : 1000; }
constexpr bool canStartTx(uint8_t type, int64_t now, int64_t deadline) {
    return deadline >= now && deadline - now >= txReservationUs(type);
}

struct ReadingSet {
    NodeReading readings[MAX_READINGS]{};
    uint8_t count = 0;
    uint32_t overflow = 0;
    constexpr void clear() { count = 0; overflow = 0; }
    constexpr bool add(const NodeReading &reading) {
        for (uint8_t i = 0; i < count; ++i) {
            if (readings[i].node_id == reading.node_id) return sameReading(readings[i], reading);
        }
        if (count == MAX_READINGS) { overflow |= uint32_t(1) << (reading.node_id - 1); return false; }
        readings[count++] = reading;
        return true;
    }
    constexpr bool canMerge(const NodeReading *incoming, uint8_t size) const {
        ReadingSet trial = *this;
        for (uint8_t i = 0; i < size; ++i) if (!trial.add(incoming[i])) return false;
        return true;
    }
};

struct ParentTable {
    struct Seen { int8_t rssi = -127; uint64_t at = 0; bool valid = false; } seen[21];
    uint8_t primary = 255, backup = 255;
    uint8_t failedAttempts = 0;
    constexpr void observe(uint8_t self, uint8_t candidate, int8_t rssi, uint64_t now) {
        if (candidate <= 20 && rssi >= -85 && rssi <= 0 && protocol_level(candidate) + 1 == protocol_level(self))
            seen[candidate] = {rssi, now, true};
    }
    constexpr bool fresh(uint8_t candidate, uint64_t now) const {
        return candidate <= 20 && seen[candidate].valid && now >= seen[candidate].at && now - seen[candidate].at <= OBSERVATION_MS;
    }
    constexpr uint8_t best(uint64_t now, uint8_t excluded = 255) const {
        uint8_t result = 255;
        for (uint8_t id = 0; id <= 20; ++id)
            if (id != excluded && fresh(id, now) && (result == 255 || seen[id].rssi > seen[result].rssi)) result = id;
        return result; // empate: menor ID, orden ascendente
    }
    constexpr void epochBoundary(uint64_t now) {
        const uint8_t failed = failedAttempts >= MAX_ATTEMPTS ? primary : uint8_t(255);
        // Una asociacion no caduca por silencio entre telemetrias de 900 s.
        // La frescura de 60 s se exige al ELEGIR un candidato, no para expulsar
        // un padre conocido al que todavia no se le ha perdido ningun ACK.
        if (failed != 255) primary = best(now, failed);
        if (primary == 255) primary = best(now, failed);
        backup = best(now, primary);
        failedAttempts = 0;
    }
};

struct AlertCache {
    struct Entry { NodeReading reading{}; uint64_t firstSeen = 0; uint8_t transmissions = 0; bool used = false; } entries[20];
    uint32_t overflow = 0;
    constexpr bool add(const NodeReading &reading, uint64_t now) {
        Entry *empty = nullptr;
        for (auto &entry : entries) {
            if (entry.used && now >= entry.firstSeen && now - entry.firstSeen >= ALERT_RETAIN_MS) entry.used = false;
            if (entry.used && sameReading(entry.reading, reading)) return true; // no reiniciar horizonte
            if (!entry.used && !empty) empty = &entry;
        }
        if (!empty) { ++overflow; return false; }
        *empty = {reading, now, 0, true}; return true;
    }
    constexpr Entry *pending(uint64_t now) {
        Entry *result = nullptr;
        for (auto &entry : entries)
            if (entry.used && now >= entry.firstSeen && now - entry.firstSeen < ALERT_HORIZON_MS && entry.transmissions < 3 &&
                (!result || entry.reading.node_id < result->reading.node_id)) result = &entry;
        return result;
    }
};

static_assert(SUPERFRAME_MS == 1500 && ALERT_LISTEN_MS == 35, "ADR-001");
static_assert(4 * LEVEL_MS == CASCADE_END_MS, "Cascada 1200ms");
static_assert(CASCADE_END_MS + 4 * ALERT_ROUND_MS == ALERT_END_MS, "Alertas 1200..1420");
}
