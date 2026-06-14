#!/usr/bin/env python3
"""
RC Plane Controller
Klavye + Joystick (Steam Deck) kontrolu

Calistirma:
  python3 control.py                  # GUI modu (pygame penceresi)
  python3 control.py --tty             # Terminal modu (Game Mode)
  python3 control.py /dev/cu.usbmodemXXXX
"""

import sys, os, time, struct, glob, select as sel
import tty, termios
import serial

BAUD = 115200
STEP = 50
DEADZONE = 0.08
FPS = 30
WIDTH, HEIGHT = 800, 500

# ═══════════════════════════════════════════════════════════════
# LinuxJoy — evdev tabanli, guvenilir joystick okuma
# ═══════════════════════════════════════════════════════════════

try:
    import evdev
    from evdev import ecodes
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

class LinuxJoy:
    """
    Linux joystick okuma (evdev paketi ile).
    Steam/SDL/pygame/SteamInput fark etmez.
    """

    # evdev axis kodlarindan JS axis numarasina
    _AX_EV2JS = {
        ecodes.ABS_X: 0,      # Left Stick X
        ecodes.ABS_Y: 1,      # Left Stick Y
        ecodes.ABS_Z: 2,      # L2
        ecodes.ABS_RX: 3,     # Right Stick X
        ecodes.ABS_RY: 4,     # Right Stick Y
        ecodes.ABS_RZ: 5,     # R2
        ecodes.ABS_HAT0X: 6,  # D-Pad X
        ecodes.ABS_HAT0Y: 7,  # D-Pad Y
    } if HAS_EVDEV else {}
    _AX_JS2EV = {v: k for k, v in _AX_EV2JS.items()} if HAS_EVDEV else {}

    # evdev button kodlarindan JS button numarasina
    _BTN_EV2JS = {
        ecodes.BTN_SOUTH:  0,   # A
        ecodes.BTN_EAST:   1,   # B
        ecodes.BTN_NORTH:  2,   # X
        ecodes.BTN_WEST:   3,   # Y
        ecodes.BTN_TL:     4,   # L1
        ecodes.BTN_TR:     5,   # R1
        ecodes.BTN_TL2:    6,   # L2 click
        ecodes.BTN_TR2:    7,   # R2 click
        ecodes.BTN_SELECT: 8,   # View / Select
        ecodes.BTN_START:  9,   # Start
        ecodes.BTN_THUMBL: 10,  # L3
        ecodes.BTN_THUMBR: 11,  # R3
    } if HAS_EVDEV else {}

    def __init__(self):
        if not HAS_EVDEV:
            raise RuntimeError("evdev paketi yuklu degil. pip install evdev")

        self._dev = None
        self._name = ""
        self._axes = {}       # JS axis -> -1..1
        self._buttons = {}    # JS button -> bool
        self._prev_buttons = {}

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
                    print(f"  [EV] {path}: {dev.name}")
                    candidates.append((dev, dev.name, path))
                else:
                    dev.close()
            except Exception:
                continue

        if not candidates:
            raise RuntimeError("Hic ABS cihaz bulunamadi")

        # prefer gamepad/steam deck
        keywords = ("gamepad", "joystick", "steam deck", "controller",
                     "xbox", "playstation", "dualshock", "dualsense", "8bitdo", "deck")
        for dev, name, path in candidates:
            if any(kw in name.lower() for kw in keywords):
                self._dev = dev
                self._name = f"{name}"
                print(f"  [EV] secildi: {name}")
                return

        # fallback: ilk ABS cihazi
        dev, name, path = candidates[0]
        self._dev = dev
        self._name = f"{name}"
        print(f"  [EV] secildi (fallback): {name}")

    def _drain_init(self):
        # baslangic durumunu oku
        for _ in range(20):
            r, _, _ = sel.select([self._dev.fd], [], [], 0.05)
            if not r:
                break
            for ev in self._dev.read():
                if ev.type == ecodes.EV_ABS:
                    self._apply_abs(ev)
                elif ev.type == ecodes.EV_KEY:
                    self._apply_key(ev, False)

    def _apply_abs(self, ev):
        js_axis = self._AX_EV2JS.get(ev.code)
        if js_axis is None:
            return
        try:
            absinfo = self._dev.absinfo(ev.code)
            lo, hi, val = absinfo.min, absinfo.max, ev.value
            rng = hi - lo
            if rng > 1:
                norm = -1.0 + 2.0 * (val - lo) / rng
                self._axes[js_axis] = max(-1.0, min(1.0, norm))
        except Exception:
            self._axes[js_axis] = 0.0

    def _apply_key(self, ev, track_press=True):
        js_btn = self._BTN_EV2JS.get(ev.code)
        if js_btn is None:
            return
        pressed = ev.value != 0
        if track_press and pressed and not self._prev_buttons.get(js_btn):
            # will be collected as new_press
            pass
        self._prev_buttons[js_btn] = pressed
        self._buttons[js_btn] = pressed

    def poll(self):
        """Non-blocking event okuma. Yeni basilan JS button numaralarini doner."""
        new_presses = []
        total = 0
        r, _, _ = sel.select([self._dev.fd], [], [], 0)
        while r:
            try:
                for ev in self._dev.read():
                    total += 1
                    if ev.type == ecodes.EV_ABS:
                        self._apply_abs(ev)
                    elif ev.type == ecodes.EV_KEY:
                        js_btn = self._BTN_EV2JS.get(ev.code)
                        if js_btn is not None:
                            pressed = ev.value != 0
                            if pressed and not self._prev_buttons.get(js_btn):
                                new_presses.append(js_btn)
                            self._prev_buttons[js_btn] = pressed
                            self._buttons[js_btn] = pressed
            except Exception:
                break
            r, _, _ = sel.select([self._dev.fd], [], [], 0)
        return new_presses, total

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
            self._dev.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# TtyController — Terminal modu
