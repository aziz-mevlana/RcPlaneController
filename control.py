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
import select as sel
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
# RawLinuxJoy — /dev/input/js* + evdev fallback
# ═══════════════════════════════════════════════════════════════

class RawLinuxJoy:
    """
    Linux joystick: once /dev/input/js* dene, yoksa /dev/input/event*.
    Steam/SDL/pygame/SteamInput fark etmez — kernel seviyesinde calisir.
    """

    def __init__(self):
        self._fd = None
        self._path = ""
        self._axes = {}
        self._buttons = {}
        self._prev_buttons = {}
        self._axes_range = {}   # axis_number -> (min, max)  evdev icin
        self._is_evdev = False
        self._name = ""

        # 1) js0-js4 tara
        for i in range(5):
            path = f"/dev/input/js{i}"
            if self._try_js(path):
                return

        # 2) evdev event* tara (event0-event15)
        for i in range(16):
            path = f"/dev/input/event{i}"
            name = self._read_sysfs_name(i)
            if name and any(kw in name.lower() for kw in
                            ("gamepad", "joystick", "steam deck",
                             "controller", "xbox", "playstation", "dualshock",
                             "dualsense", "8bitdo", "generic")):
                if self._try_evdev(path, name):
                    return

        # 3) evdev tum event* dene (isim filtresiz, ABS_X varsa kullan)
        for i in range(16):
            path = f"/dev/input/event{i}"
            if self._try_evdev(path, f"event{i}"):
                return

        raise RuntimeError("Joystick bulunamadi")

    # ── sysfs ──────────────────────────────────────────────

    def _read_sysfs_name(self, idx):
        p = f"/sys/class/input/event{idx}/device/name"
        try:
            with open(p) as f:
                return f.read().strip()
        except Exception:
            return ""

    # ── js deneme ──────────────────────────────────────────

    def _try_js(self, path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except Exception:
            return False

        # block ederek 1 sn icinde event var mi bak
        r, _, _ = sel.select([fd], [], [], 0.8)
        if not r:
            # belki zaten bufferda var
            try:
                chunk = os.read(fd, 128)
                if len(chunk) >= 8:
                    r = [fd]  # varmis
            except BlockingIOError:
                pass

        if not r:
            os.close(fd)
            print(f"  [JS] {path} : event yok (sessiz)")
            return False

        self._fd = fd
        self._path = path
        self._name = f"JS ({path})"
        self._is_evdev = False
        # bufferda ne varsa oku
        self._drain_js()
        nev = len(self._axes) + len(self._buttons)
        print(f"  [JS] {path} : OK (axes={len(self._axes)} btn={len(self._buttons)})")
        return True

    def _drain_js(self):
        while True:
            try:
                data = os.read(self._fd, 8)
                if len(data) < 8:
                    break
                _, value, etype, number = struct.unpack('<IhBB', data)
                if etype & 0x02:
                    self._axes[number] = max(-1.0, min(1.0, value / 32767.0))
                elif etype & 0x01:
                    self._buttons[number] = value != 0
            except BlockingIOError:
                break

    # ── evdev deneme ───────────────────────────────────────

    def _try_evdev(self, path, name):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except Exception:
            return False

        # read initial events (calibration)
        has_abs = False
        deadline = time.time() + 0.5
        while time.time() < deadline:
            try:
                data = os.read(fd, 24)
                if len(data) < 24:
                    break
                etype, code, value = self._parse_evdev(data)
                if etype == 0x03:  # EV_ABS
                    has_abs = True
                    # auto-range: track min/max
                    cur = self._axes_range.get(code, [value, value])
                    self._axes_range[code] = [min(cur[0], value), max(cur[1], value)]
            except BlockingIOError:
                time.sleep(0.02)

        if not has_abs:
            os.close(fd)
            print(f"  [EV] {name} ({path}) : EV_ABS yok")
            return False

        # re-open (reset pos)
        os.close(fd)
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self._fd = fd
        self._path = path
        self._name = f"EV ({name})"
        self._is_evdev = True
        self._drain_evdev()
        print(f"  [EV] {name} ({path}) : OK (axes={len(self._axes_range)})")
        return True

    def _drain_evdev(self):
        while True:
            try:
                data = os.read(self._fd, 24)
                if len(data) < 24:
                    break
                self._apply_evdev(data)
            except BlockingIOError:
                break

    def _parse_evdev(self, data):
        # struct input_event (64-bit):
        #   tv_sec (int64), tv_usec (int64), type (uint16), code (uint16), value (int32)
        # = 8 + 8 + 2 + 2 + 4 = 24 bytes
        sec  = struct.unpack_from('<q', data, 0)[0]
        usec = struct.unpack_from('<q', data, 8)[0]
        etype = struct.unpack_from('<H', data, 16)[0]
        code  = struct.unpack_from('<H', data, 18)[0]
        value = struct.unpack_from('<i', data, 20)[0]
        return etype, code, value

    def _apply_evdev(self, data):
        etype, code, value = self._parse_evdev(data)
        if etype == 0x03:  # EV_ABS
            # expand range
            cur = self._axes_range.get(code, [value, value])
            self._axes_range[code] = [min(cur[0], value), max(cur[1], value)]
            # normalize
            lo, hi = self._axes_range[code]
            rng = hi - lo
            if rng > 0:
                norm = -1.0 + 2.0 * (value - lo) / rng
            else:
                norm = 0.0
            self._axes[code] = max(-1.0, min(1.0, norm))
        elif etype == 0x01:  # EV_KEY
            self._buttons[code] = value != 0

    # ── poll (her frame cagrilir) ──────────────────────────

    def poll(self):
        new_presses = []
        if self._is_evdev:
            self._poll_evdev(new_presses)
        else:
            self._poll_js(new_presses)
        return new_presses

    def _poll_js(self, new_presses):
        while True:
            try:
                data = os.read(self._fd, 8)
                if len(data) < 8:
                    break
                _, value, etype, number = struct.unpack('<IhBB', data)
                if etype & 0x02:
                    self._axes[number] = max(-1.0, min(1.0, value / 32767.0))
                elif etype & 0x01:
                    pressed = value != 0
                    if pressed and not self._prev_buttons.get(number, False):
                        new_presses.append(number)
                    self._prev_buttons[number] = pressed
                    self._buttons[number] = pressed
            except BlockingIOError:
                break

    def _poll_evdev(self, new_presses):
        while True:
            try:
                data = os.read(self._fd, 24)
                if len(data) < 24:
                    break
                etype, code, value = self._parse_evdev(data)
                if etype == 0x03:
                    lo, hi = self._axes_range.get(code, [value, value])
                    lo, hi = min(lo, value), max(hi, value)
                    self._axes_range[code] = [lo, hi]
                    rng = hi - lo
                    norm = -1.0 + 2.0 * (value - lo) / rng if rng > 0 else 0.0
                    self._axes[code] = max(-1.0, min(1.0, norm))
                elif etype == 0x01:
                    pressed = value != 0
                    if pressed and not self._prev_buttons.get(code, False):
                        new_presses.append(code)
                    self._prev_buttons[code] = pressed
                    self._buttons[code] = pressed
            except BlockingIOError:
                break

    # ── pygame uyumlu arayuz ───────────────────────────────

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
        pass

    def close(self):
        try:
            os.close(self._fd)
        except Exception:
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
        # axis mapping (evdev ve js farkli)
        self.ax_aileron  = 0
        self.ax_elevator = 1
        self.ax_rudder   = 2
        self.ax_l2       = 4
        self.ax_r2       = 5
        self._init_joystick()

        self.last_hat_time = 0
        self.last_trigger_time = 0

        self._debug_start = pygame.time.get_ticks()
        self._debug_seen = set()

        self.send_state()

    # ─── joystick init ─────────────────────────────────────

    def _init_joystick(self):
        # 1) RawLinuxJoy (js + evdev) — Steam/SDL'den bagimsiz
        print("[JOY] RawLinuxJoy taniyor...")
        try:
            self.joy = RawLinuxJoy()
            self.joy_connected = True
            self.joy_name = self.joy.get_name()
            self.use_raw_joy = True
            if self.joy._is_evdev:
                # evdev axis numaralari: ABS_X=0 ABS_Y=1 ABS_Z=2 ABS_RX=3 ABS_RZ=5
                self.ax_aileron  = 0
                self.ax_elevator = 1
                self.ax_rudder   = 3
                self.ax_l2       = 2
                self.ax_r2       = 5
            else:
                # js axis numaralari
                self.ax_aileron  = 0
                self.ax_elevator = 1
                self.ax_rudder   = 2
                self.ax_l2       = 4
                self.ax_r2       = 5
            print(f"[JOY] baglandi: {self.joy_name}")
            print(f"[JOY] mapping: ail={self.ax_aileron} elev={self.ax_elevator} "
                  f"rudd={self.ax_rudder} L2={self.ax_l2} R2={self.ax_r2}")
            print("[DBG] Ilk 5 sn axis/button numaralarini konsola yaziyor...")
            return
        except RuntimeError as e:
            print(f"[JOY] RawLinuxJoy basarisiz: {e}")

        # 2) pygame fallback
        print("[JOY] pygame deneniyor...")
        try:
            pygame.joystick.init()
            count = pygame.joystick.get_count()
            if count > 0:
                self.joy = pygame.joystick.Joystick(0)
                self.joy.init()
                self.joy_connected = True
                self.joy_name = self.joy.get_name()
                self.use_raw_joy = False
                print(f"[JOY] baglandi (pygame): {self.joy_name}")
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
        ax = self._deadzone(self.joy.get_axis(self.ax_aileron))
        self._debug("axis", self.ax_aileron, ax)
        if ax is not None:
            v = max(1000, min(2000, int(1500 + ax * 500)))
            if v != self.aileron:
                self.aileron = v; self.changed = True
        elif self.aileron != 1500:
            self.aileron = 1500; self.changed = True

        # --- Left Stick Y -> Elevator ---
        ay = self._deadzone(self.joy.get_axis(self.ax_elevator))
        self._debug("axis", self.ax_elevator, ay)
        if ay is not None:
            v = max(1000, min(2000, int(1500 + ay * 500)))
            if v != self.elevator:
                self.elevator = v; self.changed = True
        elif self.elevator != 1500:
            self.elevator = 1500; self.changed = True

        # --- Right Stick X -> Rudder ---
        rx = self._deadzone(self.joy.get_axis(self.ax_rudder))
        self._debug("axis", self.ax_rudder, rx)
        if rx is not None:
            v = max(1000, min(2000, int(1500 + rx * 500)))
            if v != self.rudder:
                self.rudder = v; self.changed = True
        elif self.rudder != 1500:
            self.rudder = 1500; self.changed = True

        # --- L2/R2 -> Throttle (incremental, her 100ms) ---
        if now - self.last_trigger_time >= 100:
            l2 = self.joy.get_axis(self.ax_l2)
            self._debug("axis", self.ax_l2, l2)
            if l2 > 0.1:
                self.throttle = min(2000, self.throttle + int(l2 * STEP))
                self.changed = True
            r2 = self.joy.get_axis(self.ax_r2)
            self._debug("axis", self.ax_r2, r2)
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
        if pygame.time.get_ticks() - self._debug_start > 5000:
            return
        key = (kind, num)
        if key in self._debug_seen:
            return
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

        # stick okuma (cizim icin)
        jax0 = self.joy.get_axis(self.ax_aileron) if self.joy_connected else 0.0
        jax1 = self.joy.get_axis(self.ax_elevator) if self.joy_connected else 0.0
        jax_r = self.joy.get_axis(self.ax_rudder) if self.joy_connected else 0.0
        jax4 = self.joy.get_axis(self.ax_l2) if self.joy_connected else 0.0
        jax5 = self.joy.get_axis(self.ax_r2) if self.joy_connected else 0.0

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

        pygame.draw.circle(self.screen, PANEL, (cx, cy), r + 7)
        pygame.draw.circle(self.screen, (18, 18, 28), (cx, cy), r)
        pygame.draw.circle(self.screen, BORDER, (cx, cy), r, 2)
        pygame.draw.line(self.screen, BORDER, (cx - r, cy), (cx + r, cy), 1)
        pygame.draw.line(self.screen, BORDER, (cx, cy - r), (cx, cy + r), 1)
        pygame.draw.circle(self.screen, (50, 50, 65), (cx, cy), int(dr), 1)

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

        if lx:
            lb = self.font_sm.render(lx, True, ACCENT)
            self.screen.blit(lb, (cx - lb.get_width()//2, cy + r + 12))
        if ly:
            lb = self.font_sm.render(ly, True, ACCENT)
            self.screen.blit(lb, (cx - r - lb.get_width() - 6, cy - lb.get_height()//2))

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
