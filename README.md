# RC Plane Controller

2x Arduino Nano + NRF24L01 + MPU6050 ile 5 kanal kablosuz RC uçak kontrol ve stabilizasyon sistemi.

## Proje Yapısı

```
├── transmitter/transmitter.ino   # Verici - Binary protokol, NRF24L01 gönderir
├── receiver/receiver.ino         # Alıcı - ESC + 4 servo (dual aileron) + MPU6050 stabilizasyon
├── control.py                    # PC klavye + joystick kontrol scripti
├── requirements.txt              # Python bağımlılıkları
└── .gitignore
```

## Kanal Listesi

| Kanal | İşlev | Tip | Alıcı Pini | Kontrol |
|-------|-------|-----|-----------|---------|
| 1 | Throttle (Gaz) | ESC | D3 | W / S / L2-R2 |
| 2 | Aileron (Roll) | Servo x2 | D5 + D4 | ← → / Sol Stick X |
| 3 | Elevator (Kuyruk Yatay) | Servo | D6 | ↑ ↓ / Sol Stick Y |
| 4 | Rudder (Kuyruk Dikey) | Servo | D7 | A / D / Sağ Stick X |

**Dual Aileron:** Sağ (D5) ve sol (D4) kanat aynı PWM değerini alır. Asimetrik kanat
hareketi servoların mekanik olarak ters montajı ile sağlanır — iki servoya aynı sinyal
gittiğinde biri yukarı diğeri aşağı hareket eder.

> Servo montaj yönüne göre asimetri sağlanmazsa `receiver.ino` içinde D4 satırı
> `3000 - currentAileron` olarak değiştirilebilir.

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
      |   |    +-------+    |           |    Sol Aileron D4
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

| Pin    | Bağlantı            | Açıklama                     |
|--------|---------------------|------------------------------|
| D3     | ESC Sinyal          | PWM (1000-2000µs)            |
| D4     | Sol Kanat Aileron   | D5 ile aynı değer            |
| D5     | Sağ Kanat Aileron   | Roll komutu                  |
| D6     | Elevator            | Kuyruk yatay                 |
| D7     | Rudder              | Kuyruk dikey                 |
| GND    | ESC GND + Servo GND | Ortak toprak                 |
| 5V/VIN | ESC BEC 5V          | USB yoksa bağla, USB varsa boş |

### MPU6050 Bağlantısı (Stabilizasyon)

| MPU6050 | Arduino Nano |
|---------|-------------|
| VCC     | **5V**       |
| GND     | GND          |
| SCL     | A5           |
| SDA     | A4           |

> MPU6050'yi titreşim izolasyonlu monte edin (sünger/çift taraflı bant).
> X ekseni ileri, Y ekseni sağ kanada, Z ekseni aşağı bakmalı.
> Arduino Library Manager'dan **MPU6050_light** kütüphanesini yükleyin.

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
# 1. Python sanal ortam ve bağımlılıklar
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Arduino IDE'de kütüphaneleri yükle
#    Araçlar > Kütüphane Yöneticisi > "RF24 by TMRh20"
#    Araçlar > Kütüphane Yöneticisi > "MPU6050_light"

# 3. transmitter/transmitter.ino → Verici Nano'ya yükle
# 4. receiver/receiver.ino      → Alıcı Nano'ya yükle
```

## Kullanım

Alıcıyı aç (pili bağla), ESC arm sesini bekle (3 sn), sonra:

```bash
source venv/bin/activate
python3 control.py
```

Pygame penceresi açılır. Joystick bağlıysa otomatik algılanır, stick pozisyonları
canlı gösterilir. Klavye ve joystick aynı anda çalışır.

### Klavye

| Tuş | İşlev |
|-----|-------|
| **W / S** | Gaz artır / azalt |
| **A / D** | Rudder (kuyruk dikey) |
| **← →** | Aileron (kanat roll) |
| **↑ ↓** | Elevator (kuyruk yatay) |
| **Space** | Acil gaz kes |
| **Q / ESC** | Çıkış |

### Steam Deck / Joystick

| Kumanda | Kanal |
|---------|-------|
| **Sol Stick X** | Aileron |
| **Sol Stick Y** | Elevator |
| **Sağ Stick X** | Rudder |
| **L2** | Gaz artır |
| **R2** | Gaz azalt |
| **L1** | Gaz kes (acil) |
| **D-Pad Sol/Sağ** | Aileron (yedek) |
| **D-Pad Yukarı/Aşağı** | Elevator (yedek) |
| **Start** | Çıkış |
| **A / Cross** | Stabilizasyon aç/kapa |

### Stabilizasyon (Auto-Level)

MPU6050 ile uçağın roll ve pitch açıları okunur, PD kontrolcü ile otomatik
dengeleme yapılır. Stick merkezdeyken uçak kendini düz tutar.

- **Açma/Kapama:** Joystick'te **A (Cross)** tuşu
- **AUX kanalı:** 2000 = aktif, 1000 = pasif
- **Max hedef açı:** ±45° (tam stick)
- **Failsafe:** Sinyal kesilince stabilizasyon otomatik kapanır

#### PID Ayarı

`receiver/receiver.ino` içinde ayarlanabilir:

```cpp
const float ROLL_KP  = 1.5;   // Roll oransal kazancı
const float ROLL_KD  = 0.5;   // Roll türev kazancı (sönümleme)
const float PITCH_KP = 1.5;   // Pitch oransal kazancı
const float PITCH_KD = 0.5;   // Pitch türev kazancı
```

> İlk uçuşta düşük kazançlarla başlayın. Salınım varsa KD artırın,
> yavaş tepki varsa KP artırın. Yön ters ise KP işaretini değiştirin.

### Güvenlik

- Alıcı 1.5 saniyeden fazla sinyal alamazsa otomatik gaz keser (failsafe)
- Stabilizasyon sinyal kesilince otomatik kapanır
- Çıkışta (Q) gaz otomatik 1000'e çekilir
- ESC arm olana kadar bekle (bip sesi)
- **Pervaneyi takmadan önce sistemi test et**
- MPU6050 kalibrasyonu her açılışta yapılır (3-4 sn), uçağı sabit tutun