# ═══════════════════════════════════════════════════════════════

class _BaseCtrl:
    """Ortak: serial, joystick, kanal mantigi. GUI/TTY bunu miras alir."""
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

        self.joy = None
        self.joy_connected = False
        # axis mapping (LinuxJoy standard)
        self.ax_aileron  = 0   # ABS_X
        self.ax_elevator = 1   # ABS_Y
        self.ax_rudder   = 3   # ABS_RX
        self.ax_l2       = 2   # ABS_Z
        self.ax_r2       = 5   # ABS_RZ
        self.last_hat_time = 0
        self.last_trigger_time = 0

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
            self.throttle, self.aileron, self.elevator,
            self.rudder, self.aux
        )
        self.ser.write(data)
        self.ser.flush()

    def _deadzone(self, val):
        return val if (val is not None and abs(val) > DEADZONE) else None

    def _poll_joy_axes(self, now_ms):
        changed = False
        buttons, ev_count = self.joy.poll()
        self._joy_ev_count = ev_count
        for btn in buttons:
            self._joybutton(btn)
            changed = True

        ax = self._deadzone(self.joy.get_axis(self.ax_aileron))
        if ax is not None:
            v = max(1000, min(2000, int(1500 + ax * 500)))
            if v != self.aileron:
                self.aileron = v; changed = True
        elif self.aileron != 1500:
            self.aileron = 1500; changed = True

        ay = self._deadzone(self.joy.get_axis(self.ax_elevator))
        if ay is not None:
            v = max(1000, min(2000, int(1500 + ay * 500)))
            if v != self.elevator:
                self.elevator = v; changed = True
        elif self.elevator != 1500:
            self.elevator = 1500; changed = True

        rx = self._deadzone(self.joy.get_axis(self.ax_rudder))
        if rx is not None:
            v = max(1000, min(2000, int(1500 + rx * 500)))
            if v != self.rudder:
                self.rudder = v; changed = True
        elif self.rudder != 1500:
            self.rudder = 1500; changed = True

        if now_ms - self.last_trigger_time >= 100:
            l2 = self.joy.get_axis(self.ax_l2)
            if l2 > 0.1:
                self.throttle = min(2000, self.throttle + int(l2 * STEP))
                changed = True
            r2 = self.joy.get_axis(self.ax_r2)
            if r2 > 0.1:
                self.throttle = max(1000, self.throttle - int(r2 * STEP))
                changed = True
            self.last_trigger_time = now_ms

        if now_ms - self.last_hat_time >= 100:
            hat = self.joy.get_hat(0)
            if hat[0] == -1:
                self.aileron = max(1000, self.aileron - STEP); changed = True
            elif hat[0] == 1:
                self.aileron = min(2000, self.aileron + STEP); changed = True
            if hat[1] == 1:
                self.elevator = min(2000, self.elevator + STEP); changed = True
            elif hat[1] == -1:
                self.elevator = max(1000, self.elevator - STEP); changed = True
            self.last_hat_time = now_ms

        if changed:
            self.changed = True

    def _joybutton(self, button):
        if button == 4:   # L1
            self.throttle = 1000; self.changed = True
        elif button == 9:  # Start
            self.running = False

    def close(self):
        self.throttle = 1000
        self.send_state()
        self.ser.close()
        if self.joy:
            self.joy.close()

    def _print_bar(self, label, value):
        pct = (value - 1000) / 1000.0
        w = 10
        f = max(0, min(w, int(pct * w)))
        bar = "[" + "#" * f + "-" * (w - f) + "]"
        sys.stdout.write(f"{label}:{value:4d}{bar} ")
        sys.stdout.flush()


