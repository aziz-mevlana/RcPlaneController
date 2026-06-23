#!/usr/bin/env python3
"""
RC Plane Controller
GuiController Hatasi Düzeltilmis Eksiksiz Son Sürüm

Sol Stick: Gaz (Dikey) / Rudder (Yatay)
Sag Stick: Elevator (Dikey) / Aileron (Yatay)
"""

import sys, os, time, struct, glob, select as sel
import tty, termios
import serial

BAUD = 115200
DEADZONE = 0.08
FPS = 30
WIDTH, HEIGHT = 800, 500
SEND_PERIOD = 0.035 

# ═══════════════════════════════════════════════════════════════
# LinuxJoy — evdev Sürücüsü
# ═══════════════════════════════════════════════════════════════

try:
    import evdev
    from evdev import ecodes
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

class LinuxJoy:
    def __init__(self):
        if not HAS_EVDEV:
            raise RuntimeError("evdev paketi yuklu degil. pip install evdev")

        self._dev = None
        self._name = ""
        self.raw_axes = {}       
        self._buttons = {}    

        self._find_device()
        self._drain_init()
        print(f"[JOY] {self._name}")

    def _find_device(self):
        candidates = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                if ecodes.EV_ABS in caps:
                    candidates.append((dev, dev.name, path))
                else:
                    dev.close()
            except Exception:
                continue

        if not candidates:
            raise RuntimeError("Hic ABS cihaz bulunamadi")

        priority_keywords = ("microsoft", "x-box", "xbox", "360")
        for dev, name, path in candidates:
            if any(kw in name.lower() for kw in priority_keywords):
                self._dev = dev
                self._name = name
                try: self._dev.grab() 
                except Exception: pass
                return

        keywords = ("gamepad", "joystick", "steam deck", "controller", "deck")
        for dev, name, path in candidates:
            if any(kw in name.lower() for kw in keywords):
                self._dev = dev
                self._name = name
                try: self._dev.grab()
                except Exception: pass
                return

        dev, name, path = candidates[0]
        self._dev = dev
        self._name = name
        try: self._dev.grab()
        except Exception: pass

    def _drain_init(self):
        for _ in range(20):
            r, _, _ = sel.select([self._dev.fd], [], [], 0.05)
            if not r:
                break
            for ev in self._dev.read():
                if ev.type == ecodes.EV_ABS:
                    absinfo = self._dev.absinfo(ev.code)
                    lo, hi, val = absinfo.min, absinfo.max, ev.value
                    rng = hi - lo
                    if rng > 1:
                        self.raw_axes[ev.code] = -1.0 + 2.0 * (val - lo) / rng

    def poll(self):
        total = 0
        r, _, _ = sel.select([self._dev.fd], [], [], 0)
        while r:
            try:
                for ev in self._dev.read():
                    total += 1
                    if ev.type == ecodes.EV_ABS:
                        absinfo = self._dev.absinfo(ev.code)
                        lo, hi, val = absinfo.min, absinfo.max, ev.value
                        rng = hi - lo
                        if rng > 1:
                            norm = -1.0 + 2.0 * (val - lo) / rng
                            self.raw_axes[ev.code] = max(-1.0, min(1.0, norm))
                    elif ev.type == ecodes.EV_KEY:
                        if ev.code == ecodes.BTN_START: self._buttons[9] = (ev.value != 0)
                        elif ev.code == ecodes.BTN_TL: self._buttons[4] = (ev.value != 0)
            except Exception:
                break
            r, _, _ = sel.select([self._dev.fd], [], [], 0)
        return total

    def get_raw_axis(self, code):
        return self.raw_axes.get(code, 0.0)

    def get_button(self, n):
        return self._buttons.get(n, False)

    def get_name(self):
        return self._name

    def close(self):
        try:
            self._dev.ungrab()
            self._dev.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# BaseController — Sinyal Yonetimi
# ═══════════════════════════════════════════════════════════════

