"""
RC Ucak Yer Istasyonu - Steam Deck GUI
PyGame tabanli kontrol paneli
Joystick okuma + Seri haberlesme + Telemetri gorsellestirme
"""

import sys
import os
import time
import csv
import struct
import math
from datetime import datetime
from pathlib import Path

import pygame
import serial
import serial.tools.list_ports

# === Sabitler ===
WIDTH, HEIGHT = 1280, 800
FPS = 60

# Seri protokol
CMD_HEADER = 0xC0
CMD_TERMINATOR = 0x0A
CMD_PACKET_SIZE = 11

# Renkler
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
RED = (255, 50, 50)
YELLOW = (255, 255, 0)
ORANGE = (255, 165, 0)
CYAN = (0, 255, 255)
DARK_GRAY = (40, 40, 40)
PANEL_BG = (18, 22, 38)
PANEL_BORDER = (40, 50, 80)
HUD_GREEN = (0, 200, 50)
HUD_BLUE = (50, 100, 200)
BATTERY_GREEN = (0, 200, 0)
BATTERY_YELLOW = (200, 200, 0)
BATTERY_RED = (200, 0, 0)

# Profesyonel tema renkleri
ACCENT_CYAN = (0, 200, 255)
ACCENT_GREEN = (0, 255, 136)
ACCENT_ORANGE = (255, 140, 0)
ACCENT_RED = (255, 60, 60)
BG_TOP = (12, 14, 28)
BG_BOTTOM = (4, 6, 14)
GLOW_CYAN = (0, 180, 255, 40)
TEXT_DIM = (100, 110, 130)
TEXT_BRIGHT = (220, 230, 245)
BAR_BG = (15, 18, 30)

# Kanal limitleri
SERVO_MIN = 1000
SERVO_CENTER = 1500
SERVO_MAX = 2000
THROTTLE_MIN = 1000
THROTTLE_MAX = 2000

# 3S LiPo
BATTERY_FULL_V = 12.6
BATTERY_EMPTY_V = 9.9
BATTERY_CRITICAL_V = 10.2


class TelemetryData:
    """Ucaktan gelen telemetri verisi"""
    def __init__(self):
        self.battery_mv = 0
        self.rssi = 0
        self.flags = 0
        self.connected = False
        self.last_update = 0

    @property
    def battery_v(self):
        return self.battery_mv / 1000.0

    @property
    def battery_percent(self):
        return max(0, min(100,
            (self.battery_v - BATTERY_EMPTY_V) / (BATTERY_FULL_V - BATTERY_EMPTY_V) * 100))

    @property
    def failsafe(self):
        return bool(self.flags & 0x01)

    @property
    def battery_critical(self):
        return bool(self.flags & 0x02)

    @property
    def is_fresh(self):
        return (time.time() - self.last_update) < 1.0


class SerialComm:
    """Arduino verici ile seri haberlesme"""
    def __init__(self):
        self.port = None
        self.baud = 115200
        self.connected = False
        self.serial = None
        self.buffer = ""
        self.tx_count = 0
        self.rx_count = 0

    def find_arduino(self):
        """Arduino portunu otomatik bul"""
        ports = serial.tools.list_ports.comports()
        for p in ports:
            if "Arduino" in p.description or "CH340" in p.description \
               or "USB" in p.description or "ttyACM" in p.device \
               or "ttyUSB" in p.device:
                return p.device
        return None

    def connect(self, port=None):
        """Arduino'ya baglan"""
        if port is None:
            port = self.find_arduino()
        if port is None:
            return False
        try:
            self.serial = serial.Serial(port, self.baud, timeout=0.01)
            time.sleep(2)  # Arduino reset bekle
            self.port = port
            self.connected = True
            return True
        except Exception as e:
            print(f"Baglanti hatasi: {e}")
            return False

    def disconnect(self):
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.connected = False

    def send_control(self, aileron, elevator, rudder, throttle):
        """Kontrol komutunu Arduino'ya gonder"""
        if not self.connected or not self.serial:
            return

        # Degerleri uint16'a donustur
        ch1 = int(max(SERVO_MIN, min(SERVO_MAX, aileron)))
        ch2 = int(max(SERVO_MIN, min(SERVO_MAX, elevator)))
        ch3 = int(max(SERVO_MIN, min(SERVO_MAX, rudder)))
        ch4 = int(max(THROTTLE_MIN, min(THROTTLE_MAX, throttle)))

        # Paket olustur
        packet = bytearray(CMD_PACKET_SIZE)
        packet[0] = CMD_HEADER
        packet[1] = (ch1 >> 8) & 0xFF
        packet[2] = ch1 & 0xFF
        packet[3] = (ch2 >> 8) & 0xFF
        packet[4] = ch2 & 0xFF
        packet[5] = (ch3 >> 8) & 0xFF
        packet[6] = ch3 & 0xFF
        packet[7] = (ch4 >> 8) & 0xFF
        packet[8] = ch4 & 0xFF

        # CRC
        crc = 0
        for i in range(CMD_PACKET_SIZE - 2):
            crc ^= packet[i]
        packet[9] = crc
        packet[10] = CMD_TERMINATOR

        try:
            self.serial.write(packet)
            self.tx_count += 1
        except Exception:
            self.connected = False

    def read_telemetry(self, telemetry):
        """Arduino'dan telemetri satirini oku"""
        if not self.connected or not self.serial:
            return

        try:
            while self.serial.in_waiting > 0:
                line = self.serial.readline().decode('ascii', errors='ignore').strip()
                if line.startswith("TEL:"):
                    data = line[4:]
                    parts = data.split(',')
                    if len(parts) == 3:
                        telemetry.battery_mv = int(parts[0])
                        telemetry.rssi = int(parts[1])
                        telemetry.flags = int(parts[2])
                        telemetry.connected = True
                        telemetry.last_update = time.time()
                        self.rx_count += 1
                elif line == "TEL:DISCONNECTED":
                    telemetry.connected = False
                elif line == "VERICI HAZIR":
                    print("Verici hazir mesaji alindi")
        except Exception:
            pass