class TtyController(_BaseCtrl):
    """Terminal tabanli kontrol (Game Mode icin)."""
    def __init__(self, port):
        super().__init__(port)
        self._init_joystick()
        self._debug_seen = set()
        self._debug_start = time.monotonic()

    def _read_stdin_key(self):
        r, _, _ = sel.select([sys.stdin], [], [], 0.01)
        if not r:
            return None
        key = sys.stdin.read(1)
        if key == '\x1b':
            key += sys.stdin.read(2)
        return key

    def _handle_key(self, key):
        c = False
        if key in ('q', 'Q', '\x03'):
            self.running = False
        elif key == 'w':
            self.throttle = min(2000, self.throttle + STEP); c = True
        elif key == 's':
            self.throttle = max(1000, self.throttle - STEP); c = True
        elif key == ' ':
            self.throttle = 1000; c = True
        elif key == 'a':
            self.rudder = max(1000, self.rudder - STEP); c = True
        elif key == 'd':
            self.rudder = min(2000, self.rudder + STEP); c = True
        elif key == '\x1b[A':
            self.elevator = min(2000, self.elevator + STEP); c = True
        elif key == '\x1b[B':
            self.elevator = max(1000, self.elevator - STEP); c = True
        elif key == '\x1b[D':
            self.aileron = max(1000, self.aileron - STEP); c = True
        elif key == '\x1b[C':
            self.aileron = min(2000, self.aileron + STEP); c = True
        if c:
            self.changed = True

    def _debug(self, kind, num, val):
        if time.monotonic() - self._debug_start > 10:
            return
        key = (kind, num)
        if key in self._debug_seen:
            return
        if kind == "axis":
            if val is None or abs(val) < 0.05:
                return
            print(f"\n[DBG] axis {num:2d} = {val:+7.3f}")
        elif kind == "button":
            print(f"\n[DBG] btn  {num:2d} pressed")
        self._debug_seen.add(key)

    def _print_status(self):
        sys.stdout.write("\033[2K\r")
        self._print_bar("T", self.throttle)
        self._print_bar("A", self.aileron)
        self._print_bar("E", self.elevator)
        self._print_bar("D", self.rudder)
        if self.joy_connected:
            ay = self.joy.get_axis(self.ax_elevator)
            ax = self.joy.get_axis(self.ax_aileron)
            rx = self.joy.get_axis(self.ax_rudder)
            ev = getattr(self, '_joy_ev_count', 0)
            sys.stdout.write(f"| ail={ax:+.2f} elev={ay:+.2f} rudd={rx:+.2f} ev={ev}")
        sys.stdout.write("\n")
        sys.stdout.flush()

    def run(self):
        print("\n=== RC Plane Controller (Terminal) ===")
        print("W/S:Gaz A/D:Rudder Oklar:Ail/Elev Space:GazKes Q:Cikis\n")

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            last_print = 0
            while self.running:
                key = self._read_stdin_key()
                if key:
                    self._handle_key(key)

                if self.joy_connected:
                    self._poll_joy_axes(int(time.monotonic() * 1000))

                now = time.monotonic()
                if self.changed or now - self.last_send > 0.5:
                    self.send_state()
                    self.changed = False
                    self.last_send = now

                if now - last_print > 0.12:
                    self._print_status()
                    last_print = now

                time.sleep(0.02)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            print("\033[?25h")
            self.close()
            print("\nCikildi.")


