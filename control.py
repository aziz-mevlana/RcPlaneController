#!/usr/bin/env python3
"""
RC Plane Controller - Klavye + Joystick Kontrol
Gereksinimler: pip3 install pyserial pygame

Kontroller (Klavye):
  W/S       -> Gaz artir/azalt
  A/D       -> Rudder (kuyruk dikey) sol/sag
  Yukari/Asagi ok -> Elevator (kuyruk yatay)
  Sol/Sag ok       -> Aileron (kanat roll - dual aileron otomatik)
  Bosluk    -> Gaz kes (1000)
  Q         -> Cikis

Kontroller (Joystick - Steam Deck):
  Sol Stick X  -> Aileron (kanat roll)
  Sol Stick Y  -> Elevator (kuyruk yatay)
  Sag Stick X  -> Rudder (kuyruk dikey)
  L2 Trigger   -> Gaz artir
  R2 Trigger   -> Gaz azalt
  L1 Bumper    -> Gaz kes (acil durum)
  D-Pad        -> Aileron/Elevator (yedek)
  Start/Plus   -> Cikis
"""

import sys
import os
import time
import struct
import select
import serial
import termios
import tty

BAUD = 115200
STEP = 50
DEADZONE = 0.08

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class JoystickHandler:
    def __init__(self):
        self.connected = False
        self.joy_name = None
        self.axes = {}
        self.buttons = {}
        self.hats = {}
        self.num_axes = 0
        self.num_buttons = 0
        self._prev_buttons = {}

    def init(self):
        if not PYGAME_AVAILABLE:
            return False
        pygame.init()
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count == 0:
            print("Joystick bulunamadi!")
            return False
        joy = pygame.joystick.Joystick(0)
        joy.init()
        self.joy_name = joy.get_name()
        self.num_axes = joy.get_numaxes()
        self.num_buttons = joy.get_numbuttons()
        self.connected = True
        for i in range(self.num_axes):
            self.axes[i] = 0.0
        for i in range(self.num_buttons):
            self.buttons[i] = False
            self._prev_buttons[i] = False
        hat_count = joy.get_numhats()
        for i in range(hat_count):
            self.hats[i] = (0, 0)
        print(f"Joystick baglandi: {self.joy_name}")
        print(f"  Eksen: {self.num_axes}, Buton: {self.num_buttons}, Hat: {hat_count}")
        return True

    def update(self):
        if not self.connected:
            return False, False
        pygame.event.pump()
        joy = pygame.joystick.Joystick(0)
        for i in range(self.num_axes):
            val = joy.get_axis(i)
            if abs(val) < DEADZONE:
                val = 0.0
            self.axes[i] = val
        new_presses = []
        for i in range(self.num_buttons):
            pressed = joy.get_button(i) == 1
            if pressed and not self._prev_buttons.get(i, False):
                new_presses.append(i)
            self._prev_buttons[i] = pressed
            self.buttons[i] = pressed
        for i in range(joy.get_numhats()):
            self.hats[i] = joy.get_hat(i)
        return True, new_presses

    def get_axis(self, axis_id):
        if axis_id in self.axes:
            return self.axes[axis_id]
        return 0.0

    def get_button(self, btn_id):
        return self.buttons.get(btn_id, False)

    def get_hat(self, hat_id):
        return self.hats.get(hat_id, (0, 0))

    def close(self):
        if self.connected:
            pygame.joystick.quit()
            pygame.quit()
            self.connected = False


