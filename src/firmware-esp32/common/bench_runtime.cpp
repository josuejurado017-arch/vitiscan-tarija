#include "bench_runtime.h"
#include "hardware_pins.h"

#include <WiFi.h>
#include <driver/rtc_io.h>
#include <esp_now.h>
#include <esp_sleep.h>
#include <esp_timer.h>
#include <esp_wifi.h>
#include <sys/time.h>

namespace bench {
Clock clock;
bool maintenance = false;
volatile uint32_t rxOverflow = 0, txOverrun = 0;
static QueueHandle_t rxQueue, observations;
static volatile int64_t pulseUs = 0;
static volatile uint32_t pulseCounter = 0;
static portMUX_TYPE pulseMux = portMUX_INITIALIZER_UNLOCKED;
static portMUX_TYPE txMux = portMUX_INITIALIZER_UNLOCKED;
static bool txPending = false, timingFault = false;
static int64_t txDeadlineUs = 0;

uint64_t retainedMillis() {
    // RTC continua durante deep sleep. No se ajusta con SNTP/UTC en los nodos.
    timeval now{}; gettimeofday(&now, nullptr);
    return uint64_t(now.tv_sec) * 1000 + now.tv_usec / 1000;
}

static void IRAM_ATTR syncPulse() {
    const int64_t now = esp_timer_get_time();
    portENTER_CRITICAL_ISR(&pulseMux);
    pulseUs = now; ++pulseCounter;
    portEXIT_CRITICAL_ISR(&pulseMux);
}

void Clock::begin() {
    pinMode(pins::BENCH_SYNC_GPIO, INPUT_PULLDOWN);
    pinMode(pins::BENCH_TELEMETRY_GATE_GPIO, INPUT); // GPIO39 requiere pull-down externo
    if (VITISCAN_BENCH_EXTERNAL_SYNC) attachInterrupt(pins::BENCH_SYNC_GPIO, syncPulse, RISING);
}

bool Clock::poll() {
    int64_t edge; uint32_t pulses;
    portENTER_CRITICAL(&pulseMux); edge = pulseUs; pulses = pulseCounter; portEXIT_CRITICAL(&pulseMux);
    if (pulses == pulses_) return false;
    const int64_t interval = edge - startUs_;
    locked_ = startUs_ > 0 && pulses == pulses_ + 1 && llabs(interval - 1500000) <= 200;
    startUs_ = edge; pulses_ = pulses; ++frame;
    telemetry = digitalRead(pins::BENCH_TELEMETRY_GATE_GPIO) == HIGH;
    return true;
}

bool Clock::valid() const {
    const int64_t elapsed = esp_timer_get_time() - startUs_;
    return VITISCAN_BENCH_EXTERNAL_SYNC && locked_ && elapsed >= 0 && elapsed < 1500000;
}
uint32_t Clock::phase() const { return valid() ? uint32_t((esp_timer_get_time() - startUs_) / 1000) : 1500; }
bool Clock::phaseAt(int64_t atUs, uint32_t &phaseMs) const {
    if (!valid() || atUs < startUs_ || atUs >= startUs_ + 1500000) return false;
    phaseMs = uint32_t((atUs - startUs_) / 1000); return true;
}

void macFor(uint8_t id, uint8_t out[6]) {
    const uint8_t prefix[] = {0x02, 0x56, 0x54, 0x00, 0x00, id};
    memcpy(out, prefix, 6); // MAC locales de laboratorio, provision externo MAC-ID
}

static bool validSource(const uint8_t *mac, uint8_t id) {
    uint8_t expected[6]; macFor(id, expected); return memcmp(expected, mac, 6) == 0;
}

static void onReceive(const uint8_t *mac, const uint8_t *data, int length) {
    if (length < HEADER_SIZE || length > MAX_PAYLOAD_BYTES) return;
    PacketHeader header; memcpy(&header, data, sizeof(header));
    if (header.sender_id > 20 || !validSource(mac, header.sender_id)) return;
    Received event{}; event.length = length; event.atUs = esp_timer_get_time();
    memcpy(event.bytes, data, length);
    if (xQueueSend(rxQueue, &event, 0) != pdTRUE) ++rxOverflow;
}

static void onSent(const uint8_t *, esp_now_send_status_t) {
    // Callback de enlace NO significa ACK de aplicacion ni commit del backend.
    const int64_t now = esp_timer_get_time();
    portENTER_CRITICAL(&txMux);
    if (txPending && now > txDeadlineUs) { ++txOverrun; timingFault = true; }
    txPending = false;
    portEXIT_CRITICAL(&txMux);
}

static void onPromiscuous(void *buffer, wifi_promiscuous_pkt_type_t type) {
    // Parser acotado del vendor action ESP-NOW v1 sin cifrar, para RSSI real
    // de DATA/ACK ajenos observados. Nunca ingiere ni ACKea desde sniffer.
    if (type != WIFI_PKT_MGMT) return;
    const auto *packet = static_cast<wifi_promiscuous_pkt_t *>(buffer);
    const uint8_t *p = packet->payload;
    if (packet->rx_ctrl.sig_len < 45 || (p[0] & 0xFC) != 0xD0 || p[24] != 127 ||
        p[25] != 0x18 || p[26] != 0xFE || p[27] != 0x34 || p[32] != 221 ||
        p[34] != 0x18 || p[35] != 0xFE || p[36] != 0x34 || p[37] != 4 || (p[38] & 0x0F) != 1) return;
    const unsigned length = p[33];
    if (length < 5 + HEADER_SIZE || length > 5 + MAX_PAYLOAD_BYTES ||
        packet->rx_ctrl.sig_len < 34 + length) return;
    RadioPacket decoded;
    if (!protocol_decode(p + 39, length - 5, &decoded) || !validSource(p + 10, decoded.header.sender_id)) return;
    Observation event{decoded.header.sender_id, int8_t(packet->rx_ctrl.rssi), retainedMillis()};
    xQueueSend(observations, &event, 0);
}

void beginRadio() {
    rxQueue = xQueueCreate(24, sizeof(Received)); observations = xQueueCreate(32, sizeof(Observation));
    if (!rxQueue || !observations) abort();
    WiFi.mode(WIFI_STA); WiFi.disconnect();
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE));
    uint8_t own[6]; macFor(SELF_ID, own);
    ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, own));
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_wifi_config_espnow_rate(WIFI_IF_STA, WIFI_PHY_RATE_6M));
    ESP_ERROR_CHECK(esp_now_register_recv_cb(onReceive));
    ESP_ERROR_CHECK(esp_now_register_send_cb(onSent));
    for (uint8_t id = 0; id <= 21; ++id) {
        if (id != 21 && (id == SELF_ID ||
            (protocol_level(id) + 1 != LEVEL && protocol_level(id) != LEVEL + 1))) continue;
        esp_now_peer_info_t peer{};
        if (id == 21) memset(peer.peer_addr, 0xFF, 6); else macFor(id, peer.peer_addr);
        peer.channel = CHANNEL; peer.ifidx = WIFI_IF_STA; peer.encrypt = false;
        ESP_ERROR_CHECK(esp_now_add_peer(&peer));
    }
    wifi_promiscuous_filter_t filter{WIFI_PROMIS_FILTER_MASK_MGMT};
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&filter));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(onPromiscuous));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    clock.begin();
}

