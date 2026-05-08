/*
 * RC Ucak Alici - Arduino Nano + NRF24L01+
 * Kanallar: Aileron(D3), Elevator(D5), Rudder(D6), Throttle(D7)
 * Telemetri: 3S Pil voltaji(A0) + sinyal gucu (RSSI)
 * Pil: 3S LiPo 11.1V (9.9V - 12.6V)
 *
 * LED Durumu:
 *   Surekli YANIK  = Bagli, normal calisma
 *   Yavas yanip sonme = Baglanti bekleniyor
 *   Hizli yanip sonme = Failsafe aktif (sinyal kaybi)
 */

#include <SPI.h>
#include <nRF24L01.h>
#include <RF24.h>
#include <Servo.h>

// === Pin Tanimlari ===
#define CE_PIN        9
#define CSN_PIN       10
#define AILERON_PIN   3
#define ELEVATOR_PIN  5
#define RUDDER_PIN    6
#define THROTTLE_PIN  7
#define BATTERY_PIN   A0
#define LED_PIN       2

// === NRF24L01+ ===
RF24 radio(CE_PIN, CSN_PIN);
const byte address[6] = "RC01";

// === Paket Tanimlari ===
struct ControlPacket {
  uint8_t header;        // 0xC0
  uint16_t aileron;      // 1000-2000 us
  uint16_t elevator;
  uint16_t rudder;
  uint16_t throttle;
} __attribute__((packed));

struct TelemetryPacket {
  uint8_t header;        // 0xAA
  uint16_t battery_mv;   // milivolt
  uint8_t rssi;          // 0-100
  uint8_t flags;         // bit0: failsafe, bit1: pil kritik
  uint8_t crc;
} __attribute__((packed));

// === Servolar ===
Servo aileronServo;
Servo elevatorServo;
Servo rudderServo;
Servo throttleEsc;

// === Sabitler ===
const uint16_t SERVO_MIN = 1000;
const uint16_t SERVO_CENTER = 1500;
const uint16_t SERVO_MAX = 2000;
const uint16_t THROTTLE_MIN = 1000;
const uint16_t THROTTLE_MAX = 2000;

const unsigned long FAILSAFE_TIMEOUT = 500;   // 500ms sinyal kaybi = failsafe
const unsigned long TELEMETRY_INTERVAL = 100;  // 100ms = 10Hz telemetri

// Voltaj bolucu: R1=10k, R2=2.2k
// Vout = Vin * R2/(R1+R2) => Vin = Vout * (R1+R2)/R2
const float VOLTAGE_DIVIDER_RATIO = 5.545;

// 3S LiPo sinirlari
const uint16_t BATTERY_FULL_MV = 12600;
const uint16_t BATTERY_EMPTY_MV = 9900;
const uint16_t BATTERY_CRITICAL_MV = 10200;

// === Degiskenler ===
unsigned long lastPacketTime = 0;
unsigned long packetCount = 0;
unsigned long lastTelemetryTime = 0;
bool failsafeActive = false;
bool firstPacketReceived = false;

// RSSI hesaplamasi icin
unsigned long rssiWindowStart = 0;
unsigned long rssiWindowPackets = 0;
uint8_t currentRSSI = 0;

// LED yanip sonme
unsigned long lastLedToggle = 0;
bool ledState = false;

void setup() {
  Serial.begin(115200);

  // LED
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);

  // Servo baglantilari
  aileronServo.attach(AILERON_PIN);
  elevatorServo.attach(ELEVATOR_PIN);
  rudderServo.attach(RUDDER_PIN);
  throttleEsc.attach(THROTTLE_PIN);

  // Baslangic: guvenli pozisyon
  setFailsafePosition();

  // NRF24L01+ baslatma
  radio.begin();
  radio.setPALevel(RF24_PA_HIGH);
  radio.setDataRate(RF24_250KBPS);
  radio.setChannel(108);
  radio.setPayloadSize(sizeof(ControlPacket));
  radio.openReadingPipe(1, address);
  radio.startListening();

  // ESC kalibrasyonu icin bekle
  delay(2000);
  digitalWrite(LED_PIN, LOW);

  rssiWindowStart = millis();

  Serial.println(F("ALICI HAZIR"));
}