class RcController:
    def __init__(self, port, use_joystick=False):
        self.ser = serial.Serial(port, BAUD, timeout=0)
        time.sleep(2)
        self.throttle = 1000
        self.aileron = 1500
        self.elevator = 1500
        self.rudder = 1500
        self.aux = 1500
        self.running = True
        self.joy = JoystickHandler() if use_joystick else None
        if self.joy:
            self.joy.init()
        self.send_state()

    def send_state(self):
        data = b'\xaa' + struct.pack("<HHHHH",
            self.throttle,
            self.aileron,
            self.elevator,
            self.rudder,
            self.aux
        )
        self.ser.write(data)
        self.ser.flush()
        self.print_state()

    def _bar(self, value, width=20):
        pct = (value - 1000) / 1000.0
        filled = max(0, min(width, int(pct * width)))
        return "|" + "█" * filled + "░" * (width - filled) + "|"

    def _axis_bar(self, value, width=10):
        normalized = (value + 1.0) / 2.0
        filled = max(0, min(width, int(normalized * width)))
        return "|" + "█" * filled + "░" * (width - filled) + "|"

    def print_state(self):
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write("=== RC Plane Kontrol ===\n")
        sys.stdout.write("W/S: Gaz  A/D: Rudder  Oklar: Elev/Aileron  Space: Kes  Q: Cikis\n")

        if self.joy and self.joy.connected:
            sys.stdout.write(f"\n  Joystick: {self.joy.joy_name}\n")
            sys.stdout.write(f"  Axes: {self.joy.num_axes}  Buttons: {self.joy.num_buttons}\n")
            sys.stdout.write("\n")
            sys.stdout.write("  Joy Axes:\n")
            for i, v in self.joy.axes.items():
                bar = self._axis_bar(v)
                sys.stdout.write(f"    Axis {i}: {v:+.2f}  {bar}\n")
            sys.stdout.write("  Joy Buttons:\n")
            for i, v in self.joy.buttons.items():
                state = "BASILI" if v else "---"
                sys.stdout.write(f"    Button {i}: {state}\n")
            if self.joy.hats:
                sys.stdout.write("  Joy Hats:\n")
                for i, v in self.joy.hats.items():
                    sys.stdout.write(f"    Hat {i}: {v}\n")
        else:
            sys.stdout.write("\n  Joystick: Bagli degil\n")

        sys.stdout.write("\n")
        sys.stdout.write("  Gaz       {:4d}  {}\n".format(self.throttle, self._bar(self.throttle)))
        sys.stdout.write("  Aileron   {:4d}  {}\n".format(self.aileron, self._bar(self.aileron)))
        sys.stdout.write("  Elevator  {:4d}  {}\n".format(self.elevator, self._bar(self.elevator)))
        sys.stdout.write("  Rudder    {:4d}  {}\n".format(self.rudder, self._bar(self.rudder)))
        sys.stdout.write("\n  (Alicida dual aileron mix: Sag=D5, Sol=D4)\n")
        sys.stdout.write("\n")
        sys.stdout.flush()

    def handle_key(self, key):
        if key == 'q':
            self.running = False
            return

        if key == 'w':
            self.throttle = min(2000, self.throttle + STEP)
        elif key == 's':
            self.throttle = max(1000, self.throttle - STEP)
        elif key == ' ':
            self.throttle = 1000
        elif key == 'a':
            self.rudder = max(1000, self.rudder - STEP)
        elif key == 'd':
            self.rudder = min(2000, self.rudder + STEP)
        elif key == '\x1b[A':  # yukari
            self.elevator = min(2000, self.elevator + STEP)
        elif key == '\x1b[B':  # asagi
            self.elevator = max(1000, self.elevator - STEP)
        elif key == '\x1b[D':  # sol
            self.aileron = max(1000, self.aileron - STEP)
        elif key == '\x1b[C':  # sag
            self.aileron = min(2000, self.aileron + STEP)

        self.send_state()

    def handle_joystick(self):
        if not self.joy or not self.joy.connected:
            return
        changed = False

        alive, new_presses = self.joy.update()
        if not alive:
            return

        aileron_raw = self.joy.get_axis(0)
        if aileron_raw != 0.0:
            self.aileron = int(1500 + aileron_raw * 500)
            self.aileron = max(1000, min(2000, self.aileron))
            changed = True
        elif not self.joy.get_button(11) and not self.joy.get_button(12):
            pass

        elevator_raw = self.joy.get_axis(1)
        if elevator_raw != 0.0:
            self.elevator = int(1500 + elevator_raw * 500)
            self.elevator = max(1000, min(2000, self.elevator))
            changed = True

        rudder_raw = self.joy.get_axis(3)
        if rudder_raw != 0.0:
            self.rudder = int(1500 + rudder_raw * 500)
            self.rudder = max(1000, min(2000, self.rudder))
            changed = True

        l2_raw = self.joy.get_axis(4)
        if l2_raw > 0.1:
            self.throttle = min(2000, self.throttle + int(l2_raw * STEP))
            changed = True

        r2_raw = self.joy.get_axis(5)
        if r2_raw > 0.1:
            self.throttle = max(1000, self.throttle - int(r2_raw * STEP))
            changed = True

        hat = self.joy.get_hat(0)
        if hat[0] == -1:
            self.aileron = max(1000, self.aileron - STEP)
            changed = True
        elif hat[0] == 1:
            self.aileron = min(2000, self.aileron + STEP)
            changed = True
        if hat[1] == 1:
            self.elevator = min(2000, self.elevator + STEP)
            changed = True
        elif hat[1] == -1:
            self.elevator = max(1000, self.elevator - STEP)
            changed = True

        for btn_id in new_presses:
            if btn_id == 4:
                self.throttle = 1000
                changed = True
            elif btn_id == 9:
                self.running = False

        if changed:
            self.send_state()

    def close(self):
        self.throttle = 1000
        self.send_state()
        self.ser.close()
        if self.joy:
            self.joy.close()
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def run(self):
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            last_send = 0
            while self.running:
                if self.joy and self.joy.connected:
                    self.handle_joystick()

                r, _, _ = select.select([sys.stdin], [], [], 0.02)
                if r:
                    key = sys.stdin.read(1)
                    if key == '\x1b':
                        seq = sys.stdin.read(2)
                        key += seq
                    self.handle_key(key)
                    last_send = time.time()
                elif time.time() - last_send > 0.2:
                    self.send_state()
                    last_send = time.time()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
            self.close()

