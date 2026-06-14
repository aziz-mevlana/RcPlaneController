#!/usr/bin/env python3
"""
RC Plane Controller - Pygame Gorsel Arayuz
Klavye + Joystick (Steam Deck) kontrolu

Calistirma:
  python3 control.py
  python3 control.py /dev/cu.usbmodemXXXX
"""

import sys
import os
import time
import struct
import glob
import serial
import pygame

BAUD = 115200
STEP = 50
DEADZONE = 0.08
FPS = 30
WIDTH, HEIGHT = 800, 500

BG      = (22, 22, 32)
PANEL   = (38, 38, 52)
BORDER  = (70, 70, 90)
TEXT    = (200, 200, 215)
ACCENT  = (0, 210, 180)
WARN    = (255, 120, 70)
GREEN   = (80, 220, 80)
AMBER   = (255, 200, 50)
RED     = (240, 70, 60)
DIM     = (90, 90, 110)


# ═══════════════════════════════════════════════════════════════
# Raw Linux Joystick — /dev/input/js0 dogrudan okuma
# Steam / SDL / pygame'den bagimsiz, her zaman calisir
# ═══════════════════════════════════════════════════════════════

class RawJoystick:
    """Linux /dev/input/js0 ham okuyucu. pygame Joystick arayuzu taklit eder."""

    JS_EVENT_BUTTON = 0x01
    JS_EVENT_AXIS   = 0x02

    def __init__(self, path="/dev/input/js0"):
        self._path = path
        self._fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self._axes = {}
        self._buttons = {}
        self._prev_buttons = {}
        self._name = f"RawJoy ({path})"

    def poll(self):
        """Pending tum eventleri oku. Yeni basilan button'lari doner."""
        new_presses = []
        while True:
            try:
                data = os.read(self._fd, 8)
                if len(data) < 8:
                    break
                _time, value, etype, number = struct.unpack('<IhBB', data)

                if etype & self.JS_EVENT_AXIS:
                    norm = max(-1.0, min(1.0, value / 32767.0))
                    self._axes[number] = norm

                elif etype & self.JS_EVENT_BUTTON:
                    pressed = value != 0
                    if pressed and not self._prev_buttons.get(number, False):
                        new_presses.append(number)
                    self._prev_buttons[number] = pressed
                    self._buttons[number] = pressed

            except BlockingIOError:
                break
        return new_presses

    def get_axis(self, n):
        return self._axes.get(n, 0.0)

    def get_button(self, n):
        return self._buttons.get(n, False)

    def get_hat(self, n):
        base = 6 + n * 2
        return (int(self.get_axis(base)), int(self.get_axis(base + 1)))

    def get_name(self):
        return self._name

    def quit(self):
        pass  # uyumluluk

    def close(self):
        try:
            os.close(self._fd)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════

