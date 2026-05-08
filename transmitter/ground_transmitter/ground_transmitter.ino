/*
 * RC Yer Verici - Arduino Nano + NRF24L01+
 * Steam Deck (Web arayuzu) ile USB seri haberlesme
 * NRF24L01+ ile uca kontrol komutu gonderir
 * Ucaktan telemetri alir, seri ile web arayuze iletir
 *
 * Seri Protokol (115200 baud):
 *   Gonderim (11 byte): [0xC0][CH1H][CH1L][CH2H][CH2L][CH3H][CH3L][CH4H][CH4L][CRC][0x0A]
 *   Telemetri: TEL:battery_mv,rssi,flags\n
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
const uint8_t CMD_PACKET_SIZE = 11;
const uint8_t CMD_HEADER = 0xC0;
const uint8_t CMD_TERMINATOR = 0x0A;

// Seri buffer
uint8_t serialBuffer[CMD_PACKET_SIZE];
uint8_t serialIndex = 0;

// === Degiskenler ===
unsigned long txCount = 0;
unsigned long rxCount = 0;
unsigned long lastRxTime = 0;
bool planeConnected = false;

// Telemetri zamanlama
unsigned long lastTelCheckTime = 0;
const unsigned long TEL_CHECK_INTERVAL = 200; // Her 200ms'de telemetri kontrol et (5Hz)

// Baglanti timeout
const unsigned long PLANE_TIMEOUT = 2000; // 2 saniye

void setup() {
  Serial.begin(115200);

  // NRF24L01+ baslatma
  radio.begin();
  radio.setPALevel(RF24_PA_HIGH);
  radio.setDataRate(RF24_250KBPS);
  radio.setChannel(108);
  radio.setPayloadSize(sizeof(ControlPacket));
  radio.openWritingPipe(address);
  radio.stopListening();

  delay(100);

  Serial.println(F("VERICI HAZIR"));
}

void loop() {
  unsigned long now = millis();

  // Seri komut alimi
  readSerialCommands();

  // Periyodik telemetri kontrolu
  if (now - lastTelCheckTime >= TEL_CHECK_INTERVAL) {
    lastTelCheckTime = now;
    checkTelemetry();
  }

  // Baglanti timeout kontrolu
  if (planeConnected && (now - lastRxTime > PLANE_TIMEOUT)) {
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

      // Kontrol paketini olustur ve gonder
      ControlPacket pkt;
      pkt.header = 0xC0;
      pkt.aileron  = ((uint16_t)serialBuffer[1] << 8) | serialBuffer[2];
      pkt.elevator = ((uint16_t)serialBuffer[3] << 8) | serialBuffer[4];
      pkt.rudder   = ((uint16_t)serialBuffer[5] << 8) | serialBuffer[6];
      pkt.throttle = ((uint16_t)serialBuffer[7] << 8) | serialBuffer[8];

      radio.write(&pkt, sizeof(pkt));
      txCount++;
    }
  }
}

void checkTelemetry() {
  // TX modundan RX moduna gec
  radio.startListening();
  delayMicroseconds(300);

  // Telemetri icin bekle (max 2ms)
  unsigned long waitStart = micros();
  bool gotData = false;

  while (micros() - waitStart < 2000) { // Max 2000us = 2ms bekle
    if (radio.available()) {
      gotData = true;
      break;
    }
  }

  if (gotData) {
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

        // Web arayuze seri ile gonder
        Serial.print(F("TEL:"));
        Serial.print(tel.battery_mv);
        Serial.print(',');
        Serial.print(tel.rssi);
        Serial.print(',');
        Serial.println(tel.flags);
      }
    }
  }

  // RX modundan TX moduna don
  radio.stopListening();
  delayMicroseconds(150); // TX moduna gecis icin kisa bekleme
}
