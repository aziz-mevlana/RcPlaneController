/*
 * RC Plane Controller - Verici (Transmitter)
 * Arduino Nano + NRF24L01
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
 * Binary protokol: 0xAA + 10 byte (5 x uint16 LE)
 * Python control.py ile kullanilir.
 */

#include <SPI.h>
#include <RF24.h>

RF24 radio(9, 10);

const byte txAddress[6] = "00001";
const byte BINARY_SYNC = 0xAA;
const byte DATA_BYTES = 10;  // 5 kanal x 2 byte

struct __attribute__((packed)) ControlPacket {
  uint16_t throttle;
  uint16_t aileron;
  uint16_t elevator;
  uint16_t rudder;
  uint16_t aux;
};

ControlPacket packet;

void setup() {
  Serial.begin(115200);

  if (!radio.begin()) {
    while (1);
  }

  packet.throttle = 1000;
  packet.aileron  = 1500;
  packet.elevator = 1500;
  packet.rudder   = 1500;
  packet.aux      = 1500;

  radio.openWritingPipe(txAddress);
  radio.setPALevel(RF24_PA_LOW);
  radio.setDataRate(RF24_250KBPS);
  radio.setChannel(108);
  radio.setPayloadSize(sizeof(packet));
  radio.setAutoAck(false);
  radio.stopListening();
}

void loop() {
  while (Serial.available() >= (1 + DATA_BYTES)) {
    byte first = Serial.peek();

    if (first == BINARY_SYNC) {
      Serial.read(); // sync
      byte buf[DATA_BYTES];
      Serial.readBytes(buf, DATA_BYTES);

      packet.throttle = buf[0] | (buf[1] << 8);
      packet.aileron  = buf[2] | (buf[3] << 8);
      packet.elevator = buf[4] | (buf[5] << 8);
      packet.rudder   = buf[6] | (buf[7] << 8);
      packet.aux      = buf[8] | (buf[9] << 8);

      radio.write(&packet, sizeof(packet));
    } else {
      Serial.read(); // bayt temizle
    }
  }
}
