# RC Plane Controller

2x Arduino Nano + NRF24L01 ile 5 kanal kablosuz RC uçak kontrol sistemi.

## Proje Yapısı

```
├── transmitter/transmitter.ino   # Verici - Binary protokol, NRF24L01 gönderir
├── receiver/receiver.ino         # Alıcı - ESC + 4 servo (dual aileron mix)
├── control.py                    # PC klavye kontrol scripti
└── venv/                         # Python sanal ortam
```

## Kanal Listesi

| Kanal | İşlev | Tip | Alıcı Pini | Kontrol Tuşu |
|-------|-------|-----|-----------|-------------|
| 1 | Throttle (Gaz) | ESC | D3 | W / S |
| 2 | Aileron (Roll) | Servo x2 | D5 + D4 | ← → |
| 3 | Elevator (Kuyruk Yatay) | Servo | D6 | ↑ ↓ |
| 4 | Rudder (Kuyruk Dikey) | Servo | D7 | A / D |

**Dual Aileron:** Alıcıda otomatik mixing yapılır. Vericiden gelen tek `aileron` değeri:
- Sağ kanat (D5) = aynı yönde
- Sol kanat (D4) = ters yönde (3000 - aileron)

Sağa roll → sağ kanat yukarı, sol kanat aşağı. Sola roll → tam tersi.

## NRF24L01 Bağlantısı

### Shield/Adaptör varsa (önerilen)

| NRF24L01 Shield | Arduino Nano |
|-----------------|-------------|
| VCC | **5V** |
| GND | GND |
| CE | D9 |
| CSN | D10 |
| SCK | D13 |
| MOSI | D11 |
| MISO | D12 |

### Çıplak modül (shield yok)

| NRF24L01 | Arduino Nano |
|----------|-------------|
| VCC | **3.3V** |
| GND | GND |
| CE | D9 |
| CSN | D10 |
| SCK | D13 |
| MOSI | D11 |
| MISO | D12 |

> Shield varsa VCC→5V, yoksa VCC→3.3V. Çıplak modülde VCC-GND arasına 10-100µF kondansatör şart.

---

## Alıcı (Receiver) Bağlantıları

```
                            +-----------+
      LiPo Pil              | Arduino   |
      +   -                 | Nano      |
      |   |                 |           |
      |   |    NRF24L01     |           |    Sag Aileron D5
      |   |    +-------+    |           |    Sol Aileron D4 (ters)
      |   |    | VCC --|----|5V/3.3V    |    Elevator     D6
      |   |    | GND --|----|GND        |    Rudder       D7
      |   |    | CE  --|----|D9         |
      |   |    | CSN --|----|D10        |
      |   |    | SCK --|----|D13        |
      |   |    | MOSI -|----|D11        |
      |   |    | MISO -|----|D12        |
      |   |    +-------+    |           |
      |   |                 |           |
      |   |    ESC          |           |
      |   |    +--------+   |           |
      +---|----|Pil +   |   |           |
          |    |Pil -   |   |           |
          |    |Motor A |   |           |
          |    |Motor B +---+ Motor     |
          |    |Motor C |   |           |
          |    |Sinyal--|---|D3         |
          |    |GND   --|---|GND        |
          |    |5V(BEC) |  (USB varsa boş)
          |    +--------+  (USB yoksa VIN)
```

### Alıcı Pin Tablosu

| Pin    | Bağlantı            | Açıklama                             |
|--------|---------------------|--------------------------------------|
| D3     | ESC Sinyal          | PWM (1000-2000µs)                    |
| D4     | Sol Kanat Aileron   | D5'in tersi (otomatik mix)           |
| D5     | Sağ Kanat Aileron   | Roll komutu                          |
| D6     | Elevator            | Kuyruk yatay                         |
| D7     | Rudder              | Kuyruk dikey                         |
| GND    | ESC GND + Servo GND | Ortak toprak                         |
| 5V/VIN | ESC BEC 5V          | USB yoksa bağla, USB varsa boş bırak |

---

## Verici (Transmitter) Bağlantıları

```
      PC (USB)
         |
    Arduino Nano
         |
    NRF24L01 (Shield)
```

Sadece NRF24L01 bağlı. PC'ye USB ile bağlı.

---

## Kurulum

```bash
# 1. Python sanal ortam
python3 -m venv venv
source venv/bin/activate
pip install pyserial

# 2. Arduino IDE'de RF24 kütüphanesini yükle
#    Araçlar > Kütüphane Yöneticisi > "RF24 by TMRh20"

# 3. transmitter/transmitter.ino → Verici Nano'ya yükle
# 4. receiver/receiver.ino      → Alıcı Nano'ya yükle

# 5. Çalıştır
python3 control.py
```

## Kullanım

Alıcıyı aç (pili bağla), ESC arm sesini bekle (3 sn), sonra:

```bash
source venv/bin/activate
python3 control.py
```

| Tuş | İşlev |
|-----|-------|
| **W** | Gaz artır |
| **S** | Gaz azalt |
| **A / D** | Rudder (kuyruk dikey) |
| **← →** | Aileron (kanat roll) |
| **↑ ↓** | Elevator (kuyruk yatay) |
| **Space** | Acil gaz kes |
| **Q** | Çıkış |

### Güvenlik

- Alıcı 1 saniyeden fazla sinyal alamazsa otomatik gaz keser (failsafe)
- Çıkışta (Q) gaz otomatik 1000'e çekilir
- ESC arm olana kadar bekle (bip sesi)
- **Pervaneyi takmadan önce sistemi test et**