bool receive(Received &event) { return xQueueReceive(rxQueue, &event, 0) == pdTRUE; }
bool observation(Observation &event) { return xQueueReceive(observations, &event, 0) == pdTRUE; }
bool radioBusy() {
    portENTER_CRITICAL(&txMux); const bool busy = txPending; portEXIT_CRITICAL(&txMux); return busy;
}

bool send(const uint8_t *payload, size_t length, uint8_t peer, int64_t deadlineUs,
          bool maintenanceTx, int64_t *startedUs) {
    if (!VITISCAN_RF_TIMING_VALIDATED || (!maintenanceTx && !clock.valid()) ||
        (maintenanceTx && !maintenance) || length > MAX_PAYLOAD_BYTES || length < HEADER_SIZE) return false;
    RadioPacket checked;
    if (!protocol_decode(payload, length, &checked)) return false;
    uint8_t mac[6];
    if (peer == 255) memset(mac, 0xFF, 6); else macFor(peer, mac);
    const int64_t start = esp_timer_get_time();
    if (!cascade::canStartTx(checked.header.msg_type, start, deadlineUs)) return false;
    portENTER_CRITICAL(&txMux);
    if (txPending || timingFault) { portEXIT_CRITICAL(&txMux); return false; }
    txPending = true;
    txDeadlineUs = min(deadlineUs, start + cascade::txAirtimeUs(checked.header.msg_type));
    portEXIT_CRITICAL(&txMux);
    const esp_err_t result = esp_now_send(mac, payload, length);
    if (result != ESP_OK) { portENTER_CRITICAL(&txMux); txPending = false; portEXIT_CRITICAL(&txMux); }
    if (result == ESP_OK && startedUs) *startedUs = start;
    return result == ESP_OK;
}

bool readCommand(char *line, size_t capacity) {
    static char input[96]; static size_t used = 0; static bool discard = false;
    // No bloquear esperando UART. Comandos solo se procesan fuera de slots.
    while (Serial.available()) {
        const char c = char(Serial.read());
        if (c == '\n') {
            if (!discard && used < capacity) { memcpy(line, input, used); line[used] = 0; used = 0; return true; }
            used = 0; discard = false;
        } else if (c != '\r') {
            if (used < sizeof(input) - 1) input[used++] = c; else discard = true;
        }
    }
    return false;
}

bool handleMaintenance(const char *line) {
    if (strcmp(line, "MAINT 1") == 0) { maintenance = true; return true; }
    if (strcmp(line, "MAINT 0") == 0) { maintenance = false; return true; }
    return false;
}

void idleDeepSleep(bool safeToLoseSync) {
    static const int64_t awakeSinceUs = esp_timer_get_time();
    // Permitir primero varios pulsos/descubrimiento; no crear un bucle de
    // despertar-dormir que impida adquirir dos pulsos consecutivos.
    if (VITISCAN_ENABLE_DEEP_SLEEP && safeToLoseSync && !maintenance && !radioBusy() &&
        esp_timer_get_time() - awakeSinceUs >= 5000000) {
        // No dormir un repetidor asociado que debe recibir hijos/alertas.
        // Al despertar se pierde el lock y se exigen dos pulsos externos nuevos.
        gpio_hold_en(gpio_num_t(pins::MQ2_HEATER_MOSFET_GPIO)); gpio_deep_sleep_hold_en();
        esp_sleep_enable_timer_wakeup(250000);
        esp_deep_sleep_start();
    }
}
}