class _BaseCtrl:
    def __init__(self, port):
        self.ser = serial.Serial(port, BAUD, timeout=0)
        time.sleep(1.5)
        self.throttle = 1000
        self.aileron = 1500
        self.elevator = 1500
        self.rudder = 1500
        self.aux = 1500
        self.running = True
        self.last_send = 0
        self.joy = None
        self.joy_connected = False
        self._prev_stab_btn = False

    def _init_joystick(self):
        print("[JOY] LinuxJoy taniyor...")
        try:
            self.joy = LinuxJoy()
            self.joy_connected = True
            print(f"[JOY] baglandi: {self.joy.get_name()}")
        except Exception as e:
            print(f"[JOY] Joystick bulunamadi: {e}")

    def send_state(self):
        data = b'\xaa' + struct.pack("<HHHHH",
            self.throttle,  
            self.aileron,   
            self.rudder,    
            self.elevator,  
            self.aux        
        )
        self.ser.write(data)
        self.ser.flush()

    def _deadzone(self, val):
        return val if (val is not None and abs(val) > DEADZONE) else 0.0

    def _poll_joy_axes(self):
        self.joy.poll()

        if self.joy.get_button(4): 
            self.throttle = 1000
        if self.joy.get_button(9): 
            self.running = False

        btn_stab = self.joy.get_button(0)
        if btn_stab and not self._prev_stab_btn:
            self.aux = 2000 if self.aux < 1500 else 1000
            print(f"[STAB] {'AKTIF' if self.aux > 1500 else 'PASIF'}")
        self._prev_stab_btn = btn_stab

        # Sol Stick dikey eksen = GAZ
        raw_left_stick_y = self.joy.get_raw_axis(ecodes.ABS_Y)
        if raw_left_stick_y >= -DEADZONE:
            self.throttle = 1000
        else:
            pct = (abs(raw_left_stick_y) - DEADZONE) / (1.0 - DEADZONE)
            self.throttle = max(1000, min(2000, int(1000 + (pct * 1000))))

        # Sol Stick yatay eksen = RUDDER
        lx_val = self._deadzone(self.joy.get_raw_axis(ecodes.ABS_X))
        self.rudder = max(1000, min(2000, int(1500 + lx_val * 500)))

        # Sağ Stick yatay eksen = AILERON
        rx_val = self._deadzone(self.joy.get_raw_axis(ecodes.ABS_RX))
        self.aileron = max(1000, min(2000, int(1500 - rx_val * 500)))

        # Sağ Stick dikey eksen = ELEVATOR
        ry_val = self._deadzone(self.joy.get_raw_axis(ecodes.ABS_RY))
        self.elevator = max(1000, min(2000, int(1500 - ry_val * 500)))

    def close(self):
        self.throttle = 1000
        if hasattr(self, 'ser') and self.ser and self.ser.is_open:
            try:
                self.send_state()
                self.ser.close()
                print("[SERIAL] Port guvenle kapatildi.")
            except Exception: pass
        if self.joy:
            self.joy.close()


# ═══════════════════════════════════════════════════════════════
# TtyController & GuiController
# ═══════════════════════════════════════════════════════════════

class TtyController(_BaseCtrl):
    def __init__(self, port):
        super().__init__(port)
        self._init_joystick()

    def _print_status(self):
        sys.stdout.write("\033[2K\r")
        self._print_bar("T", self.throttle)
        self._print_bar("A", self.aileron)
        self._print_bar("E", self.elevator)
        self._print_bar("D", self.rudder)
        sys.stdout.write(f"| STAB={'AKTIF' if self.aux > 1500 else 'PASIF'}| FREKANS={SEND_PERIOD}s")
        sys.stdout.write("\n")
        sys.stdout.flush()

    def run(self):
        print("\n=== RC Plane Controller (TTY Sürüm) ===")
        last_print = 0
        while self.running:
            if self.joy_connected:
                self._poll_joy_axes()
            now = time.monotonic()
            if now - self.last_send >= SEND_PERIOD:
                self.send_state()
                self.last_send = now
            if now - last_print > 0.15:
                self._print_status()
                last_print = now
            time.sleep(0.01)
        self.close()


