#pragma once

#include <Arduino.h>
#include "cascade_core.h"

#ifndef VITISCAN_NODE_ID
#define VITISCAN_NODE_ID 16
#endif
#ifndef VITISCAN_BENCH_EXTERNAL_SYNC
#define VITISCAN_BENCH_EXTERNAL_SYNC 0
#endif
#ifndef VITISCAN_RF_TIMING_VALIDATED
#define VITISCAN_RF_TIMING_VALIDATED 0
#endif
#ifndef VITISCAN_SYNTHETIC_SENSORS
#define VITISCAN_SYNTHETIC_SENSORS 0
#endif
#ifndef VITISCAN_ENABLE_DEEP_SLEEP
#define VITISCAN_ENABLE_DEEP_SLEEP 0
#endif

namespace bench {
constexpr uint8_t SELF_ID = VITISCAN_NODE_ID;
constexpr uint8_t LEVEL = protocol_level(SELF_ID);
constexpr uint8_t CHANNEL = 6;
static_assert(SELF_ID <= 20, "ID provisionado fuera de topologia");

struct Received {
    uint8_t bytes[MAX_PAYLOAD_BYTES];
    uint16_t length;
    int64_t atUs;
};
struct Observation { uint8_t id; int8_t rssi; uint64_t atMs; };

class Clock {
public:
    void begin();
    bool poll(); // true una vez por pulso nuevo, dos pulsos coherentes para lock
    bool valid() const;
    uint32_t phase() const;
    bool phaseAt(int64_t atUs, uint32_t &phase) const;
    int64_t deadline(uint32_t phaseMs) const { return startUs_ + int64_t(phaseMs) * 1000; }
    bool telemetry = false;
    uint32_t frame = 0;
private:
    int64_t startUs_ = 0;
    uint32_t pulses_ = 0;
    bool locked_ = false;
};

extern Clock clock;
extern bool maintenance;
extern volatile uint32_t rxOverflow;
extern volatile uint32_t txOverrun;

uint64_t retainedMillis();
void beginRadio();
bool receive(Received &event);
bool observation(Observation &event);
bool send(const uint8_t *payload, size_t length, uint8_t peer, int64_t deadlineUs,
          bool maintenanceTx = false, int64_t *startedUs = nullptr);
void macFor(uint8_t id, uint8_t out[6]);
bool readCommand(char *line, size_t capacity);
bool handleMaintenance(const char *line);
bool radioBusy();
void idleDeepSleep(bool safeToLoseSync);
}
