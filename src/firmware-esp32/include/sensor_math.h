#pragma once
#include <stdint.h>

namespace sensors {
constexpr bool soilPercent(int raw, int dry, int wet, uint16_t &result) {
    if (raw < 0 || raw > 4095 || dry < 0 || dry > 4095 || wet < 0 || wet > 4095 || dry == wet) return false;
    const int value = (raw - dry) * 10000 / (wet - dry);
    result = uint16_t(value < 0 ? 0 : value > 10000 ? 10000 : value);
    return true;
}
}