class FlightLog:
    """Ucus verilerini CSV'ye kaydet"""
    def __init__(self):
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filepath = log_dir / f"flight_{timestamp}.csv"
        self.file = open(self.filepath, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.writer.writerow([
            'timestamp', 'aileron', 'elevator', 'rudder', 'throttle',
            'battery_v', 'rssi', 'failsafe', 'connected'
        ])
        self.start_time = time.time()

    def log(self, channels, telemetry):
        elapsed = time.time() - self.start_time
        self.writer.writerow([
            f"{elapsed:.3f}",
            channels['aileron'], channels['elevator'],
            channels['rudder'], channels['throttle'],
            f"{telemetry.battery_v:.2f}", telemetry.rssi,
            telemetry.failsafe, telemetry.connected
        ])

    def close(self):
        self.file.close()


class AircraftSimulator:
    """3D Wireframe ucak simülasyonu - Spitfire modeli"""

    def __init__(self):
        self.roll = 0
        self.pitch = 0
        self.yaw = 0
        self.vertices, self.edges, self.faces = self._build_spitfire()

    def _build_spitfire(self):
        """Spitfire wireframe modeli olustur"""
        v = []
        e = []
        f = []

        # === GÖVDE ===
        # Burun -> Kuyruk arası kesitler (x ekseni boyunca)
        nose_x = 1.8
        body_sections = [
            (nose_x, 0.06, 0.06),       # Burun ucu
            (1.4, 0.10, 0.10),          # Motor kaplaması
            (1.0, 0.13, 0.13),          # Kokpit önü
            (0.6, 0.14, 0.15),          # Kokpit
            (0.2, 0.14, 0.14),          # Kokpit arkası
            (-0.2, 0.13, 0.12),         # Gövde ortası
            (-0.6, 0.11, 0.10),         # Gövde arka
            (-1.0, 0.09, 0.08),         # Kuyruk önü
            (-1.4, 0.07, 0.06),         # Kuyruk
            (-1.7, 0.04, 0.03),         # Kuyruk ucu
        ]

        # Her kesit için 4 nokta (elips cross-section)
        for x, ry, rz in body_sections:
            v.append((x, 0, rz))      # üst
            v.append((x, ry, 0))      # sağ
            v.append((x, 0, -rz))     # alt
            v.append((x, -ry, 0))     # sol

        # Gövde longitudinal kenarlar
        n = len(body_sections)
        for i in range(n - 1):
            base = i * 4
            for j in range(4):
                e.append((base + j, base + 4 + j))
            e.append((base, base + 3))       # cross üst-sol
            e.append((base + 1, base))       # cross sağ-üst
            e.append((base + 2, base + 1))   # cross alt-sağ
            e.append((base + 3, base + 2))   # cross sol-alt

        # Son kesit cross
        last = (n - 1) * 4
        e.append((last, last + 3))
        e.append((last + 1, last))
        e.append((last + 2, last + 1))
        e.append((last + 3, last + 2))

        # === KANATLAR (Eliptik - Spitfire karakteristik) ===
        wing_root_x = -0.1
        wing_le_root = (wing_root_x, 0.15, 0)    # Leading edge kök
        wing_te_root = (wing_root_x - 0.3, 0.15, 0)  # Trailing edge kök

        # Kanat ucu (eliptik)
        wing_tip_x = -0.15
        wing_span = 1.6
        wing_le_tip = (wing_tip_x, wing_span, 0.05)   # LE tip (dihedral)
        wing_te_tip = (wing_tip_x - 0.25, wing_span, 0.05)  # TE tip

        # Orta noktalar (eliptik kavis için)
        wing_mid_span = wing_span * 0.6
        wing_le_mid = (wing_root_x - 0.02, wing_mid_span, 0.03)
        wing_te_mid = (wing_root_x - 0.28, wing_mid_span, 0.03)

        # Sol kanat vertices
        w_start = len(v)
        v.append(wing_le_root)       # 0: LE root
        v.append(wing_te_root)       # 1: TE root
        v.append(wing_le_mid)        # 2: LE mid
        v.append(wing_te_mid)        # 3: TE mid
        v.append(wing_le_tip)        # 4: LE tip
        v.append(wing_te_tip)        # 5: TE tip

        # Sol kanat kenarları
        e.append((w_start, w_start + 2))      # LE root->mid
        e.append((w_start + 2, w_start + 4))  # LE mid->tip
        e.append((w_start + 1, w_start + 3))  # TE root->mid
        e.append((w_start + 3, w_start + 5))  # TE mid->tip
        e.append((w_start, w_start + 1))      # root chord
        e.append((w_start + 2, w_start + 3))  # mid chord
        e.append((w_start + 4, w_start + 5))  # tip chord

        # Kanat yüzeyi
        f.append((w_start, w_start+2, w_start+3, w_start+1))
        f.append((w_start+2, w_start+4, w_start+5, w_start+3))

        # Sağ kanat (y eksenine göre simetrik)
        w2_start = len(v)
        v.append((wing_le_root[0], -wing_le_root[1], wing_le_root[2]))
        v.append((wing_te_root[0], -wing_te_root[1], wing_te_root[2]))
        v.append((wing_le_mid[0], -wing_le_mid[1], wing_le_mid[2]))
        v.append((wing_te_mid[0], -wing_te_mid[1], wing_te_mid[2]))
        v.append((wing_le_tip[0], -wing_le_tip[1], wing_le_tip[2]))
        v.append((wing_te_tip[0], -wing_te_tip[1], wing_te_tip[2]))

        e.append((w2_start, w2_start + 2))
        e.append((w2_start + 2, w2_start + 4))
        e.append((w2_start + 1, w2_start + 3))
        e.append((w2_start + 3, w2_start + 5))
        e.append((w2_start, w2_start + 1))
        e.append((w2_start + 2, w2_start + 3))
        e.append((w2_start + 4, w2_start + 5))

        f.append((w2_start, w2_start+1, w2_start+3, w2_start+2))
        f.append((w2_start+2, w2_start+3, w2_start+5, w2_start+4))

        # === YATAY KUYRUK ===
        hstab_x = -1.3
        hstab_span = 0.6
        hstab_chord = 0.35

        hs_start = len(v)
        v.append((hstab_x, 0.08, 0))                              # LE root sol
        v.append((hstab_x - hstab_chord, 0.08, 0))                # TE root sol
        v.append((hstab_x - 0.03, hstab_span, 0.02))              # LE tip sol
        v.append((hstab_x - hstab_chord + 0.05, hstab_span, 0.02))  # TE tip sol
        v.append((hstab_x, -0.08, 0))                             # LE root sag
        v.append((hstab_x - hstab_chord, -0.08, 0))               # TE root sag
        v.append((hstab_x - 0.03, -hstab_span, 0.02))             # LE tip sag
        v.append((hstab_x - hstab_chord + 0.05, -hstab_span, 0.02))  # TE tip sag

        e.append((hs_start, hs_start+2))    # LE sol
        e.append((hs_start+1, hs_start+3))  # TE sol
        e.append((hs_start, hs_start+1))    # root sol
        e.append((hs_start+2, hs_start+3))  # tip sol
        e.append((hs_start+4, hs_start+6))  # LE sag
        e.append((hs_start+5, hs_start+7))  # TE sag
        e.append((hs_start+4, hs_start+5))  # root sag
        e.append((hs_start+6, hs_start+7))  # tip sag

        f.append((hs_start, hs_start+2, hs_start+3, hs_start+1))
        f.append((hs_start+4, hs_start+5, hs_start+7, hs_start+6))

        # === DİKEY KUYRUK (Spitfire karakteristik dorsal fin) ===
        vtail_h = 0.45
        vtail_chord = 0.4

        v_start = len(v)
        v.append((hstab_x, 0, 0.08))                             # LE base
        v.append((hstab_x - vtail_chord, 0, 0.08))               # TE base
        v.append((hstab_x + 0.05, 0, vtail_h))                   # LE top (dorsal fin)
        v.append((hstab_x - vtail_chord + 0.1, 0, vtail_h * 0.7))  # TE top

        e.append((v_start, v_start+2))    # LE
        e.append((v_start+1, v_start+3))  # TE
        e.append((v_start, v_start+1))    # base
        e.append((v_start+2, v_start+3))  # top

        f.append((v_start, v_start+2, v_start+3, v_start+1))

        # === PERVANE ===
        prop_x = nose_x + 0.05
        prop_r = 0.35
        prop_w = 0.03

        p_start = len(v)
        v.append((prop_x, 0, prop_r))         # üst kanat
        v.append((prop_x, 0, -prop_r))        # alt kanat
        v.append((prop_x, prop_r, 0))          # sağ kanat
        v.append((prop_x, -prop_r, 0))         # sol kanat
        v.append((prop_x + prop_w, 0, prop_r * 0.8))
        v.append((prop_x + prop_w, 0, -prop_r * 0.8))
        v.append((prop_x + prop_w, prop_r * 0.8, 0))
        v.append((prop_x + prop_w, -prop_r * 0.8, 0))

        e.append((p_start, p_start+1))    # dikey kanat ön
        e.append((p_start+2, p_start+3))  # yatay kanat ön
        e.append((p_start+4, p_start+5))  # dikey kanat arka
        e.append((p_start+6, p_start+7))  # yatay kanat arka
        e.append((p_start, p_start+4))    # bağlantılar
        e.append((p_start+1, p_start+5))
        e.append((p_start+2, p_start+6))
        e.append((p_start+3, p_start+7))

        # === KOKPIT CAMI ===
        canopy_start_x = 0.8
        canopy_end_x = 0.1
        canopy_top_z = 0.22
        canopy_sides_y = 0.12

        c_start = len(v)
        v.append((canopy_start_x, 0, canopy_top_z))              # ön üst
        v.append((canopy_end_x, 0, canopy_top_z * 0.9))          # arka üst
        v.append((canopy_start_x, canopy_sides_y, 0.14))         # ön sağ
        v.append((canopy_end_x, canopy_sides_y * 0.9, 0.13))     # arka sağ
        v.append((canopy_start_x, -canopy_sides_y, 0.14))        # ön sol
        v.append((canopy_end_x, -canopy_sides_y * 0.9, 0.13))    # arka sol

        e.append((c_start, c_start+1))      # üst kenar
        e.append((c_start, c_start+2))      # ön sağ
        e.append((c_start, c_start+4))      # ön sol
        e.append((c_start+1, c_start+3))    # arka sağ
        e.append((c_start+1, c_start+5))    # arka sol
        e.append((c_start+2, c_start+3))    # sağ üst kenar
        e.append((c_start+4, c_start+5))    # sol üst kenar

        return v, e, f

    def rotate_point(self, point):
        """3D noktayı roll, pitch, yaw ile döndür"""
        x, y, z = point

        # Roll (X ekseni)
        cos_r, sin_r = math.cos(self.roll), math.sin(self.roll)
        y1 = y * cos_r - z * sin_r
        z1 = y * sin_r + z * cos_r

        # Pitch (Y ekseni)
        cos_p, sin_p = math.cos(self.pitch), math.sin(self.pitch)
        x2 = x * cos_p + z1 * sin_p
        z2 = -x * sin_p + z1 * cos_p

        # Yaw (Z ekseni)
        cos_y, sin_y = math.cos(self.yaw), math.sin(self.yaw)
        x3 = x2 * cos_y - y1 * sin_y
        y3 = x2 * sin_y + y1 * cos_y

        return (x3, y3, z2)

    def project(self, point, cx, cy, scale=200, distance=4):
        """3D -> 2D perspektif projeksiyon"""
        x, y, z = point
        z_offset = z + distance
        if z_offset < 0.1:
            z_offset = 0.1
        factor = scale / z_offset
        px = int(cx + x * factor)
        py = int(cy - y * factor)
        return (px, py)

    def update(self, aileron, elevator, rudder):
        """Kanal degerlerinden hedef acilari hesapla"""
        # Kanal degerlerini -1 ile 1 arasina cevir
        norm_ail = (aileron - SERVO_CENTER) / (SERVO_MAX - SERVO_MIN)
        norm_elev = (elevator - SERVO_CENTER) / (SERVO_MAX - SERVO_MIN)
        norm_rud = (rudder - SERVO_CENTER) / (SERVO_MAX - SERVO_MIN)

        # Hedef acilar (radyan)
        target_roll = -norm_ail * math.radians(60)
        target_pitch = norm_elev * math.radians(30)
        target_yaw = -norm_rud * math.radians(45)

        # Yumuşak geçiş (lerp)
        smooth = 0.1
        self.roll += (target_roll - self.roll) * smooth
        self.pitch += (target_pitch - self.pitch) * smooth
        self.yaw += (target_yaw - self.yaw) * smooth

    def draw(self, screen, cx, cy, scale=200):
        """Ucagi solid render + ışıklandırma ile ciz"""
        transformed = [self.rotate_point(v) for v in self.vertices]

        # Işık yönü (yukarı-sağ-ön, normalize)
        light = (0.4, 0.6, 0.7)
        ll = math.sqrt(light[0]**2 + light[1]**2 + light[2]**2)
        light = (light[0]/ll, light[1]/ll, light[2]/ll)

        def avg_depth(face):
            return sum(transformed[i][2] for i in face) / len(face)

        def face_normal(face):
            if len(face) < 3:
                return (0, 0, 1)
            p0 = transformed[face[0]]
            p1 = transformed[face[1]]
            p2 = transformed[face[2]]
            ux, uy, uz = p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2]
            vx, vy, vz = p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2]
            nx = uy*vz - uz*vy
            ny = uz*vx - ux*vz
            nz = ux*vy - uy*vx
            nl = math.sqrt(nx*nx + ny*ny + nz*nz)
            if nl < 0.001:
                return (0, 0, 1)
            return (nx/nl, ny/nl, nz/nl)

        sorted_faces = sorted(self.faces, key=lambda f: avg_depth(f), reverse=True)

        # Solid face render
        for face in sorted_faces:
            points = [self.project(transformed[i], cx, cy, scale) for i in face]
            normal = face_normal(face)
            avg_z = avg_depth(face)

            # Diffuse lighting
            dot = normal[0]*light[0] + normal[1]*light[1] + normal[2]*light[2]
            diffuse = max(0, dot)

            # Ambient + diffuse
            ambient = 0.25
            brightness = ambient + diffuse * 0.75
            brightness = min(1.0, brightness)

            # Spitfire kamuflaj renkleri
            if avg_z > 0:
                # Üst: koyu yeşil kamuflaj
                r = int(45 * brightness)
                g = int(85 * brightness)
                b = int(35 * brightness)
            else:
                # Alt: açık gri/mavi
                r = int(140 * brightness)
                g = int(145 * brightness)
                b = int(155 * brightness)

            color = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))

            pygame.draw.polygon(screen, color, points)
            # Kenar çizgisi (hafif)
            edge_brightness = int(100 + brightness * 80)
            pygame.draw.polygon(screen, (edge_brightness, edge_brightness, edge_brightness + 10), points, 1)

        # Navigation lights (kılavuz lambaları)
        # Sol kanat ucu: kırmızı
        for i, v in enumerate(transformed):
            if abs(v[1] - 1.6) < 0.1 and v[0] < 0:
                p = self.project(v, cx, cy, scale)
                pygame.draw.circle(screen, (255, 30, 0), p, 3)
            elif abs(v[1] + 1.6) < 0.1 and v[0] < 0:
                p = self.project(v, cx, cy, scale)
                pygame.draw.circle(screen, (0, 200, 50), p, 3)

        # Wireframe overlay (hafif)
        for edge in self.edges:
            p1 = self.project(transformed[edge[0]], cx, cy, scale)
            p2 = self.project(transformed[edge[1]], cx, cy, scale)
            z1 = transformed[edge[0]][2]
            z2 = transformed[edge[1]][2]
            avg_z = (z1 + z2) / 2
            brightness = max(60, min(160, int(100 + avg_z * 25)))
            pygame.draw.line(screen, (brightness, brightness, brightness + 5), p1, p2, 1)

        # Zemin gölgesi
        shadow_y = cy + 100
        shadow_w = int(scale * 0.6)
        shadow_h = int(scale * 0.12)
        shadow_surf = pygame.Surface((shadow_w * 2, shadow_h * 2), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow_surf, (0, 0, 0, 50), (0, 0, shadow_w * 2, shadow_h * 2))
        screen.blit(shadow_surf, (cx - shadow_w, shadow_y - shadow_h))


