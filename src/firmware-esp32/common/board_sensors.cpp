#include "board_sensors.h"
#include "bench_runtime.h"
#include "hardware_pins.h"
#include "sensor_math.h"

#include <DallasTemperature.h>
#include <DHT.h>
#include <OneWire.h>
#include <Wire.h>
#include <driver/adc.h>
#include <driver/gpio.h>
#include <math.h>

#ifndef VITISCAN_MQ2_HEATER_ENABLED
#define VITISCAN_MQ2_HEATER_ENABLED 0
#endif
#ifndef VITISCAN_SOIL_DRY_ADC
#define VITISCAN_SOIL_DRY_ADC -1
#endif
#ifndef VITISCAN_SOIL_WET_ADC
#define VITISCAN_SOIL_WET_ADC -1
#endif

namespace sensors {
static OneWire oneWire(pins::ONEWIRE_GPIO);
static DallasTemperature soilTemperature(&oneWire);
static DHT ambient(pins::DHT22_GPIO, DHT22);
static NodeReading latest{};
static uint64_t nextSample = 0, conversionReady = 0;
static int rawSoil = 0, rawGas = 0;
static uint64_t heaterStartedMs = 0;
constexpr uint64_t MQ2_WARMUP_MIN_MS = 180000; // minimo ilustrativo, no sustituye acondicionamiento/calibracion

void begin() {
    gpio_deep_sleep_hold_dis(); gpio_hold_dis(gpio_num_t(pins::MQ2_HEATER_MOSFET_GPIO));
    pinMode(pins::MQ2_HEATER_MOSFET_GPIO, OUTPUT);
    digitalWrite(pins::MQ2_HEATER_MOSFET_GPIO, VITISCAN_MQ2_HEATER_ENABLED ? HIGH : LOW);
    heaterStartedMs = bench::retainedMillis(); // conservador: reiniciar warmup en cada arranque
    adc1_config_width(ADC_WIDTH_BIT_12);
    adc1_config_channel_atten(ADC1_CHANNEL_6, ADC_ATTEN_DB_12);
    adc1_config_channel_atten(ADC1_CHANNEL_7, ADC_ATTEN_DB_12);
    Wire.begin(pins::I2C_SDA_GPIO, pins::I2C_SCL_GPIO); Wire.setTimeOut(5);
    soilTemperature.begin(); soilTemperature.setWaitForConversion(false);
    ambient.begin(); latest.status_flags = 0x3F; // canales desconocidos con placeholder 0
}

void poll(bool safeWindow) {
    if (!safeWindow || bench::LEVEL == 0 || VITISCAN_SYNTHETIC_SENSORS) return;
    const uint64_t now = bench::retainedMillis();
    if (conversionReady && now >= conversionReady) {
        const float temperature = soilTemperature.getTempCByIndex(0);
        if (isfinite(temperature) && temperature != DEVICE_DISCONNECTED_C && temperature >= -55 && temperature <= 125) {
            latest.soil_temp_x10 = lroundf(temperature * 10); latest.status_flags &= ~(1 << 0);
        }
        conversionReady = 0;
    }
    if (now < nextSample) return;
    nextSample = now + 45000;
    latest = {}; latest.status_flags = 0x3F;
    rawSoil = adc1_get_raw(ADC1_CHANNEL_6); rawGas = adc1_get_raw(ADC1_CHANNEL_7);
    uint16_t moisture = 0;
    if (soilPercent(rawSoil, VITISCAN_SOIL_DRY_ADC, VITISCAN_SOIL_WET_ADC, moisture)) {
        latest.soil_moisture = moisture; latest.status_flags &= ~(1 << 1);
    }
    const float t = ambient.readTemperature(), h = ambient.readHumidity();
    if (isfinite(t) && t >= -40 && t <= 80) { latest.amb_temp_x10 = lroundf(t * 10); latest.status_flags &= ~(1 << 2); }
    if (isfinite(h) && h >= 0 && h <= 100) { latest.amb_humidity = lroundf(h); latest.status_flags &= ~(1 << 3); }
    Wire.beginTransmission(pins::BATTERY_I2C_ADDRESS); Wire.write(0x04);
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom(pins::BATTERY_I2C_ADDRESS, uint8_t(2)) == 2) {
        const unsigned whole = Wire.read(), fraction = Wire.read();
        const float soc = whole + fraction / 256.0f;
        if (soc <= 100) { latest.battery_pct = lroundf(soc); latest.status_flags &= ~FLAG_BATTERY_INVALID; }
    }
    // Incluso tras 180s de calentamiento, ADC MQ-2 NO se convierte a ppm reales.
    latest.gas_smoke_ppm = 0; latest.status_flags |= FLAG_GAS_INVALID;
    soilTemperature.requestTemperatures(); conversionReady = now + 750;
}

NodeReading snapshot(uint8_t id) {
    if (VITISCAN_SYNTHETIC_SENSORS) {
        return NodeReading{id, int16_t(215 + id - 1), uint16_t(4230 - 45 * (id - 1)),
                           287, 62, uint16_t(120 + (id - 1) * 3), 95, FLAG_SYNTHETIC};
    }
    NodeReading result = latest; result.node_id = id; return result;
}
int soilRaw() { return rawSoil; }
int gasRaw() { return rawGas; }
bool heaterReady() {
    const uint64_t now = bench::retainedMillis();
    return VITISCAN_MQ2_HEATER_ENABLED && now >= heaterStartedMs && now - heaterStartedMs >= MQ2_WARMUP_MIN_MS;
}
}
