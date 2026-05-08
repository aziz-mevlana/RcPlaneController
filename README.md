# RC Uçak Kontrol Sistemi

Arduino Nano + NRF24L01+ tabanlı RC uçak kontrol sistemi. Web tabanlı arayüz ile kontrol.

## Donanım

### Uçak (Alıcı)
- Arduino Nano
- NRF24L01+ modül
- 4x Servo (Aileron, Elevator, Rudder, Throttle/ESC)
- 3S LiPo pil (11.1V)
- Voltaj bölücü: R1=10kΩ, R2=2.2kΩ (A0 pinine)

### Yer (Verici)
- Arduino Nano
- NRF24L01+ modül
- USB kablo (Steam Deck'e veya bilgisayara)

## Proje Yapısı

```
RcPlaneController/
├── ground_station_web/          # Web tabanlı kontrol arayüzü
│   ├── app.py                   # Flask + WebSocket backend
│   ├── requirements.txt
│   ├── templates/index.html
│   └── static/
│       ├── css/style.css        # Profesyonel tema
│       └── js/app.js            # Three.js 3D model + input
├── transmitter/
│   └── ground_transmitter/      # Verici Arduino kodu
├── receiver/
│   └── airplane_receiver/       # Alıcı Arduino kodu
└── ground_station/              # Eski PyGame arayüzü (kullanılmıyor)
```

## Pin Bağlantıları

### Uçak Arduino Nano
| Pin | Bağlantı |
|-----|----------|
| D2 | Durum LED'i |
| D3 | Aileron Servo |
| D5 | Elevator Servo |
| D6 | Rudder Servo |
| D7 | ESC Throttle |
| D9 | NRF24L01+ CE |
| D10 | NRF24L01+ CSN |
| D11 | NRF24L01+ MOSI |
| D12 | NRF24L01+ MISO |
| D13 | NRF24L01+ SCK |
| A0 | Pil Voltaj Bölücü |
| 3.3V | NRF24L01+ VCC |
| GND | Ortak GND |

### Voltaj Bölücü Devresi
```
Pil (+) ----[R1=10kΩ]----+---- A0
                          |
                       [R2=2.2kΩ]
                          |
Pil (-) -----------------+---- GND
```

### Verici Arduino Nano
| Pin | Bağlantı |
|-----|----------|
| D9 | NRF24L01+ CE |
| D10 | NRF24L01+ CSN |
| D11 | NRF24L01+ MOSI |
| D12 | NRF24L01+ MISO |
| D13 | NRF24L01+ SCK |
| USB | Steam Deck / Bilgisayar |
| 3.3V | NRF24L01+ VCC |
| GND | GND |

## Kurulum

### Arduino
1. Arduino IDE'de `RF24` kütüphanesini kur (Library Manager'dan)
2. `Servo` kütüphanesi dahili olarak gelir
3. `receiver/airplane_receiver/airplane_receiver.ino` → Uçak Arduino'suna yükle
4. `transmitter/ground_transmitter/ground_transmitter.ino` → Verici Arduino'suna yükle

### Web Arayüzü (Steam Deck / Bilgisayar)
```bash
cd ground_station_web
pip3 install -r requirements.txt
python3 app.py
```

Tarayıcıda **http://localhost:8080** adresini aç.

## Kontroller

### Klavye
| Tuş | İşlev |
|-----|-------|
| ← → | Aileron (roll) |
| ↑ ↓ | Elevator (pitch) |
| W / S | Throttle (gaz) |
| Z / X | Rudder (yön) |
| C | Arduino'ya bağlan |
| D | Bağlantıyı kes |
| L | Uçuş kaydını başlat/durdur |

### Gamepad (Steam Deck / USB Joystick)
| Çubuk | Kontrol |
|-------|---------|
| Sol Stick | Aileron + Elevator |
| Sağ Stick | Rudder + Throttle |
| A | Arduino'ya bağlan |
| B | Bağlantıyı kes |
| Y | Log başlat/durdur |

## Uçuş Kayıtları
- `ground_station_web/logs/` klasörüne CSV olarak kaydedilir
- Zaman damgası, tüm kanal değerleri ve telemetri içerir

## Telemetri
- **Pil Voltajı:** 3S LiPo (9.9V boş - 12.6V dolu)
- **RSSI:** Sinyal gücü (0-100%)
- **Failsafe:** 500ms sinyal kaybında aktif olur, servolar merkeze throttle minimuma döner

## LED Durumu (Uçak)
| Durum | LED |
|-------|-----|
| Normal | Sürekli YANIK |
| Bağlantı bekleniyor | Yavaş yanıp sönme |
| Failsafe | Hızlı yanıp sönme |

## Protokol

### Kontrol Paketi (NRF24L01+)
| Byte | İçerik | Aralık |
|------|--------|--------|
| 0 | Header | 0xC0 |
| 1-2 | Aileron | 1000-2000 |
| 3-4 | Elevator | 1000-2000 |
| 5-6 | Rudder | 1000-2000 |
| 7-8 | Throttle | 1000-2000 |

### Seri Protokol (Web ↔ TX Arduino)
Gönderim: `[0xC0][CH1H][CH1L][CH2H][CH2L][CH3H][CH3L][CH4H][CH4L][CRC][0x0A]`

Telemetri: `TEL:millivolt,rssi,flags\n`

## NRF24L01+ Ayarları
Her iki Arduino'da aynı ayarlar olmalı:
- Kanal: 108
- Veri hızı: 250kbps (menzil öncelikli)
- Güç seviyesi: HIGH
- Adres: "RC01"