class HUDRenderer:
    """PyGame tabanli HUD cizici"""

    def __init__(self, screen):
        self.screen = screen
        # Fontlar
        self.font_large = pygame.font.Font(None, 48)
        self.font_medium = pygame.font.Font(None, 32)
        self.font_small = pygame.font.Font(None, 24)
        self.font_tiny = pygame.font.Font(None, 20)

        # Arka plan gradient cache
        self.bg_surface = pygame.Surface((WIDTH, HEIGHT))
        for y in range(HEIGHT):
            t = y / HEIGHT
            r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
            g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
            b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
            pygame.draw.line(self.bg_surface, (r, g, b), (0, y), (WIDTH, y))

    def draw_background(self):
        """Gradient arka plan ciz"""
        self.screen.blit(self.bg_surface, (0, 0))

    def draw_panel(self, x, y, w, h, title=None):
        """Glassmorphism panel ciz"""
        # Yarim saydam arka plan
        panel_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        panel_surf.fill((PANEL_BG[0], PANEL_BG[1], PANEL_BG[2], 200))
        self.screen.blit(panel_surf, (x, y))

        # Glow kenar (dis cerceve)
        for i in range(3):
            alpha = 25 - i * 8
            glow_surf = pygame.Surface((w + 4 + i*2, h + 4 + i*2), pygame.SRCALPHA)
            glow_surf.fill((ACCENT_CYAN[0], ACCENT_CYAN[1], ACCENT_CYAN[2], alpha))
            self.screen.blit(glow_surf, (x - 2 - i, y - 2 - i))

        # Ic cerceve
        pygame.draw.rect(self.screen, PANEL_BORDER, (x, y, w, h), 1)

        # Köşe vurguları
        corner_len = 12
        corner_color = ACCENT_CYAN
        # Sol ust
        pygame.draw.line(self.screen, corner_color, (x, y), (x + corner_len, y), 2)
        pygame.draw.line(self.screen, corner_color, (x, y), (x, y + corner_len), 2)
        # Sag ust
        pygame.draw.line(self.screen, corner_color, (x + w, y), (x + w - corner_len, y), 2)
        pygame.draw.line(self.screen, corner_color, (x + w, y), (x + w, y + corner_len), 2)
        # Sol alt
        pygame.draw.line(self.screen, corner_color, (x, y + h), (x + corner_len, y + h), 2)
        pygame.draw.line(self.screen, corner_color, (x, y + h), (x, y + h - corner_len), 2)
        # Sag alt
        pygame.draw.line(self.screen, corner_color, (x + w, y + h), (x + w - corner_len, y + h), 2)
        pygame.draw.line(self.screen, corner_color, (x + w, y + h), (x + w, y + h - corner_len), 2)

        if title:
            title_surf = self.font_small.render(title, True, ACCENT_CYAN)
            self.screen.blit(title_surf, (x + 10, y + 5))
            # Altinda separator cizgi
            sep_w = title_surf.get_width() + 4
            pygame.draw.line(self.screen, ACCENT_CYAN, (x + 10, y + 22), (x + 10 + sep_w, y + 22), 1)

    def draw_glow_line(self, x1, y1, x2, y2, color=ACCENT_CYAN, width=1):
        """Glow efektli cizgi"""
        # Arka glow
        for i in range(3, 0, -1):
            alpha = 20 // i
            glow_surf = pygame.Surface((abs(x2 - x1) + 6, abs(y2 - y1) + 6), pygame.SRCALPHA)
            glow_surf.fill((color[0], color[1], color[2], alpha))
            self.screen.blit(glow_surf, (min(x1, x2) - 3, min(y1, y2) - 3))
        pygame.draw.line(self.screen, color, (x1, y1), (x2, y2), width)

    def draw_panel(self, x, y, w, h, title=None):
        """Arka plan paneli ciz"""
        pygame.draw.rect(self.screen, PANEL_BG, (x, y, w, h))
        pygame.draw.rect(self.screen, DARK_GRAY, (x, y, w, h), 2)
        if title:
            title_surf = self.font_small.render(title, True, CYAN)
            self.screen.blit(title_surf, (x + 8, y + 4))

    def draw_artificial_horizon(self, cx, cy, radius, roll_angle, pitch_offset):
        """Sanal ufuk cizgisi"""
        # Arka plan (gokyuzu/yer)
        surface = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)

        pygame.draw.circle(surface, (30, 30, 30, 255), (radius, radius), radius)

        # Roll dondurme merkezi
        roll_rad = math.radians(roll_angle)

        # Ufuk cizgisi
        pitch_pixels = pitch_offset * radius * 0.8
        horizon_y = radius + pitch_pixels

        # Kesisim noktalarini hesapla
        cos_r = math.cos(roll_rad)
        sin_r = math.sin(roll_rad)

        # Clip daire icinde
        clip_rect = pygame.Rect(cx - radius, cy - radius, radius * 2, radius * 2)
        old_clip = self.screen.get_clip()
        self.screen.set_clip(clip_rect)

        # Gokyuzu yarisi
        sky_points = []
        ground_points = []
        for angle_deg in range(0, 361, 2):
            a = math.radians(angle_deg)
            px = cx + math.cos(a) * radius
            py = cy + math.sin(a) * radius
            # Ufuk cizgisine gore
            dy = (py - cy) * cos_r - (px - cx) * sin_r
            if dy < pitch_pixels:
                sky_points.append((px, py))
            else:
                ground_points.append((px, py))

        if len(sky_points) >= 3:
            pygame.draw.polygon(self.screen, (40, 80, 160), sky_points)
        if len(ground_points) >= 3:
            pygame.draw.polygon(self.screen, (100, 70, 30), ground_points)

        # Ufuk cizgisi
        line_half = radius * 1.5
        x1 = cx - line_half * cos_r
        y1 = cy - line_half * sin_r + pitch_pixels
        x2 = cx + line_half * cos_r
        y2 = cy + line_half * sin_r + pitch_pixels
        pygame.draw.line(self.screen, WHITE, (int(x1), int(y1)), (int(x2), int(y2)), 2)

        self.screen.set_clip(old_clip)

        # Cerceve
        pygame.draw.circle(self.screen, WHITE, (cx, cy), radius, 2)

        # Merkez isareti
        mark_size = 12
        pygame.draw.line(self.screen, ORANGE,
                         (cx - mark_size, cy), (cx - 4, cy), 2)
        pygame.draw.line(self.screen, ORANGE,
                         (cx + 4, cy), (cx + mark_size, cy), 2)
        pygame.draw.line(self.screen, ORANGE,
                         (cx, cy), (cx, cy - 4), 2)

    def draw_channel_bar(self, x, y, w, h, value, label, color=HUD_GREEN):
        """Gradient kanal gostergesi"""
        # Arka plan
        bg_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        bg_surf.fill((BAR_BG[0], BAR_BG[1], BAR_BG[2], 220))
        self.screen.blit(bg_surf, (x, y))

        # Deger cubugu (yatay gradient)
        normalized = (value - SERVO_MIN) / (SERVO_MAX - SERVO_MIN)
        bar_w = int(normalized * w)
        if bar_w > 0:
            bar_surf = pygame.Surface((bar_w, h), pygame.SRCALPHA)
            for bx in range(bar_w):
                t = bx / w
                r = int(color[0] * 0.3 + color[0] * 0.7 * t)
                g = int(color[1] * 0.3 + color[1] * 0.7 * t)
                b = int(color[2] * 0.3 + color[2] * 0.7 * t)
                pygame.draw.line(bar_surf, (r, g, b, 200), (bx, 0), (bx, h))
            self.screen.blit(bar_surf, (x, y))

        # Merkez isareti (noktalı)
        center_x = x + w // 2
        for dy in range(0, h, 4):
            pygame.draw.line(self.screen, (80, 90, 110), (center_x, y + dy), (center_x, y + dy + 2), 1)

        # Cerceve
        pygame.draw.rect(self.screen, PANEL_BORDER, (x, y, w, h), 1)

        # Etiket
        label_surf = self.font_tiny.render(label, True, TEXT_DIM)
        self.screen.blit(label_surf, (x + 5, y + 3))

        # Deger metni (sagda, parlak)
        val_surf = self.font_tiny.render(str(int(value)), True, TEXT_BRIGHT)
        self.screen.blit(val_surf, (x + w - 50, y + 3))

    def draw_throttle_bar(self, x, y, w, h, value):
        """Dikey gradient throttle cubugu"""
        bg_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        bg_surf.fill((BAR_BG[0], BAR_BG[1], BAR_BG[2], 220))
        self.screen.blit(bg_surf, (x, y))

        normalized = (value - THROTTLE_MIN) / (THROTTLE_MAX - THROTTLE_MIN)
        bar_h = int(normalized * h)
        bar_y = y + h - bar_h

        if bar_h > 0:
            bar_surf = pygame.Surface((w, bar_h), pygame.SRCALPHA)
            for by in range(bar_h):
                t = by / h
                r = int(0 + 255 * t)
                g = int(255 * (1 - t * 0.6))
                b = int(20 * t)
                pygame.draw.line(bar_surf, (r, g, b, 200), (0, by), (w, by))
            self.screen.blit(bar_surf, (x, bar_y))

        pygame.draw.rect(self.screen, PANEL_BORDER, (x, y, w, h), 1)

        label = self.font_tiny.render("THR", True, TEXT_DIM)
        self.screen.blit(label, (x + w // 2 - 12, y + h + 4))

        pct = self.font_tiny.render(f"{int(normalized * 100)}%", True, TEXT_BRIGHT)
        self.screen.blit(pct, (x + w // 2 - 12, y - 18))

    def draw_battery_gauge(self, x, y, w, h, voltage, percent, critical):
        """Profesyonel pil voltaj gostergesi"""
        self.draw_panel(x, y, w, h, "PIL")

        # Pil seviyesi cubugu
        bar_x = x + 10
        bar_y = y + 30
        bar_w = w - 20
        bar_h = 28

        bg_surf = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
        bg_surf.fill((BAR_BG[0], BAR_BG[1], BAR_BG[2], 200))
        self.screen.blit(bg_surf, (bar_x, bar_y))

        fill_w = int((percent / 100) * bar_w)
        if critical:
            color = ACCENT_RED
        elif percent < 30:
            color = ACCENT_ORANGE
        else:
            color = ACCENT_GREEN
        if fill_w > 0:
            bar_surf = pygame.Surface((fill_w, bar_h), pygame.SRCALPHA)
            for bx in range(fill_w):
                t = bx / bar_w
                r = int(color[0] * 0.5 + color[0] * 0.5 * t)
                g = int(color[1] * 0.5 + color[1] * 0.5 * t)
                b = int(color[2] * 0.5 + color[2] * 0.5 * t)
                pygame.draw.line(bar_surf, (r, g, b, 200), (bx, 0), (bx, bar_h))
            self.screen.blit(bar_surf, (bar_x, bar_y))
        pygame.draw.rect(self.screen, PANEL_BORDER, (bar_x, bar_y, bar_w, bar_h), 1)

        # Voltaj metni
        v_text = self.font_medium.render(f"{voltage:.1f}V", True, TEXT_BRIGHT)
        self.screen.blit(v_text, (x + 10, bar_y + bar_h + 6))

        pct_text = self.font_medium.render(f"{int(percent)}%", True, color)
        self.screen.blit(pct_text, (x + w - 65, bar_y + bar_h + 6))

    def draw_signal_gauge(self, x, y, w, h, rssi, connected):
        """Profesyonel sinyal gucu gostergesi"""
        self.draw_panel(x, y, w, h, "SINYAL")

        # Sinyal cubuklari
        bar_count = 5
        bar_w = (w - 40) // bar_count
        bar_max_h = 36
        for i in range(bar_count):
            bx = x + 15 + i * (bar_w + 5)
            bh = int((i + 1) / bar_count * bar_max_h)
            by = y + 30 + bar_max_h - bh

            threshold = (i + 1) / bar_count * 100
            if rssi >= threshold and connected:
                if i < 2:
                    color = ACCENT_RED
                elif i < 4:
                    color = ACCENT_ORANGE
                else:
                    color = ACCENT_GREEN
            else:
                color = (35, 38, 50)
            pygame.draw.rect(self.screen, color, (bx, by, bar_w - 3, bh))

        rssi_text = self.font_medium.render(f"{rssi}%", True, TEXT_BRIGHT)
        self.screen.blit(rssi_text, (x + 10, y + h - 28))

        if connected:
            conn_text = self.font_small.render("BAGLI", True, ACCENT_GREEN)
        else:
            conn_text = self.font_small.render("BAGLI DEGIL", True, ACCENT_RED)
        self.screen.blit(conn_text, (x + w - 80, y + h - 26))

    def draw_mini_joystick(self, cx, cy, radius, x_val, y_val, label):
        """Profesyonel mini joystick gostergesi"""
        # Yarim saydam arka plan
        bg_surf = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(bg_surf, (BAR_BG[0], BAR_BG[1], BAR_BG[2], 180), (radius + 2, radius + 2), radius)
        self.screen.blit(bg_surf, (cx - radius - 2, cy - radius - 2))

        # Capraz cizgiler
        pygame.draw.line(self.screen, (50, 55, 70),
                         (cx - radius, cy), (cx + radius, cy), 1)
        pygame.draw.line(self.screen, (50, 55, 70),
                         (cx, cy - radius), (cx, cy + radius), 1)
        pygame.draw.circle(self.screen, PANEL_BORDER, (cx, cy), radius, 1)

        # Joystick topu pozisyonu
        norm_x = (x_val - SERVO_MIN) / (SERVO_MAX - SERVO_MIN) * 2 - 1
        norm_y = (y_val - SERVO_MIN) / (SERVO_MAX - SERVO_MIN) * 2 - 1

        ball_x = cx + int(norm_x * radius * 0.8)
        ball_y = cy + int(norm_y * radius * 0.8)

        # Glow efekti
        glow_surf = pygame.Surface((24, 24), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (ACCENT_GREEN[0], ACCENT_GREEN[1], ACCENT_GREEN[2], 40), (12, 12), 12)
        self.screen.blit(glow_surf, (ball_x - 12, ball_y - 12))

        pygame.draw.circle(self.screen, ACCENT_GREEN, (ball_x, ball_y), 6)

        label_surf = self.font_tiny.render(label, True, ACCENT_CYAN)
        self.screen.blit(label_surf, (cx - 15, cy + radius + 4))

    def draw_flight_timer(self, x, y, elapsed_sec):
        """Profesyonel ucus suresi sayaci"""
        hours = int(elapsed_sec // 3600)
        minutes = int((elapsed_sec % 3600) // 60)
        seconds = int(elapsed_sec % 60)
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        label = self.font_tiny.render("UCUS SURESI", True, ACCENT_CYAN)
        self.screen.blit(label, (x, y - 18))

        timer_text = self.font_large.render(time_str, True, TEXT_BRIGHT)
        self.screen.blit(timer_text, (x, y))

    def draw_failsafe_warning(self, cx, cy, active):
        """Failsafe uyari ekrani"""
        if not active:
            return
        # Yarim saydam kirmizi overlay
        overlay = pygame.Surface((300, 80), pygame.SRCALPHA)
        overlay.fill((255, 0, 0, 180))
        self.screen.blit(overlay, (cx - 150, cy - 40))

        warning = self.font_large.render("! FAILSAFE !", True, WHITE)
        self.screen.blit(warning, (cx - warning.get_width() // 2, cy - 20))

        sub = self.font_small.render("Sinyal kaybi - Guvenli mod", True, WHITE)
        self.screen.blit(sub, (cx - sub.get_width() // 2, cy + 15))

    def draw_connection_status(self, x, y, serial_comm):
        """Profesyonel baglanti durumu"""
        if serial_comm.connected:
            status_text = f"TX: {serial_comm.port}"
            color = ACCENT_GREEN
        else:
            status_text = "Arduino bagli degil"
            color = ACCENT_RED

        status_surf = self.font_small.render(status_text, True, color)
        self.screen.blit(status_surf, (x, y))

        tx_text = self.font_tiny.render(f"TX: {serial_comm.tx_count} | RX: {serial_comm.rx_count}", True, TEXT_DIM)
        self.screen.blit(tx_text, (x, y + 20))

    def draw_button(self, cx, cy, radius, label, pressed, color_normal, color_pressed):
        """Profesyonel buton ciz"""
        color = color_pressed if pressed else color_normal

        if pressed:
            # Glow efekti
            glow_surf = pygame.Surface((radius * 3, radius * 3), pygame.SRCALPHA)
            pygame.draw.circle(glow_surf, (color[0], color[1], color[2], 50), (radius * 3 // 2, radius * 3 // 2), radius + 4)
            self.screen.blit(glow_surf, (cx - radius * 3 // 2, cy - radius * 3 // 2))

        pygame.draw.circle(self.screen, color, (cx, cy), radius)
        border = PANEL_BORDER if not pressed else color
        pygame.draw.circle(self.screen, border, (cx, cy), radius, 2)
        label_surf = self.font_small.render(label, True, WHITE if pressed else TEXT_DIM)
        self.screen.blit(label_surf, (cx - label_surf.get_width() // 2, cy - label_surf.get_height() // 2))

    def draw_steam_deck_buttons(self, cx, cy, button_states):
        """Profesyonel Steam Deck buton takimi"""
        self.draw_panel(cx - 120, cy - 100, 240, 200, "TUSLAR")

        # Renkler
        green_normal = (30, 60, 30)
        green_pressed = (0, 220, 0)
        red_normal = (60, 30, 30)
        red_pressed = (220, 0, 0)
        blue_normal = (30, 30, 60)
        blue_pressed = (0, 100, 220)
        yellow_normal = (60, 60, 30)
        yellow_pressed = (220, 220, 0)
        gray_normal = (40, 42, 55)
        gray_pressed = (120, 125, 140)
        shoulder_normal = (35, 38, 50)
        shoulder_pressed = (100, 105, 120)

        btn_r = 18
        center_y = cy + 10

        # L1 / R1
        self.draw_button(cx - 80, cy - 60, 16, "L1", button_states.get('L1', False), shoulder_normal, shoulder_pressed)
        self.draw_button(cx + 80, cy - 60, 16, "R1", button_states.get('R1', False), shoulder_normal, shoulder_pressed)

        # Select / Start
        self.draw_button(cx - 30, center_y - 20, 12, "Sel", button_states.get('Select', False), gray_normal, gray_pressed)
        self.draw_button(cx + 30, center_y - 20, 12, "Str", button_states.get('Start', False), gray_normal, gray_pressed)

        # D-Pad (sol taraf)
        dpad_x = cx - 60
        dpad_y = center_y + 30
        self.draw_button(dpad_x, dpad_y - 28, 12, "^", button_states.get('D-Up', False), gray_normal, gray_pressed)
        self.draw_button(dpad_x, dpad_y + 28, 12, "v", button_states.get('D-Down', False), gray_normal, gray_pressed)
        self.draw_button(dpad_x - 28, dpad_y, 12, "<", button_states.get('D-Left', False), gray_normal, gray_pressed)
        self.draw_button(dpad_x + 28, dpad_y, 12, ">", button_states.get('D-Right', False), gray_normal, gray_pressed)

        # A, B, X, Y (sag taraf)
        abxy_x = cx + 60
        abxy_y = center_y + 30
        self.draw_button(abxy_x, abxy_y - 28, btn_r, "Y", button_states.get('Y', False), yellow_normal, yellow_pressed)
        self.draw_button(abxy_x, abxy_y + 28, btn_r, "B", button_states.get('B', False), red_normal, red_pressed)
        self.draw_button(abxy_x - 28, abxy_y, btn_r, "X", button_states.get('X', False), blue_normal, blue_pressed)
        self.draw_button(abxy_x + 28, abxy_y, btn_r, "A", button_states.get('A', False), green_normal, green_pressed)

    def draw_compass_strip(self, x, y, w, h, yaw_deg):
        """Pusula heading strip - yatay bantt"""
        self.draw_panel(x, y, w, h, None)

        # Arka plan
        bg_surf = pygame.Surface((w - 4, h - 4), pygame.SRCALPHA)
        bg_surf.fill((8, 10, 18, 230))
        self.screen.blit(bg_surf, (x + 2, y + 2))

        # Yön etiketleri
        directions = {
            0: "N", 45: "NE", 90: "E", 135: "SE",
            180: "S", 225: "SW", 270: "W", 315: "NW"
        }

        # Normalleştir 0-360
        heading = yaw_deg % 360
        if heading < 0:
            heading += 360

        center_x = x + w // 2
        pixels_per_deg = (w - 20) / 90  # 90° görüş açısı

        for deg_offset in range(-50, 51, 5):
            tick_deg = (heading + deg_offset) % 360
            tick_x = center_x + int(deg_offset * pixels_per_deg)

            if tick_x < x + 5 or tick_x > x + w - 5:
                continue

            is_major = (int(tick_deg) % 30 == 0)
            is_cardinal = (int(tick_deg) % 90 == 0)

            if is_cardinal:
                tick_h = 12
                color = ACCENT_CYAN
                label = directions.get(int(tick_deg), "")
                if label:
                    label_surf = self.font_small.render(label, True, color)
                    self.screen.blit(label_surf, (tick_x - label_surf.get_width() // 2, y + 4))
                pygame.draw.line(self.screen, color, (tick_x, y + 20), (tick_x, y + 20 + tick_h), 2)
            elif is_major:
                tick_h = 8
                color = (120, 130, 150)
                label = directions.get(int(tick_deg), str(int(tick_deg)))
                label_surf = self.font_tiny.render(label, True, color)
                self.screen.blit(label_surf, (tick_x - label_surf.get_width() // 2, y + 5))
                pygame.draw.line(self.screen, color, (tick_x, y + 18), (tick_x, y + 18 + tick_h), 1)
            else:
                tick_h = 4
                color = (60, 65, 80)
                pygame.draw.line(self.screen, color, (tick_x, y + 20), (tick_x, y + 20 + tick_h), 1)

        # Merkez isareti (ok)
        pygame.draw.polygon(self.screen, ACCENT_ORANGE, [
            (center_x, y + h - 3),
            (center_x - 5, y + h - 12),
            (center_x + 5, y + h - 12)
        ])

        # Heading degeri (sag alt)
        hdg_text = self.font_tiny.render(f"HDG {int(heading)}°", True, TEXT_BRIGHT)
        self.screen.blit(hdg_text, (x + w - 60, y + h - 18))

    def draw_vsi(self, cx, cy, radius, elevator_value):
        """VSI - Vertical Speed Indicator (dikey hiz gostergesi)"""
        # Arka plan
        bg_surf = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(bg_surf, (PANEL_BG[0], PANEL_BG[1], PANEL_BG[2], 220), (radius + 2, radius + 2), radius + 2)
        self.screen.blit(bg_surf, (cx - radius - 2, cy - radius - 2))
        pygame.draw.circle(self.screen, PANEL_BORDER, (cx, cy), radius, 1)

        # Daire dilimleri (tırmanma/soluk)
        for angle_deg in range(-120, 121, 30):
            a = math.radians(angle_deg - 90)
            x1 = cx + int(math.cos(a) * (radius - 12))
            y1 = cy + int(math.sin(a) * (radius - 12))
            x2 = cx + int(math.cos(a) * (radius - 6))
            y2 = cy + int(math.sin(a) * (radius - 6))
            pygame.draw.line(self.screen, (80, 90, 110), (x1, y1), (x2, y2), 1)

        # Etiketler
        up_label = self.font_tiny.render("UP", True, ACCENT_GREEN)
        dn_label = self.font_tiny.render("DN", True, ACCENT_RED)
        self.screen.blit(up_label, (cx + 6, cy - radius + 4))
        self.screen.blit(dn_label, (cx + 6, cy + radius - 18))

        # İğne
        norm = (elevator_value - SERVO_CENTER) / (SERVO_MAX - SERVO_MIN)
        needle_angle = math.radians(norm * 120 - 90)
        nx = cx + int(math.cos(needle_angle) * (radius - 16))
        ny = cy + int(math.sin(needle_angle) * (radius - 16))
        pygame.draw.line(self.screen, WHITE, (cx, cy), (nx, ny), 2)
        pygame.draw.circle(self.screen, (80, 85, 100), (cx, cy), 4)

        # Başlık
        title = self.font_tiny.render("VSI", True, ACCENT_CYAN)
        self.screen.blit(title, (cx - title.get_width() // 2, cy + radius - 2))


class GroundStation:
    """Ana uygulama"""

    def __init__(self):
        pygame.init()
        pygame.joystick.init()

        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("RC Ucak Yer Istasyonu")
        self.clock = pygame.time.Clock()

        self.hud = HUDRenderer(self.screen)
        self.serial_comm = SerialComm()
        self.telemetry = TelemetryData()
        self.flight_log = None

        # 3D Ucak Simulatörü
        self.aircraft_sim = AircraftSimulator()

        # Joystick
        self.joystick = None
        self.init_joystick()

        # Kanal degerleri
        self.channels = {
            'aileron': SERVO_CENTER,
            'elevator': SERVO_CENTER,
            'rudder': SERVO_CENTER,
            'throttle': THROTTLE_MIN
        }

        # Ayarlar
        self.axis_map = {}  # Axis index -> kanal adi
        self.auto_connect = True
        self.send_rate = 50  # Hz
        self.last_send = 0
        self.flight_start = time.time()
        self.running = True

        # Steam Deck buton durumlari
        self.button_states = {
            'A': False, 'B': False, 'X': False, 'Y': False,
            'L1': False, 'R1': False, 'L2': False, 'R2': False,
            'D-Up': False, 'D-Down': False, 'D-Left': False, 'D-Right': False,
            'Start': False, 'Select': False
        }

        # Joystick ayar dosyasi yukle veya varsayilani kullan
        self.load_joystick_config()

    def init_joystick(self):
        """Joystick baslat"""
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            print(f"Joystick bulundu: {self.joystick.get_name()}")
            print(f"  Axes: {self.joystick.get_numaxes()}")
            print(f"  Buttons: {self.joystick.get_numbuttons()}")
        else:
            print("Joystick bulunamadi!")

    def load_joystick_config(self):
        """Joystick eksen eslestirmesini yukle"""
        # Steam Deck icin varsayilan harita
        # Sol cubuk: soldan saga = aileron, ileri geri = elevator
        # Sag cubuk: soldan saga = rudder, ileri geri = throttle
        config_path = Path(__file__).parent / "joystick_config.json"

        if config_path.exists():
            import json
            with open(config_path) as f:
                config = json.load(f)
                self.axis_map = config.get('axis_map', {})
        else:
            # Steam Deck varsayilani
            # axis index: {"channel": "aileron", "invert": False}
            self.axis_map = {
                "0": {"channel": "aileron", "invert": False},    # Sol X
                "1": {"channel": "elevator", "invert": True},    # Sol Y (ters)
                "3": {"channel": "rudder", "invert": False},     # Sag X
                "4": {"channel": "throttle", "invert": True},    # Sag Y (ters)
            }

    def save_joystick_config(self):
        """Joystick ayarini kaydet"""
        import json
        config_path = Path(__file__).parent / "joystick_config.json"
        with open(config_path, 'w') as f:
            json.dump({'axis_map': self.axis_map}, f, indent=2)

    def read_joystick(self):
        """Joystick degerlerini oku ve kanallara ata. Joystick yoksa klavye ok tuslari."""
        if self.joystick:
            for axis_str, mapping in self.axis_map.items():
                axis_idx = int(axis_str)
                if axis_idx >= self.joystick.get_numaxes():
                    continue

                raw_value = self.joystick.get_axis(axis_idx)
                if mapping.get('invert', False):
                    raw_value = -raw_value

                channel = mapping['channel']
                if channel == 'throttle':
                    # Throttle: -1 -> 1000, +1 -> 2000
                    value = THROTTLE_MIN + (raw_value + 1) / 2.0 * (THROTTLE_MAX - THROTTLE_MIN)
                else:
                    # Servo kanallari: -1 -> 1000, 0 -> 1500, +1 -> 2000
                    value = SERVO_MIN + (raw_value + 1) / 2.0 * (SERVO_MAX - SERVO_MIN)

                self.channels[channel] = value
        else:
            # Klavye ok tuslari ile test kontrolu
            keys = pygame.key.get_pressed()
            step = 20

            # Aileron (Sol/Sag ok)
            if keys[pygame.K_LEFT]:
                self.channels['aileron'] = max(SERVO_MIN, self.channels['aileron'] - step)
            elif keys[pygame.K_RIGHT]:
                self.channels['aileron'] = min(SERVO_MAX, self.channels['aileron'] + step)
            else:
                # Merkeze don
                if self.channels['aileron'] < SERVO_CENTER:
                    self.channels['aileron'] = min(SERVO_CENTER, self.channels['aileron'] + step)
                elif self.channels['aileron'] > SERVO_CENTER:
                    self.channels['aileron'] = max(SERVO_CENTER, self.channels['aileron'] - step)

            # Elevator (Ileri/Geri ok)
            if keys[pygame.K_UP]:
                self.channels['elevator'] = min(SERVO_MAX, self.channels['elevator'] + step)
            elif keys[pygame.K_DOWN]:
                self.channels['elevator'] = max(SERVO_MIN, self.channels['elevator'] - step)
            else:
                if self.channels['elevator'] < SERVO_CENTER:
                    self.channels['elevator'] = min(SERVO_CENTER, self.channels['elevator'] + step)
                elif self.channels['elevator'] > SERVO_CENTER:
                    self.channels['elevator'] = max(SERVO_CENTER, self.channels['elevator'] - step)

            # Rudder (Z/X tuslari)
            if keys[pygame.K_z]:
                self.channels['rudder'] = max(SERVO_MIN, self.channels['rudder'] - step)
            elif keys[pygame.K_x]:
                self.channels['rudder'] = min(SERVO_MAX, self.channels['rudder'] + step)
            else:
                if self.channels['rudder'] < SERVO_CENTER:
                    self.channels['rudder'] = min(SERVO_CENTER, self.channels['rudder'] + step)
                elif self.channels['rudder'] > SERVO_CENTER:
                    self.channels['rudder'] = max(SERVO_CENTER, self.channels['rudder'] - step)

            # Throttle (W/S tuslari)
            if keys[pygame.K_w]:
                self.channels['throttle'] = min(THROTTLE_MAX, self.channels['throttle'] + step)
            elif keys[pygame.K_s]:
                self.channels['throttle'] = max(THROTTLE_MIN, self.channels['throttle'] - step)

    def send_control(self):
        """Kontrol komutunu gonder"""
        now = time.time()
        if now - self.last_send < 1.0 / self.send_rate:
            return
        self.last_send = now

        self.serial_comm.send_control(
            self.channels['aileron'],
            self.channels['elevator'],
            self.channels['rudder'],
            self.channels['throttle']
        )

    def handle_events(self):
        """PyGame olaylarini isle"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_c:
                    # Manuel baglan
                    if not self.serial_comm.connected:
                        self.serial_comm.connect()
                elif event.key == pygame.K_d:
                    # Baglanti kes
                    self.serial_comm.disconnect()
                elif event.key == pygame.K_r:
                    # Joystick yenile
                    self.init_joystick()
                elif event.key == pygame.K_l:
                    # Log baslat/durdur
                    if self.flight_log is None:
                        self.flight_log = FlightLog()
                        print("Ucus kaydi basladi")
                    else:
                        self.flight_log.close()
                        self.flight_log = None
                        print("Ucus kaydi durduruldu")

            elif event.type == pygame.JOYBUTTONDOWN:
                # Steam Deck butonlari
                if event.button == 0:  # A - Baglan
                    self.button_states['A'] = True
                    if not self.serial_comm.connected:
                        self.serial_comm.connect()
                elif event.button == 1:  # B - Kes
                    self.button_states['B'] = True
                    self.serial_comm.disconnect()
                elif event.button == 2:  # X - Joystick yenile
                    self.button_states['X'] = True
                    self.init_joystick()
                elif event.button == 3:  # Y - Log baslat/durdur
                    self.button_states['Y'] = True
                    if self.flight_log is None:
                        self.flight_log = FlightLog()
                        print("Ucus kaydi basladi")
                    else:
                        self.flight_log.close()
                        self.flight_log = None
                        print("Ucus kaydi durduruldu")
                elif event.button == 4:  # L1
                    self.button_states['L1'] = True
                elif event.button == 5:  # R1
                    self.button_states['R1'] = True
                elif event.button == 6:  # Select
                    self.button_states['Select'] = True
                elif event.button == 7:  # Menu (Start) - Cikis
                    self.button_states['Start'] = True
                    self.running = False

            elif event.type == pygame.JOYBUTTONUP:
                if event.button == 0:
                    self.button_states['A'] = False
                elif event.button == 1:
                    self.button_states['B'] = False
                elif event.button == 2:
                    self.button_states['X'] = False
                elif event.button == 3:
                    self.button_states['Y'] = False
                elif event.button == 4:
                    self.button_states['L1'] = False
                elif event.button == 5:
                    self.button_states['R1'] = False
                elif event.button == 6:
                    self.button_states['Select'] = False
                elif event.button == 7:
                    self.button_states['Start'] = False

            elif event.type == pygame.JOYDEVICEADDED:
                self.init_joystick()
            elif event.type == pygame.JOYDEVICEREMOVED:
                self.joystick = None

    def draw(self):
        """Ana ekran cizimi"""
        # Gradient arka plan
        self.hud.draw_background()

        # === Merkez: 3D Ucak Simulasyonu ===
        self.aircraft_sim.update(
            self.channels['aileron'],
            self.channels['elevator'],
            self.channels['rudder']
        )

        # Simulasyon paneli
        sim_cx = 380
        sim_cy = 310
        self.hud.draw_panel(sim_cx - 190, sim_cy - 190, 380, 380, "UCAK GORUNUMU")
        # Karanlık arka plan
        sim_bg = pygame.Surface((370, 350), pygame.SRCALPHA)
        sim_bg.fill((5, 8, 15, 230))
        self.screen.blit(sim_bg, (sim_cx - 185, sim_cy - 165))

        # Perspective grid cizgileri
        for i in range(-4, 5):
            gy = sim_cy + 80 + i * 15
            alpha = max(10, 40 - abs(i) * 6)
            color = (0, 80, 40, alpha)
            pygame.draw.line(self.screen, color,
                             (sim_cx - 175, gy), (sim_cx + 175, gy), 1)
        for i in range(-5, 6):
            gx = sim_cx + i * 35
            alpha = max(10, 30 - abs(i) * 4)
            color = (0, 60, 30, alpha)
            pygame.draw.line(self.screen, color,
                             (gx, sim_cy + 80), (gx, sim_cy - 160), 1)

        # Yer referans cizgisi (parlak)
        pygame.draw.line(self.screen, (0, 150, 60),
                         (sim_cx - 175, sim_cy + 80), (sim_cx + 175, sim_cy + 80), 2)

        # Ucagi ciz
        self.aircraft_sim.draw(self.screen, sim_cx, sim_cy + 10, scale=180)

        # Açı bilgileri
        roll_deg = math.degrees(self.aircraft_sim.roll)
        pitch_deg = math.degrees(self.aircraft_sim.pitch)
        yaw_deg = math.degrees(self.aircraft_sim.yaw)

        # Açı paneli
        self.hud.draw_panel(sim_cx - 180, sim_cy + 175, 360, 28, None)
        angle_text = self.hud.font_tiny.render(
            f"Roll: {roll_deg:+.0f}°   Pitch: {pitch_deg:+.0f}°   Yaw: {yaw_deg:+.0f}°",
            True, ACCENT_CYAN
        )
        self.screen.blit(angle_text, (sim_cx - 95, sim_cy + 180))

        # Pusula heading strip
        self.hud.draw_compass_strip(sim_cx - 180, sim_cy + 207, 360, 35, yaw_deg)

        # VSI (dikey hiz gostergesi) - sag panel
        self.hud.draw_vsi(720, 430, 30, self.channels['elevator'])

        # === Sol Alt: Kanal Cubuklari ===
        bar_y = 640
        bar_h = 20
        bar_w = 200
        self.hud.draw_channel_bar(20, bar_y, bar_w, bar_h, self.channels['aileron'], "AILERON (CH1)")
        self.hud.draw_channel_bar(20, bar_y + 28, bar_w, bar_h, self.channels['elevator'], "ELEVATOR (CH2)")
        self.hud.draw_channel_bar(20, bar_y + 56, bar_w, bar_h, self.channels['rudder'], "RUDDER (CH3)")

        # Throttle dikey cubuk
        self.hud.draw_throttle_bar(245, bar_y, 32, 80, self.channels['throttle'])

        # === Mini Joystick Gorselleri ===
        joy_cx = 140
        joy_cy = 595
        joy_r = 22
        self.hud.draw_mini_joystick(joy_cx - 35, joy_cy, joy_r,
                                     self.channels['aileron'],
                                     self.channels['elevator'], "SOL")
        self.hud.draw_mini_joystick(joy_cx + 35, joy_cy, joy_r,
                                     self.channels['rudder'],
                                     self.channels['throttle'], "SAG")

        # === Sag Panel: Telemetri ===
        # Pil
        self.hud.draw_battery_gauge(780, 80, 220, 90,
                                     self.telemetry.battery_v,
                                     self.telemetry.battery_percent,
                                     self.telemetry.battery_critical)

        # Sinyal
        self.hud.draw_signal_gauge(780, 180, 220, 75,
                                    self.telemetry.rssi,
                                    self.telemetry.connected)

        # Ucus suresi
        self.hud.draw_flight_timer(790, 275, time.time() - self.flight_start)

        # Baglanti durumu
        self.hud.draw_connection_status(790, 330, self.serial_comm)

        # === Steam Deck Buton Takimi ===
        self.hud.draw_steam_deck_buttons(900, 540, self.button_states)

        # === Baslik ===
        title = self.hud.font_large.render("RC UCAK YER ISTASYONU", True, ACCENT_CYAN)
        title_x = WIDTH // 2 - title.get_width() // 2
        self.screen.blit(title, (title_x, 10))

        # Baslik alti glow separator
        sep_x = title_x
        sep_w = title.get_width()
        self.hud.draw_glow_line(sep_x, 52, sep_x + sep_w, 52, ACCENT_CYAN, 1)

        # === Baglanti Durumu ===
        if self.telemetry.is_fresh and self.telemetry.connected:
            conn_label = "UCAK: BAGLI"
            conn_color = ACCENT_GREEN
        elif self.telemetry.connected:
            conn_label = "UCAK: BEKLENIYOR"
            conn_color = ACCENT_ORANGE
        else:
            conn_label = "UCAK: BAGLI DEGIL"
            conn_color = ACCENT_RED

        conn_surf = self.hud.font_medium.render(conn_label, True, conn_color)
        self.screen.blit(conn_surf, (WIDTH // 2 - conn_surf.get_width() // 2, 58))

        # === Failsafe Uyarisi ===
        self.hud.draw_failsafe_warning(WIDTH // 2, 400, self.telemetry.failsafe)

        # === Alt Bilgi Bar ===
        bar_h = 36
        bar_surf = pygame.Surface((WIDTH, bar_h), pygame.SRCALPHA)
        bar_surf.fill((8, 10, 20, 200))
        self.screen.blit(bar_surf, (0, HEIGHT - bar_h))

        pygame.draw.line(self.screen, PANEL_BORDER, (0, HEIGHT - bar_h), (WIDTH, HEIGHT - bar_h), 1)

        help_texts = [
            "Start: Cikis | A: Baglan | B: Kes | X: Yenile | Y: Log",
            f"Joystick: {'BAGLI' if self.joystick else 'YOK'} | "
            f"Arduino: {'BAGLI' if self.serial_comm.connected else 'YOK'}"
        ]
        for i, text in enumerate(help_texts):
            help_surf = self.hud.font_tiny.render(text, True, TEXT_DIM)
            self.screen.blit(help_surf, (10, HEIGHT - bar_h + 4 + i * 15))

        # === Sag alt: TX/RX sayacları ===
        stats = self.hud.font_tiny.render(
            f"TX: {self.serial_comm.tx_count} | RX: {self.serial_comm.rx_count}",
            True, TEXT_DIM
        )
        self.screen.blit(stats, (WIDTH - 150, HEIGHT - 18))

        pygame.display.flip()

    def run(self):
        """Ana dongu"""
        # Otomatik baglan
        if self.auto_connect:
            if self.serial_comm.connect():
                print(f"Arduino baglandi: {self.serial_comm.port}")
            else:
                print("Arduino bulunamadi - 'C' tusu ile tekrar deneyin")

        print("\n=== RC Ucak Yer Istasyonu ===")
        print("ESC: Cikis | C: Baglan | D: Kes | L: Log Baslat/Durdur")

        while self.running:
            self.handle_events()
            self.read_joystick()
            self.send_control()
            self.serial_comm.read_telemetry(self.telemetry)

            if self.flight_log:
                self.flight_log.log(self.channels, self.telemetry)

            self.draw()
            self.clock.tick(FPS)

        # Temizlik
        if self.flight_log:
            self.flight_log.close()
        self.serial_comm.disconnect()
        pygame.quit()


if __name__ == "__main__":
    app = GroundStation()
    app.run()
