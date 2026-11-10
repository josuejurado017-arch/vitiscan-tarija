#pragma once

#include <stdint.h>

namespace pins {
constexpr uint8_t SOIL_MOISTURE_GPIO = 34; // ADC1_CHANNEL_6; solo entrada
constexpr uint8_t MQ2_ANALOG_GPIO = 35;    // ADC1_CHANNEL_7; solo entrada
constexpr uint8_t SOIL_ADC1_CHANNEL = 6;
constexpr uint8_t MQ2_ADC1_CHANNEL = 7;
constexpr uint8_t ONEWIRE_GPIO = 4;       // DS18B20, pull-up 4.7k a 3.3V
constexpr uint8_t DHT22_GPIO = 27;        // DIGITAL, nunca analogRead/ADC2
constexpr uint8_t I2C_SDA_GPIO = 21;
constexpr uint8_t I2C_SCL_GPIO = 22;
constexpr uint8_t BATTERY_I2C_ADDRESS = 0x36; // MAX17048, SOC I2C; sin divisor ADC inventado
constexpr uint8_t MQ2_HEATER_MOSFET_GPIO = 33; // salida RTC, gate logico; NO alimenta calefactor
constexpr uint8_t BENCH_SYNC_GPIO = 32;       // pulso EXTERNO 1500ms, NO byte de radio
constexpr uint8_t BENCH_TELEMETRY_GATE_GPIO = 39; // entrada externa: ciclo de telemetria habilitado
static_assert(SOIL_MOISTURE_GPIO == 34 && MQ2_ANALOG_GPIO == 35, "Solo ADC1 para sensores analogicos");
static_assert(SOIL_ADC1_CHANNEL == 6 && MQ2_ADC1_CHANNEL == 7, "ESP32 clasico ADC1");
static_assert(MQ2_HEATER_MOSFET_GPIO != SOIL_MOISTURE_GPIO &&
              MQ2_HEATER_MOSFET_GPIO != MQ2_ANALOG_GPIO, "Gate no puede ser GPIO de solo entrada");
}