# ═══════════════════════════════════════════════════════════════
# GuiController — Pygame penceresi (Desktop modu)
# ═══════════════════════════════════════════════════════════════

def _make_gui_controller():
    """pygame varsa GuiController sinifini dondurur."""
    import pygame

    BG      = (22, 22, 32)
    PANEL   = (38, 38, 52)
    BORDER  = (70, 70, 90)
    TXT_COL = (200, 200, 215)
    ACCENT  = (0, 210, 180)
    WARN    = (255, 120, 70)
    GREEN   = (80, 220, 80)
    AMBER   = (255, 200, 50)
    RED     = (240, 70, 60)
    DIM     = (90, 90, 110)

    class GuiController(_BaseCtrl):
        def __init__(self, port):
            super().__init__(port)

            pygame.init()
            self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
            pygame.display.set_caption("RC Plane Controller")
            self.clock = pygame.time.Clock()
            self.font_sm  = pygame.font.Font(None, 17)
            self.font     = pygame.font.Font(None, 22)
            self.font_md  = pygame.font.Font(None, 26)
            self.font_big = pygame.font.Font(None, 32)

            self._init_joystick()
            self._debug_start = pygame.time.get_ticks()
            self._debug_seen = set()
            self.send_state()

        def _debug(self, kind, num, val):
            if pygame.time.get_ticks() - self._debug_start > 5000:
                return
            key = (kind, num)
            if key in self._debug_seen:
                return
            if kind == "axis":
                if val is None or abs(val) < 0.05:
                    return
                print(f"[DBG] axis {num:2d} = {val:+7.3f}")
            elif kind == "button":
                print(f"[DBG] btn  {num:2d} pressed")
            self._debug_seen.add(key)

        def handle_events(self):
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    self._keydown(event.key)

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

        def draw(self):
            self.screen.fill(BG)
            pygame.draw.rect(self.screen, PANEL, (0, 0, WIDTH, 46))
            t = self.font_big.render("RC  Plane  Controller", True, ACCENT)
            self.screen.blit(t, (16, 8))

            if self.joy_connected:
                st = self.joy.get_name()[:32]
                sc = GREEN
            else:
                st = "Joystick yok — klavye modu"
                sc = WARN
            s = self.font_sm.render(st, True, sc)
            self.screen.blit(s, (WIDTH - s.get_width() - 14, 14))

            jax0 = self.joy.get_axis(self.ax_aileron) if self.joy_connected else 0.0
            jax1 = self.joy.get_axis(self.ax_elevator) if self.joy_connected else 0.0
            jax_r = self.joy.get_axis(self.ax_rudder) if self.joy_connected else 0.0
            jax4 = self.joy.get_axis(self.ax_l2) if self.joy_connected else 0.0
            jax5 = self.joy.get_axis(self.ax_r2) if self.joy_connected else 0.0

            self._draw_stick(190, 210, jax0, jax1, "AILERON", "ELEVATOR")
            self._draw_stick(590, 210, jax_r, 0.0, "RUDDER", "")

            bx, by, bw, bh = 110, 388, 580, 26
            pygame.draw.rect(self.screen, PANEL, (bx-3, by-3, bw+6, bh+6), border_radius=6)
            pygame.draw.rect(self.screen, (16, 16, 26), (bx, by, bw, bh), border_radius=4)
            pct = (self.throttle - 1000) / 1000.0
            fw = int(pct * bw)
            if fw > 0:
                if self.throttle <= 1500:
                    r, g = int(60 + 195 * (self.throttle-1000)/500), 230
                else:
                    r, g = 255, int(230 - 160 * (self.throttle-1500)/500)
                pygame.draw.rect(self.screen, (r, g, 55), (bx, by, fw, bh), border_radius=4)
            self.screen.blit(self.font.render("GAZ", True, TXT_COL), (bx - 42, by + 2))
            self.screen.blit(self.font_md.render(str(self.throttle), True, AMBER), (bx + bw + 12, by + 1))
            l2c = GREEN if jax4 > 0.1 else DIM
            r2c = RED if jax5 > 0.1 else DIM
            self.screen.blit(self.font_sm.render("L2 ▲", True, l2c), (bx + bw//2 - 55, by + 30))
            self.screen.blit(self.font_sm.render("R2 ▼", True, r2c), (bx + bw//2 + 18, by + 30))

            cy = 440
            channels = [
                ("T", self.throttle, AMBER), ("A", self.aileron, ACCENT),
                ("E", self.elevator, ACCENT), ("D", self.rudder, ACCENT),
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

            hy = 475
            hints = [
                ("W/S Gaz", TXT_COL), ("A/D Rudder", TXT_COL), ("← → Aileron", TXT_COL),
                ("↑ ↓ Elev", TXT_COL), ("Space GazKes", TXT_COL), ("Q/ESC Cikis", TXT_COL),
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

            vx = self.font_sm.render(f"{ax:+.2f}", True, TXT_COL)
            self.screen.blit(vx, (cx - vx.get_width()//2, cy + r + 30))
            vy = self.font_sm.render(f"{ay:+.2f}", True, TXT_COL)
            self.screen.blit(vy, (cx + r + 12, cy + 6))

        def run(self):
            pygame.key.set_repeat(200, 100)
            while self.running:
                self.handle_events()
                if self.joy_connected:
                    self._poll_joy_axes(pygame.time.get_ticks())

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
                self.joy.close()
            pygame.quit()
            print("\nCikildi.")

    return GuiController


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def find_port():
    ports = glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.usbmodem*")
    if ports:
        return ports[0]
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if ports:
        return ports[0]
    return None


if __name__ == "__main__":
    tty_mode = "--tty" in sys.argv
    port = None
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            port = arg

    if port is None:
        port = find_port()

    if port is None:
        print("Seri port bulunamadi!")
        print("Elle belirt: python3 control.py [--tty] /dev/cu.usbserial-XXXX")
        sys.exit(1)

    print(f"Port: {port}")

    if tty_mode:
        ctrl = TtyController(port)
    else:
        try:
            GuiController = _make_gui_controller()
            ctrl = GuiController(port)
        except Exception as e:
            print(f"GUI baslatilamadi: {e}")
            print("Terminal moduna geciliyor...")
            ctrl = TtyController(port)

    try:
        ctrl.run()
    except KeyboardInterrupt:
        ctrl.close()
    print("\nCikildi.")
