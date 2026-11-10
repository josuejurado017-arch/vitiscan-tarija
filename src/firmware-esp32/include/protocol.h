#ifndef VITISCAN_PROTOCOL_H
#define VITISCAN_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* ESP32 clasico y los fixtures usan little-endian. packed NO convierte endian. */
#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "Serializacion directa requiere little-endian; no reinterpretar structs big-endian"
#endif

#ifdef __cplusplus
#define PROTOCOL_CONSTEXPR constexpr
extern "C" {
#else
#define PROTOCOL_CONSTEXPR
#define static_assert _Static_assert
#endif

enum MessageType {
    BEACON = 0x01,
    CASCADE_DATA = 0x02,
    ACK = 0x03,
    FIRE_ALERT = 0xFF
};

enum {
    PROTOCOL_MAGIC = 0xA5,
    HEADER_SIZE = 6,
    READING_SIZE = 12,
    MAX_READINGS = 20,
    MAX_PAYLOAD_BYTES = 246,
    SYNTHETIC_GAS_MAX = 1000, /* perfil demo Python; contrato congelado conserva 500 */
    FLAG_GAS_INVALID = 1 << 4,
    FLAG_BATTERY_INVALID = 1 << 5,
    FLAG_FIRE_TRIGGERED = 1 << 6,
    FLAG_SYNTHETIC = 1 << 7
};

typedef struct __attribute__((packed)) {
    uint8_t magic;
    uint8_t msg_type;
    uint8_t level;
    uint8_t sender_id;
    uint8_t parent_id;
    uint8_t reading_count;
} PacketHeader;

typedef struct __attribute__((packed)) {
    uint8_t node_id;
    int16_t soil_temp_x10;
    uint16_t soil_moisture;
    int16_t amb_temp_x10;
    uint8_t amb_humidity;
    uint16_t gas_smoke_ppm;
    uint8_t battery_pct;
    uint8_t status_flags;
} NodeReading;

typedef struct __attribute__((packed)) {
    PacketHeader header;
    NodeReading readings[MAX_READINGS];
} RadioPacket;

static_assert(sizeof(PacketHeader) == 6, "PacketHeader debe ser exactamente 6B");
static_assert(sizeof(NodeReading) == 12, "NodeReading debe ser exactamente 12B");
static_assert(sizeof(RadioPacket) == MAX_PAYLOAD_BYTES, "Payload maximo 246B");
static_assert(offsetof(PacketHeader, reading_count) == 5, "Offset count");
static_assert(offsetof(NodeReading, node_id) == 0, "Offset node_id");
static_assert(offsetof(NodeReading, soil_temp_x10) == 1, "Offset soil_temp_x10");
static_assert(offsetof(NodeReading, soil_moisture) == 3, "Offset soil_moisture");
static_assert(offsetof(NodeReading, amb_temp_x10) == 5, "Offset amb_temp_x10");
static_assert(offsetof(NodeReading, amb_humidity) == 7, "Offset amb_humidity");
static_assert(offsetof(NodeReading, gas_smoke_ppm) == 8, "Offset gas_smoke_ppm");
static_assert(offsetof(NodeReading, battery_pct) == 10, "Offset battery_pct");
static_assert(offsetof(NodeReading, status_flags) == 11, "Offset status_flags");

static inline PROTOCOL_CONSTEXPR uint8_t protocol_level(uint8_t id) {
    return id == 0 ? 0 : (id <= 20 ? (uint8_t)((id - 1) / 5 + 1) : 255);
}

static inline size_t protocol_size(uint8_t count) {
    return HEADER_SIZE + (size_t)READING_SIZE * count;
}

static inline PROTOCOL_CONSTEXPR int protocol_valid_header(const PacketHeader *h) {
    if (!h || h->magic != PROTOCOL_MAGIC || h->sender_id > 20 ||
        h->level != protocol_level(h->sender_id) || h->reading_count > MAX_READINGS) return 0;
    switch (h->msg_type) {
        case BEACON:
            return h->sender_id == 0 && h->level == 0 && h->parent_id == 255 && h->reading_count == 0;
        case CASCADE_DATA:
            return h->sender_id != 0 && h->reading_count >= 1 &&
                protocol_level(h->parent_id) == h->level - 1;
        case ACK:
            return h->reading_count == 0 && protocol_level(h->parent_id) == h->level + 1;
        case FIRE_ALERT:
            return h->sender_id != 0 && h->parent_id == 255 && h->reading_count == 1;
        default: return 0;
    }
}

static inline PROTOCOL_CONSTEXPR int protocol_valid_reading(const NodeReading *r) {
    if (!r || r->node_id < 1 || r->node_id > 20 || r->soil_temp_x10 < -550 ||
        r->soil_temp_x10 > 1250 || r->soil_moisture > 10000 || r->amb_temp_x10 < -400 ||
        r->amb_temp_x10 > 800 || r->amb_humidity > 100 || r->gas_smoke_ppm > SYNTHETIC_GAS_MAX ||
        r->battery_pct > 100) return 0;
    const int32_t channels[] = {r->soil_temp_x10, r->soil_moisture, r->amb_temp_x10,
                               r->amb_humidity, r->gas_smoke_ppm, r->battery_pct};
    for (uint8_t bit = 0; bit < 6; ++bit) {
        if ((r->status_flags & (1 << bit)) && channels[bit] != 0) return 0;
    }
    return (r->status_flags & FLAG_SYNTHETIC) || (r->status_flags & FLAG_GAS_INVALID);
}

/* memcpy evita accesos desalineados a los campos int16_t de una lectura packed. */
static inline int protocol_decode(const uint8_t *bytes, size_t length, RadioPacket *out) {
    if (!bytes || !out || length < HEADER_SIZE || length > MAX_PAYLOAD_BYTES) return 0;
    PacketHeader h;
    memcpy(&h, bytes, HEADER_SIZE);
    if (!protocol_valid_header(&h) || length != protocol_size(h.reading_count)) return 0;
    memset(out, 0, sizeof(*out));
    memcpy(out, bytes, length);
    uint32_t seen = 0;
    for (uint8_t i = 0; i < h.reading_count; ++i) {
        const NodeReading *r = &out->readings[i];
        if (!protocol_valid_reading(r)) return 0;
        const uint32_t mask = (uint32_t)1 << (r->node_id - 1);
        if (seen & mask) return 0;
        seen |= mask;
    }
    return h.msg_type != FIRE_ALERT || (out->readings[0].status_flags & FLAG_FIRE_TRIGGERED);
}

static inline size_t protocol_encode(const PacketHeader *h, const NodeReading *readings,
                                     uint8_t *out, size_t capacity) {
    if (!h || !out || !protocol_valid_header(h) || (h->reading_count && !readings)) return 0;
    const size_t length = protocol_size(h->reading_count);
    if (length > capacity) return 0;
    memcpy(out, h, HEADER_SIZE);
    if (readings && h->reading_count) memcpy(out + HEADER_SIZE, readings, length - HEADER_SIZE);
    RadioPacket verified;
    return protocol_decode(out, length, &verified) ? length : 0;
}

#ifdef __cplusplus
}
#endif
#endif