def find_port():
    import glob
    ports = glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.usbmodem*")
    if ports:
        return ports[0]
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if ports:
        return ports[0]
    return None

if __name__ == "__main__":
    use_joystick = "--joystick" in sys.argv
    port = None

    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            port = arg

    if port is None:
        port = find_port()

    if port is None:
        print("Seri port bulunamadi!")
        print("Elle belirt: python3 control.py [--joystick] /dev/cu.usbserial-XXXX")
        sys.exit(1)

    print(f"Port: {port}")
    print()
    print("=== RC Plane Klavye + Joystick Kontrol ===")
    print()
    print("  Klavye:")
    print("    W/S       : Gaz artir/azalt")
    print("    A/D       : Rudder (kuyruk dikey)")
    print("    Yukari/As : Elevator (kuyruk yatay)")
    print("    Sol/Sag   : Aileron (kanat roll)")
    print("    Space     : Gaz kes (acil durum)")
    print("    Q         : Cikis")

    if use_joystick:
        if not PYGAME_AVAILABLE:
            print("\n  HATA: pygame yuklu degil! pip3 install pygame")
            sys.exit(1)
        print()
        print("  Joystick (Steam Deck):")
        print("    Sol Stick X  : Aileron (kanat roll)")
        print("    Sol Stick Y  : Elevator (kuyruk yatay)")
        print("    Sag Stick X  : Rudder (kuyruk dikey)")
        print("    L2           : Gaz artir")
        print("    R2           : Gaz azalt")
        print("    L1           : Gaz kes (acil durum)")
        print("    D-Pad        : Aileron/Elevator (yedek)")
        print("    Start/Plus   : Cikis")

    print()

    ctrl = RcController(port, use_joystick=use_joystick)
    try:
        ctrl.run()
    except KeyboardInterrupt:
        ctrl.close()
    print("\nCikildi.")
