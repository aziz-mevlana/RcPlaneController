# RC Uçak Kontrol Sistemi

Arduino Nano + NRF24L01+ tabanlı RC uçak kontrol sistemi. Steam Deck ile joystick kontrolü ve tam uçuş paneli.

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
- USB kablo (Steam Deck'e)

## Pin Bağlantıları

### Uçak Arduino Nano
| Pin | Bağlantı |
|-----|----------|
| D3 | Aileron Servo (Signal) |
| D5 | Elevator Servo (Signal) |
| D6 | Rudder Servo (Signal) |
| D7 | ESC Throttle (Signal) |
| D9 | NRF24L01+ CE |
| D10 | NRF24L01+ CSN |
| D11 | NRF24L01+ MOSI |
| D12 | NRF24L01+ MISO |
| D13 | NRF24L01+ SCK |
| A0 | Pil Voltaj Bölücü (Orta nokta) |
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
| USB | Steam Deck |
| 3.3V | NRF24L01+ VCC |
| GND | GND |

## Kurulum

### Arduino
1. Arduino IDE'de `RF24` kütüphanesini kur (Library Manager'dan)
2. `Servo` kütüphanesi dahili olarak gelir
3. `receiver/airplane_receiver/airplane_receiver.ino` → Uçak Arduino'suna yükle
4. `transmitter/ground_transmitter/ground_transmitter.ino` → Verici Arduino'suna yükle

### Steam Deck (Python GUI)
```bash
cd ground_station
pip install -r requirements.txt
python main.py
```

## Kullanım

### Kontroller
| Buton | Tuş | İşlev |
|-------|-----|-------|
| Menu (Start) | ESC | Çıkış |
| A | C | Arduino'ya bağlan |
| B | D | Bağlantıyı kes |
| X | R | Joystick'i yenile |
| Y | L | Uçuş kaydını başlat/durdur |

### Sol Cubuk (Aileron + Elevator)
- Sol/Sağ → Aileron (yuvarlanma)
- İleri/Geri → Elevator (tırmanma/alçalma)

### Sag Cubuk (Rudder + Throttle)
- Sol/Sağ → Rudder (yön değiştirme)
- İleri/Geri → Throttle (gaz)

### Uçuş Kayıtları
- `ground_station/logs/` klasörüne CSV olarak kaydedilir
- Zaman damgası, tüm kanal değerleri ve telemetri içerir

## Telemetri
- **Pil Voltajı:** 3S LiPo (9.9V boş - 12.6V dolu)
- **RSSI:** Sinyal gücü (0-100%)
- **Failsafe:** 500ms sinyal kaybında aktif olur, servolar merkeze throttle minimuma döner

## Protokol

### Kontrol Paketi (NRF24L01+)
| Byte | İçerik | Aralık |
|------|--------|--------|
| 0 | Header | 0xC0 |
| 1-2 | Aileron | 1000-2000 |
| 3-4 | Elevator | 1000-2000 |
| 5-6 | Rudder | 1000-2000 |
| 7-8 | Throttle | 1000-2000 |

### Seri Protokol (Steam Deck ↔ TX Arduino)
Gönderim: `[0xC0][CH1H][CH1L][CH2H][CH2L][CH3H][CH3L][CH4H][CH4L][CRC][0x0A]`

Telemetri: `TEL:millivolt,rssi,flags\n`

## Ayarlar

### Joystick Eşleme
`ground_station/joystick_config.json` dosyasını düzenleyerek joystick eksenlerini değiştirebilirsiniz:
```json
{
  "axis_map": {
    "0": {"channel": "aileron", "invert": false},
    "1": {"channel": "elevator", "invert": true}
  }
}
```

### NRF24L01+ Ayarları
Her iki Arduino'da aynı ayarlar olmalı:
- Kanal: 108
- Veri hızı: 250kbps (menzil öncelikli)
- Güç seviyesi: HIGH
- Adres: "RC01"