class RcController:
    def __init__(self, port):
        self.ser = serial.Serial(port, BAUD, timeout=0)
        time.sleep(1.5)

        self.throttle = 1000
        self.aileron = 1500
        self.elevator = 1500
        self.rudder = 1500
        self.aux = 1500
        self.running = True
        self.changed = False
        self.last_send = 0

        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("RC Plane Controller")
        self.clock = pygame.time.Clock()
        self.font_sm  = pygame.font.Font(None, 17)
        self.font     = pygame.font.Font(None, 22)
        self.font_md  = pygame.font.Font(None, 26)
        self.font_big = pygame.font.Font(None, 32)

        self.joy_connected = False
        self.joy_name = ""
        self.joy = None
        self.use_raw_joy = False
        self.rudder_axis = 2    # Steam Deck: sag stick X
        self._init_joystick()

        self.last_hat_time = 0
        self.last_trigger_time = 0

        self._debug_start = pygame.time.get_ticks()
        self._debug_seen = set()

        self.send_state()

    # ─── joystick init ─────────────────────────────────────

    def _init_joystick(self):
        # 1) Linux: /dev/input/js0 direkt okuma (Steam/SDL'den bagimsiz)
        if os.path.exists("/dev/input/js0"):
            try:
                self.joy = RawJoystick("/dev/input/js0")
                self.joy_connected = True
                self.joy_name = self.joy.get_name()
                self.use_raw_joy = True
                print(f"[JOY] raw: {self.joy_name}")
                print("[DBG] Ilk 5 sn axis/button numaralarini konsola yaziyor...")
                return
            except PermissionError:
                print("[JOY] /dev/input/js0 izin hatasi!")
                print("[JOY] sudo usermod -a -G input $USER && reboot")

        # 2) pygame fallback (diger isletim sistemleri / normal gamepad)
        try:
            pygame.joystick.init()
            count = pygame.joystick.get_count()
            if count > 0:
                self.joy = pygame.joystick.Joystick(0)
                self.joy.init()
                self.joy_connected = True
                self.joy_name = self.joy.get_name()
                self.use_raw_joy = False
                print(f"[JOY] pygame: {self.joy_name}")
                return
        except Exception as e:
            print(f"[JOY] pygame hata: {e}")

        print("[JOY] Joystick bulunamadi - klavye modu")

    # ─── serial ────────────────────────────────────────────

    def send_state(self):
        data = b'\xaa' + struct.pack("<HHHHH",
            self.throttle, self.aileron, self.elevator,
            self.rudder, self.aux
        )
        self.ser.write(data)
        self.ser.flush()

    # ─── events ────────────────────────────────────────────

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._keydown(event.key)
            elif event.type == pygame.JOYBUTTONDOWN and not self.use_raw_joy:
                self._joybutton(event.button)

    def _keydown(self, key):
        c = False
        if key in (pygame.K_q, pygame.K_ESCAPE):
            self.running = False
        elif key == pygame.K_w:
            self.throttle = min(2000, self.throttle + STEP); c = True
        elif key == pygame.K_s:
            self.throttle = max(1000, self.throttle - STEP); c = True
        elif key == pygame.K_SPACE:
            self.throttle = 1000; c = True
        elif key == pygame.K_a:
            self.rudder = max(1000, self.rudder - STEP); c = True
        elif key == pygame.K_d:
            self.rudder = min(2000, self.rudder + STEP); c = True
        elif key == pygame.K_UP:
            self.elevator = min(2000, self.elevator + STEP); c = True
        elif key == pygame.K_DOWN:
            self.elevator = max(1000, self.elevator - STEP); c = True
        elif key == pygame.K_LEFT:
            self.aileron = max(1000, self.aileron - STEP); c = True
        elif key == pygame.K_RIGHT:
            self.aileron = min(2000, self.aileron + STEP); c = True
        if c:
            self.changed = True

    def _joybutton(self, button):
        if button == 4:
            self.throttle = 1000
            self.changed = True
        elif button == 9:
            self.running = False

    # ─── joystick poll ─────────────────────────────────────

    def poll_joystick(self):
        if not self.joy_connected:
            return

        now = pygame.time.get_ticks()

        # raw mod: once tum eventleri oku
        if self.use_raw_joy:
            for btn in self.joy.poll():
                self._debug("button", btn, 1.0)
                self._joybutton(btn)

        # --- Left Stick X -> Aileron ---
        ax = self._deadzone(self.joy.get_axis(0))
        self._debug("axis", 0, ax)
        if ax is not None:
            v = max(1000, min(2000, int(1500 + ax * 500)))
            if v != self.aileron:
                self.aileron = v; self.changed = True
        elif self.aileron != 1500:
            self.aileron = 1500; self.changed = True

        # --- Left Stick Y -> Elevator ---
        ay = self._deadzone(self.joy.get_axis(1))
        self._debug("axis", 1, ay)
        if ay is not None:
            v = max(1000, min(2000, int(1500 + ay * 500)))
            if v != self.elevator:
                self.elevator = v; self.changed = True
        elif self.elevator != 1500:
            self.elevator = 1500; self.changed = True

        # --- Right Stick X -> Rudder ---
        rx = self._deadzone(self.joy.get_axis(self.rudder_axis))
        self._debug("axis", self.rudder_axis, rx)
        if rx is not None:
            v = max(1000, min(2000, int(1500 + rx * 500)))
            if v != self.rudder:
                self.rudder = v; self.changed = True
        elif self.rudder != 1500:
            self.rudder = 1500; self.changed = True

        # --- L2/R2 -> Throttle (incremental, her 100ms) ---
        if now - self.last_trigger_time >= 100:
            l2 = self.joy.get_axis(4)
            self._debug("axis", 4, l2)
            if l2 > 0.1:
                self.throttle = min(2000, self.throttle + int(l2 * STEP))
                self.changed = True
            r2 = self.joy.get_axis(5)
            self._debug("axis", 5, r2)
            if r2 > 0.1:
                self.throttle = max(1000, self.throttle - int(r2 * STEP))
                self.changed = True
            self.last_trigger_time = now

        # --- D-Pad -> Aileron / Elevator (her 100ms) ---
        if now - self.last_hat_time >= 100:
            hat = self.joy.get_hat(0)
            self._debug("hat", 0, hat)
            if hat[0] == -1:
                self.aileron = max(1000, self.aileron - STEP); self.changed = True
            elif hat[0] == 1:
                self.aileron = min(2000, self.aileron + STEP); self.changed = True
            if hat[1] == 1:
                self.elevator = min(2000, self.elevator + STEP); self.changed = True
            elif hat[1] == -1:
                self.elevator = max(1000, self.elevator - STEP); self.changed = True
            self.last_hat_time = now

    def _deadzone(self, val):
        return val if (val is not None and abs(val) > DEADZONE) else None

    def _debug(self, kind, num, val):
        """Ilk 5 saniye hangi axis/button/hat hareket ediyor konsola yaz."""
        if pygame.time.get_ticks() - self._debug_start > 5000:
            return
        key = (kind, num)
        if key in self._debug_seen:
            return
        # sadece anlamli hareket varsa yaz
        if kind == "axis":
            if val is None or abs(val) < 0.05:
                return
            print(f"[DBG] axis {num:2d}  = {val:+7.3f}")
        elif kind == "button":
            print(f"[DBG] btn  {num:2d}  pressed")
        elif kind == "hat":
            if val[0] == 0 and val[1] == 0:
                return
            print(f"[DBG] hat  {num}    = {val}")
        self._debug_seen.add(key)

    # ─── draw ────────────────────────────────────────────────

    def draw(self):
        self.screen.fill(BG)

        # header
        pygame.draw.rect(self.screen, PANEL, (0, 0, WIDTH, 46))
        t = self.font_big.render("RC  Plane  Controller", True, ACCENT)
        self.screen.blit(t, (16, 8))

        if self.joy_connected:
            tag = "[RAW]" if self.use_raw_joy else "[PYG]"
            st = f"{tag} {self.joy_name[:28]}"
            sc = GREEN
        else:
            st = "Joystick yok — klavye modu"
            sc = WARN
        s = self.font_sm.render(st, True, sc)
        self.screen.blit(s, (WIDTH - s.get_width() - 14, 14))

        # stick okuma (cizim icin, gonderimden bagimsiz)
        jax0 = self.joy.get_axis(0) if self.joy_connected else 0.0
        jax1 = self.joy.get_axis(1) if self.joy_connected else 0.0
        jax_r = self.joy.get_axis(self.rudder_axis) if self.joy_connected else 0.0
        jax4 = self.joy.get_axis(4) if self.joy_connected else 0.0
        jax5 = self.joy.get_axis(5) if self.joy_connected else 0.0

        # sticks
        self._draw_stick(190, 210, jax0, jax1, "AILERON", "ELEVATOR")
        self._draw_stick(590, 210, jax_r, 0.0, "RUDDER", "")

        # throttle bar
        bx, by, bw, bh = 110, 388, 580, 26
        pygame.draw.rect(self.screen, PANEL, (bx-3, by-3, bw+6, bh+6), border_radius=6)
        pygame.draw.rect(self.screen, (16, 16, 26), (bx, by, bw, bh), border_radius=4)

        pct = (self.throttle - 1000) / 1000.0
        fw = int(pct * bw)
        if fw > 0:
            if self.throttle <= 1500:
                r = int(60 + 195 * (self.throttle-1000)/500)
                g = 230
            else:
                r = 255
                g = int(230 - 160 * (self.throttle-1500)/500)
            pygame.draw.rect(self.screen, (r, g, 55), (bx, by, fw, bh), border_radius=4)

        self.screen.blit(self.font.render("GAZ", True, TEXT), (bx - 42, by + 2))
        self.screen.blit(self.font_md.render(str(self.throttle), True, AMBER), (bx + bw + 12, by + 1))

        # L2 / R2 indicators
        l2c = GREEN if jax4 > 0.1 else DIM
        r2c = RED if jax5 > 0.1 else DIM
        l2t = self.font_sm.render("L2 ▲", True, l2c)
        r2t = self.font_sm.render("R2 ▼", True, r2c)
        self.screen.blit(l2t, (bx + bw//2 - 55, by + 30))
        self.screen.blit(r2t, (bx + bw//2 + 18, by + 30))

        # kanal degerleri + mini bar
        cy = 440
        channels = [
            ("T", self.throttle, AMBER),
            ("A", self.aileron,  ACCENT),
            ("E", self.elevator, ACCENT),
            ("D", self.rudder,   ACCENT),
        ]
        cx = 55
        for label, val, color in channels:
            txt = self.font.render(f"{label}:{val:4d}", True, color)
            self.screen.blit(txt, (cx, cy))
            mp = (val - 1000) / 1000.0
            mw = int(mp * 100)
            pygame.draw.rect(self.screen, (28, 28, 40), (cx + 70, cy + 2, 100, 16), border_radius=2)
            if mw > 0:
                pygame.draw.rect(self.screen, color, (cx + 70, cy + 2, mw, 16), border_radius=2)
            cx += 185

        # klavye yardim
        hy = 475
        hints = [
            ("W/S Gaz", TEXT), ("A/D Rudder", TEXT),
            ("← → Aileron", TEXT), ("↑ ↓ Elev", TEXT),
            ("Space GazKes", TEXT), ("Q/ESC Cikis", TEXT),
        ]
        hx = 28
        for txt, col in hints:
            r = self.font_sm.render(txt, True, col)
            self.screen.blit(r, (hx, hy))
            hx += r.get_width() + 16

        pygame.display.flip()

    def _draw_stick(self, cx, cy, ax, ay, lx, ly):
        r = 90
        dr = r * DEADZONE

        # bg
        pygame.draw.circle(self.screen, PANEL, (cx, cy), r + 7)
        pygame.draw.circle(self.screen, (18, 18, 28), (cx, cy), r)
        pygame.draw.circle(self.screen, BORDER, (cx, cy), r, 2)
        pygame.draw.line(self.screen, BORDER, (cx - r, cy), (cx + r, cy), 1)
        pygame.draw.line(self.screen, BORDER, (cx, cy - r), (cx, cy + r), 1)
        pygame.draw.circle(self.screen, (50, 50, 65), (cx, cy), int(dr), 1)

        # dot
        dx = cx + int(ax * r)
        dy = cy + int(ay * r)
        dist = ((dx - cx)**2 + (dy - cy)**2) ** 0.5
        if dist > r:
            dx = cx + int((dx - cx) * r / dist)
            dy = cy + int((dy - cy) * r / dist)

        if abs(ax) > DEADZONE or abs(ay) > DEADZONE:
            pygame.draw.line(self.screen, (55, 55, 75), (cx, dy), (dx, dy), 1)
            pygame.draw.line(self.screen, (55, 55, 75), (dx, cy), (dx, dy), 1)
        pygame.draw.circle(self.screen, ACCENT, (dx, dy), 7)
        pygame.draw.circle(self.screen, (255, 255, 255), (dx, dy), 3)

        # labels
        if lx:
            lb = self.font_sm.render(lx, True, ACCENT)
            self.screen.blit(lb, (cx - lb.get_width()//2, cy + r + 12))
        if ly:
            lb = self.font_sm.render(ly, True, ACCENT)
            self.screen.blit(lb, (cx - r - lb.get_width() - 6, cy - lb.get_height()//2))

        # axis vals
        vx = self.font_sm.render(f"{ax:+.2f}", True, TEXT)
        self.screen.blit(vx, (cx - vx.get_width()//2, cy + r + 30))
        vy = self.font_sm.render(f"{ay:+.2f}", True, TEXT)
        self.screen.blit(vy, (cx + r + 12, cy + 6))

    # ─── run ─────────────────────────────────────────────────

    def run(self):
        pygame.key.set_repeat(200, 100)

        while self.running:
            self.handle_events()
            if self.joy_connected:
                self.poll_joystick()

            now = pygame.time.get_ticks()
            if self.changed or now - self.last_send > 500:
                self.send_state()
                self.changed = False
                self.last_send = now

            self.draw()
            self.clock.tick(FPS)

        self.close()

    def close(self):
        self.throttle = 1000
        self.send_state()
        self.ser.close()
        if self.joy:
            self.joy.quit()
            if self.use_raw_joy:
                self.joy.close()
        pygame.joystick.quit()
        pygame.quit()


# ─── main ───────────────────────────────────────────────────

def find_port():
    ports = glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.usbmodem*")
    if ports:
        return ports[0]
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if ports:
        return ports[0]
    return None


if __name__ == "__main__":
    port = None
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            port = arg

    if port is None:
        port = find_port()

    if port is None:
        print("Seri port bulunamadi!")
        print("Elle belirt: python3 control.py /dev/cu.usbserial-XXXX")
        sys.exit(1)

    print(f"Port: {port}")
    ctrl = RcController(port)
    try:
        ctrl.run()
    except KeyboardInterrupt:
        ctrl.close()
    print("\nCikildi.")
