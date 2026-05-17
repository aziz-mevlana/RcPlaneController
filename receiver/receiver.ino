/*
 * RC Plane Controller - Alici (Receiver)
 * Arduino Nano + NRF24L01 + ESC + 4 Servo
 *
 * NRF24L01 (tek basina) -> Arduino Nano:
 *   VCC  -> 3.3V  (VCC-GND arasi 10-100uF kondansator SART)
 *   GND  -> GND
 *   CE   -> D9
 *   CSN  -> D10
 *   SCK  -> D13
 *   MOSI -> D11
 *   MISO -> D12
 *
 * NRF24L01 (adaptor shield ile) -> Arduino Nano:
 *   VCC  -> 5V    (shield uzerinde 5V->3.3V regulator var)
 *   GND  -> GND
 *   CE   -> D9
 *   CSN  -> D10
 *   SCK  -> D13
 *   MOSI -> D11
 *   MISO -> D12
 *
 * Cikislar (Dual Aileron):
 *   D3  -> ESC (Gaz/Throttle)
 *   D5  -> Sag Kanat Aileron  (aileron ile dogru orantili)
 *   D4  -> Sol Kanat Aileron  (aileron ters, otomatik mix)
 *   D6  -> Elevator (Kuyruk Yatay)
 *   D7  -> Rudder   (Kuyruk Dikey)
 *
 * ESC -> Motor -> Pil baglantisi:
 *   ESC 3x mavi kablo  -> Brushless motor 3 kablosu
 *   ESC kirmizi/siyah   -> LiPo pil
 *   ESC sinyal kablosu  -> Arduino D3
 *   ESC GND             -> Arduino GND
 *   ESC 5V (kirmizi)    -> USB varsa BOS, yoksa VIN
 */

#include <SPI.h>
#include <RF24.h>
#include <Servo.h>

RF24 radio(9, 10);

const byte rxAddress[6] = "00001";

struct __attribute__((packed)) ControlPacket {
  uint16_t throttle;
  uint16_t aileron;
  uint16_t elevator;
  uint16_t rudder;
  uint16_t aux;
};

ControlPacket packet;

Servo esc;
Servo servoRightAileron;
Servo servoLeftAileron;
Servo servoElevator;
Servo servoRudder;

const int PIN_ESC            = 3;
const int PIN_RIGHT_AILERON  = 5;
const int PIN_LEFT_AILERON   = 4;
const int PIN_ELEVATOR       = 6;
const int PIN_RUDDER         = 7;
const int PIN_LED            = LED_BUILTIN;

unsigned long lastPacketTime = 0;
unsigned long lastResetAttempt = 0;
bool armed = false;
bool linkLost = false;
int resetAttempts = 0;

uint16_t currentThrottle = 1000;
uint16_t currentAileron = 1500;
uint16_t currentElevator = 1500;
uint16_t currentRudder = 1500;

uint16_t targetThrottle = 1000;
uint16_t targetAileron = 1500;
uint16_t targetElevator = 1500;
uint16_t targetRudder = 1500;

void resetRadio() {
  radio.stopListening();
  radio.begin();
  radio.openReadingPipe(0, rxAddress);
  radio.setPALevel(RF24_PA_LOW);
  radio.setDataRate(RF24_250KBPS);
  radio.setChannel(108);
  radio.setPayloadSize(sizeof(packet));
  radio.setAutoAck(false);
  radio.startListening();
}

void centerServos() {
  targetThrottle = 1000;
  targetAileron = 1500;
  targetElevator = 1500;
  targetRudder = 1500;
  currentThrottle = 1000;
  currentAileron = 1500;
  currentElevator = 1500;
  currentRudder = 1500;
  esc.writeMicroseconds(1000);
  servoRightAileron.writeMicroseconds(1500);
  servoLeftAileron.writeMicroseconds(1500);
  servoElevator.writeMicroseconds(1500);
  servoRudder.writeMicroseconds(1500);
}

uint16_t smoothMove(uint16_t current, uint16_t target, uint16_t maxStep) {
  if (current < target) {
    return min(target, current + maxStep);
  } else if (current > target) {
    return max(target, current - maxStep);
  }
  return current;
}

void setup() {
  Serial.begin(115200);
  while (!Serial);

  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  if (!radio.begin()) {
    Serial.println(F("NRF24L01 baslatilamadi!"));
    while (1);
  }

  radio.openReadingPipe(0, rxAddress);
  radio.setPALevel(RF24_PA_LOW);
  radio.setDataRate(RF24_250KBPS);
  radio.setChannel(108);
  radio.setPayloadSize(sizeof(packet));
  radio.setAutoAck(false);
  radio.startListening();

  esc.attach(PIN_ESC, 1000, 2000);
  servoRightAileron.attach(PIN_RIGHT_AILERON);
  servoLeftAileron.attach(PIN_LEFT_AILERON);
  servoElevator.attach(PIN_ELEVATOR);
  servoRudder.attach(PIN_RUDDER);

  Serial.println(F("ESC arm ediliyor... 3 sn"));
  esc.writeMicroseconds(1000);
  servoRightAileron.writeMicroseconds(1500);
  servoLeftAileron.writeMicroseconds(1500);
  servoElevator.writeMicroseconds(1500);
  servoRudder.writeMicroseconds(1500);
  delay(3000);

  armed = true;
  Serial.println(F("=== RC Alici Hazir ==="));
  Serial.println(F("D3=ESC D5=SagAil D4=SolAil D6=Elev D7=Rudd"));
  Serial.println();
}

void loop() {
  if (radio.available()) {
    radio.read(&packet, sizeof(packet));
    lastPacketTime = millis();

    if (linkLost) {
      linkLost = false;
      resetAttempts = 0;
      digitalWrite(PIN_LED, HIGH);
      Serial.println(F("++ Baglanti yeniden kuruldu"));
    }

    targetThrottle = packet.throttle;
    targetAileron  = packet.aileron;
    targetElevator = packet.elevator;
    targetRudder   = packet.rudder;

    Serial.print(F("<< T:"));
    Serial.print(packet.throttle);
    Serial.print(F(" R:"));
    Serial.print(packet.aileron);
    Serial.print(F(" E:"));
    Serial.print(packet.elevator);
    Serial.print(F(" D:"));
    Serial.println(packet.rudder);
  }

  currentThrottle = smoothMove(currentThrottle, targetThrottle, 5);
  currentAileron  = smoothMove(currentAileron, targetAileron, 5);
  currentElevator = smoothMove(currentElevator, targetElevator, 5);
  currentRudder   = smoothMove(currentRudder, targetRudder, 5);

  esc.writeMicroseconds(currentThrottle);
  servoRightAileron.writeMicroseconds(currentAileron);
  servoLeftAileron.writeMicroseconds(3000 - currentAileron);
  servoElevator.writeMicroseconds(currentElevator);
  servoRudder.writeMicroseconds(currentRudder);

  if (armed && millis() - lastPacketTime > 1500) {
    if (!linkLost) {
      linkLost = true;
      centerServos();
      Serial.println(F("!! Sinyal kesildi - Servolar merkezlendi !!"));
    }

    digitalWrite(PIN_LED, !digitalRead(PIN_LED));

    if (millis() - lastResetAttempt > 5000 && resetAttempts < 3) {
      Serial.print(F("!! NRF yeniden baslatiliyor ("));
      Serial.print(resetAttempts + 1);
      Serial.println(F("/3)"));
      resetRadio();
      lastResetAttempt = millis();
      resetAttempts++;
    }

    lastPacketTime = millis();
  }
}
