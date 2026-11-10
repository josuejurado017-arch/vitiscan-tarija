#pragma once
#include "protocol.h"

namespace sensors {
void begin();
void poll(bool safeWindow);
NodeReading snapshot(uint8_t nodeId);
int soilRaw();
int gasRaw();
bool heaterReady();
}