def _make_gui_controller():
    import pygame
    BG, PANEL, BORDER, TXT_COL, ACCENT, AMBER, GREEN, RED = (20, 20, 26), (30, 30, 42), (55, 55, 75), (210, 210, 225), (0, 210, 180), (255, 190, 60), (75, 210, 110), (240, 75, 75)

    class GuiController(_BaseCtrl):
        def __init__(self, port):
            super().__init__(port)
            pygame.init()
            self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
            pygame.display.set_caption("RC Plane Dashboard")
            self.clock = pygame.time.Clock()
            self.font_sm = pygame.font.Font(None, 18)
            self.font = pygame.font.Font(None, 22)
            self.font_big = pygame.font.Font(None, 28)
            self._init_joystick()

        def draw(self):
            self.screen.fill(BG)
            
            pygame.draw.rect(self.screen, PANEL, (0, 0, WIDTH, 40))
            self.screen.blit(self.font_big.render("RC TELEMETRY CONTROL - READY", True, ACCENT), (16, 8))
            
            st = self.joy.get_name()[:32] if self.joy_connected else "KUMANDA BAGLANTISI YOK!"
            s = self.font_sm.render(st, True, GREEN if self.joy_connected else RED)
            self.screen.blit(s, (WIDTH - s.get_width() - 16, 13))

            js_rud = self.joy.get_raw_axis(ecodes.ABS_X)
            js_gaz = self.joy.get_raw_axis(ecodes.ABS_Y)
            js_ail = self.joy.get_raw_axis(ecodes.ABS_RX)
            js_elv = self.joy.get_raw_axis(ecodes.ABS_RY)

            self._draw_stick(195, 190, js_rud, js_gaz, "RUDDER (SOL/SAG)", "GAZ (YUKARI)")
            self._draw_stick(605, 190, js_ail, js_elv, "AILERON (SOL/SAG)", "ELEVATOR (YUKARI/ASAGI)")

            # Optimize Gaz Barı
            bx, by, bw, bh = 150, 350, 500, 14
            pygame.draw.rect(self.screen, PANEL, (bx-2, by-2, bw+4, bh+4), border_radius=4)
            pygame.draw.rect(self.screen, (12, 12, 18), (bx, by, bw, bh), border_radius=3)
            pct = (self.throttle - 1000) / 1000.0
            if pct > 0:
                pygame.draw.rect(self.screen, AMBER, (bx, by, int(pct * bw), bh), border_radius=3)
                
            self.screen.blit(self.font.render("ANLIK GAZ:", True, TXT_COL), (bx - 105, by - 2))
            self.screen.blit(self.font.render(f"{self.throttle}", True, AMBER), (bx + bw + 14, by - 2))

            # Alt Simetrik Kanal Göstergeleri
            cy = 410
            channels = [
                ("THROTTLE", self.throttle, AMBER), ("AILERON", self.aileron, ACCENT),
                ("ELEVATOR", self.elevator, ACCENT), ("RUDDER", self.rudder, ACCENT),
            ]
            cx = 35
            for label, val, color in channels:
                txt = self.font.render(f"{label}: {val:4d}", True, color)
                self.screen.blit(txt, (cx, cy))
                
                pygame.draw.rect(self.screen, PANEL, (cx, cy + 22, 150, 8), border_radius=2)
                mp = (val - 1000) / 1000.0
                mw = int(mp * 150)
                if mw > 0:
                    pygame.draw.rect(self.screen, color, (cx, cy + 22, mw, 8), border_radius=2)
                cx += 190

            stab_label = f"STABILIZASYON: {'AKTIF' if self.aux > 1500 else 'PASIF'} (A tusu)"
            stab_color = GREEN if self.aux > 1500 else (150, 150, 170)
            self.screen.blit(self.font.render(stab_label, True, stab_color), (35, 448))

            hints = "A=Stabilizasyon  |  Sol Analog: Gaz / Istikamet  |  Sag Analog: Kanatcik / Yukselis"
            self.screen.blit(self.font_sm.render(hints, True, (120, 120, 140)), (40, 470))

            pygame.display.flip()

        def _draw_stick(self, cx, cy, ax, ay, lx, ly):
            r = 85
            pygame.draw.circle(self.screen, PANEL, (cx, cy), r + 4, 2)
            pygame.draw.circle(self.screen, (15, 15, 22), (cx, cy), r)
            pygame.draw.line(self.screen, (45, 45, 60), (cx - r, cy), (cx + r, cy), 1)
            pygame.draw.line(self.screen, (45, 45, 60), (cx, cy - r), (cx, cy + r), 1)
            
            dx, dy = cx + int(ax * r), cy + int(ay * r)
            pygame.draw.circle(self.screen, ACCENT, (dx, dy), 6)
            
            if lx: 
                lbl1 = self.font_sm.render(lx, True, ACCENT)
                self.screen.blit(lbl1, (cx - lbl1.get_width()//2, cy + r + 8))
            if ly: 
                lbl2 = self.font_sm.render(ly, True, (150, 150, 170))
                self.screen.blit(lbl2, (cx - r - lbl2.get_width() - 8, cy - 6))

        def run(self):
            while self.running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT: self.running = False
                if self.joy_connected: self._poll_joy_axes()
                
                now = pygame.time.get_ticks() / 1000.0
                if now - self.last_send >= SEND_PERIOD:
                    self.send_state()
                    self.last_send = now

                self.draw()
                self.clock.tick(FPS)
            self.close()

    return GuiController


def find_port():
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/cu.usb*")
    return ports[0] if ports else None


if __name__ == "__main__":
    tty_mode = "--tty" in sys.argv
    port = find_port()
    if port is None: sys.exit(1)

    ctrl = None
    if tty_mode:
        ctrl = TtyController(port)
    else:
        try:
            GuiController = _make_gui_controller()
            ctrl = GuiController(port)
        except Exception:
            ctrl = TtyController(port)

    try:
        if ctrl:
            ctrl.run()
    except KeyboardInterrupt:
        pass
    finally:
        if ctrl:
            ctrl.close()
    print("\nCikildi.")