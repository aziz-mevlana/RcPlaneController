/*
 * RC Ucak Alici - Arduino Nano + NRF24L01+
 * Kanallar: Aileron(D3), Elevator(D5), Rudder(D6), Throttle(D7)
 * Telemetri: 3S Pil voltaji(A0) + sinyal gucu
 * Pil: 3S LiPo 11.1V (9.9V-12.6V)
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
#define LED_PIN       2   // Durum LED'i (opsiyonel)

// === NRF24L01+ ===
RF24 radio(CE_PIN, CSN_PIN);
const byte address[6] = "RC01";

// === Paket Tanimlari ===
// Kontrol Paketi (9 byte) - Vericiden alinir
struct ControlPacket {
  uint8_t header;        // 0xC0
  uint16_t aileron;      // 1000-2000 us
  uint16_t elevator;
  uint16_t rudder;
  uint16_t throttle;
} __attribute__((packed));

// Telemetri Paketi (6 byte) - Vericiye gonderilir
struct TelemetryPacket {
  uint8_t header;        // 0xAA
  uint16_t battery_mv;   // milivolt
  uint8_t rssi;          // 0-100
  uint8_t flags;         // bit0: failsafe
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

const unsigned long FAILSAFE_TIMEOUT = 500;
const unsigned long TELEMETRY_INTERVAL = 100;

// Voltaj bolucu: R1=10k, R2=2.2k
// Vout = Vin * R2/(R1+R2) => Vin = Vout * (R1+R2)/R2
// Oran = (10+2.2)/2.2 = 5.545
const float VOLTAGE_DIVIDER_RATIO = 5.545;

// 3S LiPo sinirlar
const uint16_t BATTERY_FULL_MV = 12600;
const uint16_t BATTERY_EMPTY_MV = 9900;
const uint16_t BATTERY_CRITICAL_MV = 10200;

// === Degiskenler ===
unsigned long lastPacketTime = 0;
unsigned long packetCount = 0;
unsigned long lastTelemetryTime = 0;
bool failsafeActive = false;

// RSSI icin
unsigned long prevPacketCount = 0;

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

  // Baslangic pozisyonlari
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

  Serial.println(F("ALICI HAZIR"));
  Serial.print(F("Pil araligi: "));
  Serial.print(BATTERY_EMPTY_MV);
  Serial.print(F(" - "));
  Serial.print(BATTERY_FULL_MV);
  Serial.println(F(" mV"));
}

void loop() {
  unsigned long now = millis();

  // --- Paket Alimi ---
  if (radio.available()) {
    ControlPacket pkt;
    radio.read(&pkt, sizeof(pkt));

    if (pkt.header == 0xC0) {
      lastPacketTime = now;
      failsafeActive = false;
      packetCount++;

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

  // --- Failsafe Kontrolu ---
  if (!failsafeActive && (now - lastPacketTime > FAILSAFE_TIMEOUT)) {
    failsafeActive = true;
    setFailsafePosition();
    Serial.println(F("FAILSAFE AKTIF - Sinyal kaybi!"));
  }

  // --- LED Guncelleme ---
  if (failsafeActive) {
    digitalWrite(LED_PIN, (now / 100) % 2);  // Hizli yanip sonme
  } else {
    digitalWrite(LED_PIN, HIGH);  // Sabit - bagli
  }

  // --- Telemetri Gonderimi ---
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

void sendTelemetry() {
  TelemetryPacket tel;
  tel.header = 0xAA;

  // Pil voltaji hesapla (3S LiPo)
  int analogVal = analogRead(BATTERY_PIN);
  float vout = analogVal * (5.0 / 1024.0);
  uint16_t vin_mv = (uint16_t)(vout * VOLTAGE_DIVIDER_RATIO * 1000.0);
  tel.battery_mv = vin_mv;

  // RSSI: son 1 saniyedeki paket orani
  unsigned long countDiff = packetCount - prevPacketCount;
  prevPacketCount = packetCount;
  tel.rssi = (uint8_t)constrain(countDiff * 10, 0, 100);

  // Durum bayraklari
  tel.flags = 0;
  if (failsafeActive) tel.flags |= 0x01;
  if (vin_mv < BATTERY_CRITICAL_MV) tel.flags |= 0x02;

  // CRC
  tel.crc = tel.header ^ (uint8_t)(tel.battery_mv & 0xFF)
            ^ (uint8_t)(tel.battery_mv >> 8) ^ tel.rssi ^ tel.flags;

  // Gonder (TX moduna gec, geri don)
  radio.stopListening();
  radio.openWritingPipe(address);
  bool ok = radio.write(&tel, sizeof(tel));
  radio.startListening();
}
