/*
 * RC Yer Verici - Arduino Nano + NRF24L01+
 * Steam Deck'ten USB seri ile komut alir
 * NRF24L01+ ile uca iletir
 * Ucaktan telemetri alir, seri ile Steam Deck'e gonderir
 */

#include <SPI.h>
#include <nRF24L01.h>
#include <RF24.h>

// === Pin Tanimlari ===
#define CE_PIN   9
#define CSN_PIN  10

// === NRF24L01+ ===
RF24 radio(CE_PIN, CSN_PIN);
const byte address[6] = "RC01";

// === Paket Tanimlari ===
struct ControlPacket {
  uint8_t header;        // 0xC0
  uint16_t aileron;
  uint16_t elevator;
  uint16_t rudder;
  uint16_t throttle;
} __attribute__((packed));

struct TelemetryPacket {
  uint8_t header;        // 0xAA
  uint16_t battery_mv;
  uint8_t rssi;
  uint8_t flags;
  uint8_t crc;
} __attribute__((packed));

// === Seri Protokol ===
// Gonderilen komut formati (11 byte):
// [0]: 0xC0 (header)
// [1-2]: Aileron (big-endian uint16)
// [3-4]: Elevator
// [5-6]: Rudder
// [7-8]: Throttle
// [9]: CRC (XOR tum byte'lar header dahil)
// [10]: 0x0A (newline terminator)

const uint8_t CMD_PACKET_SIZE = 11;
const uint8_t CMD_HEADER = 0xC0;
const uint8_t CMD_TERMINATOR = 0x0A;

// Alinan seri buffer
uint8_t serialBuffer[CMD_PACKET_SIZE];
uint8_t serialIndex = 0;

// === Degiskenler ===
unsigned long lastTxTime = 0;
unsigned long txCount = 0;
unsigned long lastRxTime = 0;
unsigned long rxCount = 0;
bool planeConnected = false;

const unsigned long TX_INTERVAL = 20; // 50Hz gonderim
const unsigned long PLANE_TIMEOUT = 1000;

void setup() {
  Serial.begin(115200);

  // NRF24L01+ baslatma
  radio.begin();
  radio.setPALevel(RF24_PA_HIGH);
  radio.setDataRate(RF24_250KBPS);
  radio.setChannel(108);
  radio.setPayloadSize(sizeof(ControlPacket));
  radio.openWritingPipe(address);
  radio.stopListening();  // Varsayilan TX modu

  delay(100);

  Serial.println(F("VERICI HAZIR"));
  Serial.println(F("FORMAT: [0xC0][CH1_H][CH1_L][CH2_H][CH2_L][CH3_H][CH3_L][CH4_H][CH4_L][CRC][0x0A]"));
}

void loop() {
  unsigned long now = millis();

  // --- Seri Komut Alimi ---
  readSerialCommands();

  // --- Telemetri Alimi ---
  checkTelemetry();

  // --- Baglanti Durumu ---
  if (now - lastRxTime > PLANE_TIMEOUT && planeConnected) {
    planeConnected = false;
    Serial.println(F("TEL:DISCONNECTED"));
  }
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    uint8_t b = Serial.read();

    // Header bekle
    if (serialIndex == 0 && b != CMD_HEADER) {
      continue;
    }

    serialBuffer[serialIndex] = b;
    serialIndex++;

    // Tam paket alindi mi?
    if (serialIndex >= CMD_PACKET_SIZE) {
      serialIndex = 0;

      // Terminator kontrol
      if (serialBuffer[CMD_PACKET_SIZE - 1] != CMD_TERMINATOR) {
        continue;
      }

      // CRC kontrol
      uint8_t calcCrc = 0;
      for (uint8_t i = 0; i < CMD_PACKET_SIZE - 2; i++) {
        calcCrc ^= serialBuffer[i];
      }
      if (calcCrc != serialBuffer[CMD_PACKET_SIZE - 2]) {
        continue;
      }

      // Paketi olustur
      ControlPacket pkt;
      pkt.header = 0xC0;
      pkt.aileron  = ((uint16_t)serialBuffer[1] << 8) | serialBuffer[2];
      pkt.elevator = ((uint16_t)serialBuffer[3] << 8) | serialBuffer[4];
      pkt.rudder   = ((uint16_t)serialBuffer[5] << 8) | serialBuffer[6];
      pkt.throttle = ((uint16_t)serialBuffer[7] << 8) | serialBuffer[8];

      // NRF ile gonder
      radio.write(&pkt, sizeof(pkt));
      txCount++;
      lastTxTime = millis();
    }
  }
}

void checkTelemetry() {
  radio.startListening();
  delayMicroseconds(130);

  if (radio.available()) {
    TelemetryPacket tel;
    radio.read(&tel, sizeof(tel));

    if (tel.header == 0xAA) {
      // CRC dogrula
      uint8_t calcCrc = tel.header ^ (uint8_t)(tel.battery_mv & 0xFF)
                        ^ (uint8_t)(tel.battery_mv >> 8) ^ tel.rssi ^ tel.flags;
      if (calcCrc == tel.crc) {
        lastRxTime = millis();
        planeConnected = true;
        rxCount++;

        // Seri uzerinden Steam Deck'e gonder
        // Format: TEL:battery_mv,rssi,flags\n
        Serial.print(F("TEL:"));
        Serial.print(tel.battery_mv);
        Serial.print(',');
        Serial.print(tel.rssi);
        Serial.print(',');
        Serial.println(tel.flags);
      }
    }
  }

  radio.stopListening();
}