void loop() {
  unsigned long now = millis();

  // === Paket Alimi ===
  if (radio.available()) {
    ControlPacket pkt;
    radio.read(&pkt, sizeof(pkt));

    if (pkt.header == 0xC0) {
      lastPacketTime = now;
      packetCount++;
      rssiWindowPackets++;

      if (!firstPacketReceived) {
        firstPacketReceived = true;
        Serial.println(F("ILK PAKET ALINDI"));
      }

      // Failsafe sifirla
      if (failsafeActive) {
        failsafeActive = false;
        Serial.println(F("FAILSAFE DEVRE DISI - Baglanti geri geldi"));
      }

      // Degerleri guvenli araliga cek
      uint16_t ail = constrain(pkt.aileron, SERVO_MIN, SERVO_MAX);
      uint16_t ele = constrain(pkt.elevator, SERVO_MIN, SERVO_MAX);
      uint16_t rud = constrain(pkt.rudder, SERVO_MIN, SERVO_MAX);
      uint16_t thr = constrain(pkt.throttle, THROTTLE_MIN, THROTTLE_MAX);

      // Servolari guncelle
      aileronServo.writeMicroseconds(ail);
      elevatorServo.writeMicroseconds(ele);
      rudderServo.writeMicroseconds(rud);
      throttleEsc.writeMicroseconds(thr);
    }
  }

  // === RSSI Hesapla (her 1 saniyede) ===
  if (now - rssiWindowStart >= 1000) {
    // 50Hz gonderimde 50 paket = %100 RSSI
    currentRSSI = constrain(rssiWindowPackets * 2, 0, 100);
    rssiWindowPackets = 0;
    rssiWindowStart = now;
  }

  // === Failsafe Kontrolu ===
  if (!failsafeActive && (now - lastPacketTime > FAILSAFE_TIMEOUT)) {
    failsafeActive = true;
    setFailsafePosition();
    Serial.println(F("FAILSAFE AKTIF - Sinyal kaybi!"));
  }

  // === LED Durumu ===
  updateLED(now);

  // === Telemetri Gonderimi ===
  if (now - lastTelemetryTime >= TELEMETRY_INTERVAL) {
    lastTelemetryTime = now;
    sendTelemetry();
  }
}

void setFailsafePosition() {
  aileronServo.writeMicroseconds(SERVO_CENTER);
  elevatorServo.writeMicroseconds(SERVO_CENTER);
  rudderServo.writeMicroseconds(SERVO_CENTER);
  throttleEsc.writeMicroseconds(THROTTLE_MIN);
}

void updateLED(unsigned long now) {
  if (failsafeActive) {
    // Hizli yanip sonme (100ms)
    if (now - lastLedToggle >= 100) {
      lastLedToggle = now;
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState);
    }
  } else if (!firstPacketReceived) {
    // Yavas yanip sonme (500ms) - baglanti bekleniyor
    if (now - lastLedToggle >= 500) {
      lastLedToggle = now;
      ledState = !ledState;
      digitalWrite(LED_PIN, ledState);
    }
  } else {
    // Surekli yanik - normal calisma
    digitalWrite(LED_PIN, HIGH);
  }
}

void sendTelemetry() {
  TelemetryPacket tel;
  tel.header = 0xAA;

  // Pil voltaji (3S LiPo)
  int analogVal = analogRead(BATTERY_PIN);
  float vout = analogVal * (5.0 / 1024.0);
  uint16_t vin_mv = (uint16_t)(vout * VOLTAGE_DIVIDER_RATIO * 1000.0);
  tel.battery_mv = vin_mv;

  // RSSI
  tel.rssi = currentRSSI;

  // Durum bayraklari
  tel.flags = 0;
  if (failsafeActive) tel.flags |= 0x01;
  if (vin_mv < BATTERY_CRITICAL_MV) tel.flags |= 0x02;

  // CRC
  tel.crc = tel.header ^ (uint8_t)(tel.battery_mv & 0xFF)
            ^ (uint8_t)(tel.battery_mv >> 8) ^ tel.rssi ^ tel.flags;

  // TX moduna gec, gonder, RX moduna don
  radio.stopListening();
  radio.openWritingPipe(address);
  radio.write(&tel, sizeof(tel));
  radio.startListening();
}
