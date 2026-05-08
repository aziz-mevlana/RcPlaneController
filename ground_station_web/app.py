"""
RC Ucak Yer Istasyonu - Web Tabanlı Arayüz
Flask + WebSocket + Arduino seri haberleşme
"""

import time
import csv
import struct
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
import serial
import serial.tools.list_ports

# === Sabitler ===
SERVO_MIN = 1000
SERVO_CENTER = 1500
SERVO_MAX = 2000
THROTTLE_MIN = 1000
THROTTLE_MAX = 2000

CMD_HEADER = 0xC0
CMD_TERMINATOR = 0x0A
CMD_PACKET_SIZE = 11

app = Flask(__name__)
app.config['SECRET_KEY'] = 'rc-plane-controller'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')


class SerialComm:
    """Arduino ile seri haberleşme"""
    def __init__(self):
        self.port = None
        self.baud = 115200
        self.connected = False
        self.serial = None
        self.tx_count = 0
        self.rx_count = 0

    def find_arduino(self):
        """Arduino portunu otomatik bul (macOS ve Linux destegi)"""
        ports = serial.tools.list_ports.comports()
        for p in ports:
            desc = (p.description or "").lower()
            dev = p.device or ""
            # macOS: tty.usbmodem, tty.usbserial
            # Linux: ttyACM, ttyUSB
            # Windows: COM
            if any(kw in desc for kw in ["arduino", "ch340", "cp210", "usb serial"]):
                return p.device
            if any(kw in dev for kw in ["ttyACM", "ttyUSB", "tty.usbmodem", "tty.usbserial", "COM"]):
                return p.device
        return None

    def connect(self, port=None):
        if port is None:
            port = self.find_arduino()
        if port is None:
            return False
        try:
            self.serial = serial.Serial(port, self.baud, timeout=0.01)
            time.sleep(2)  # Arduino reset bekle
            self.port = port
            self.connected = True
            print(f"Arduino baglandi: {port}")
            return True
        except Exception as e:
            print(f"Baglanti hatasi: {e}")
            return False

    def disconnect(self):
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.connected = False
        self.port = None
        print("Arduino baglantisi kesildi")

    def send_control(self, aileron, elevator, rudder, throttle):
        if not self.connected or not self.serial:
            return
        ch1 = int(max(SERVO_MIN, min(SERVO_MAX, aileron)))
        ch2 = int(max(SERVO_MIN, min(SERVO_MAX, elevator)))
        ch3 = int(max(SERVO_MIN, min(SERVO_MAX, rudder)))
        ch4 = int(max(THROTTLE_MIN, min(THROTTLE_MAX, throttle)))

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

        crc = 0
        for i in range(CMD_PACKET_SIZE - 2):
            crc ^= packet[i]
        packet[9] = crc
        packet[10] = CMD_TERMINATOR

        try:
            self.serial.write(packet)
            self.tx_count += 1
        except Exception as e:
            print(f"Seri yazma hatasi: {e}")
            self.connected = False

    def read_telemetry(self):
        """Arduino'dan telemetri oku - hata toleransli"""
        if not self.connected or not self.serial:
            return None
        try:
            # Baglanti hala aktif mi kontrol et
            if not self.serial.is_open:
                self.connected = False
                return None

            while self.serial.in_waiting > 0:
                line = self.serial.readline().decode('ascii', errors='ignore').strip()
                if line.startswith("TEL:"):
                    data = line[4:]
                    parts = data.split(',')
                    if len(parts) == 3:
                        self.rx_count += 1
                        return {
                            'battery_mv': int(parts[0]),
                            'rssi': int(parts[1]),
                            'flags': int(parts[2]),
                            'connected': True
                        }
                elif line == "TEL:DISCONNECTED":
                    return {'connected': False}
                elif line == "VERICI HAZIR":
                    print("Verici hazir mesaji alindi")
        except serial.SerialException as e:
            print(f"Seri port hatasi: {e}")
            self.connected = False
        except Exception:
            pass
            pass
        return None


# Global state
serial_comm = SerialComm()
channels = {
    'aileron': SERVO_CENTER,
    'elevator': SERVO_CENTER,
    'rudder': SERVO_CENTER,
    'throttle': THROTTLE_MIN
}
telemetry = {
    'battery_mv': 0,
    'battery_v': 0.0,
    'battery_percent': 0,
    'battery_critical': False,
    'rssi': 0,
    'connected': False,
    'failsafe': False
}
send_rate = 50
last_send = 0
flight_start = time.time()
flight_log = None
log_lock = threading.Lock()


def telemetry_loop():
    """Arka plan telemetri okuma döngüsü"""
    global telemetry
    while True:
        data = serial_comm.read_telemetry()
        if data:
            if data.get('connected') is False:
                telemetry['connected'] = False
            else:
                telemetry['battery_mv'] = data['battery_mv']
                telemetry['battery_v'] = data['battery_mv'] / 1000.0
                telemetry['battery_percent'] = max(0, min(100,
                    (telemetry['battery_v'] - 9.9) / (12.6 - 9.9) * 100))
                telemetry['battery_critical'] = telemetry['battery_v'] < 10.2
                telemetry['rssi'] = data['rssi']
                telemetry['connected'] = data['connected']
                telemetry['failsafe'] = bool(data['flags'] & 0x01)

                socketio.emit('telemetry', telemetry)
        time.sleep(0.05)


# === Routes ===
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    return jsonify({
        'serial_connected': serial_comm.connected,
        'port': serial_comm.port,
        'tx_count': serial_comm.tx_count,
        'rx_count': serial_comm.rx_count,
        'channels': channels,
        'telemetry': telemetry,
        'flight_time': time.time() - flight_start
    })


# === WebSocket Events ===
@socketio.on('connect')
def handle_connect():
    print(f'Istemci baglandi')
    emit('status', {
        'serial_connected': serial_comm.connected,
        'port': serial_comm.port,
        'channels': channels,
        'telemetry': telemetry,
        'flight_time': time.time() - flight_start
    })


@socketio.on('control')
def handle_control(data):
    """Joystick/klavye kontrol verisi al"""
    global channels, last_send
    channels['aileron'] = max(SERVO_MIN, min(SERVO_MAX, data.get('aileron', SERVO_CENTER)))
    channels['elevator'] = max(SERVO_MIN, min(SERVO_MAX, data.get('elevator', SERVO_CENTER)))
    channels['rudder'] = max(SERVO_MIN, min(SERVO_MAX, data.get('rudder', SERVO_CENTER)))
    channels['throttle'] = max(THROTTLE_MIN, min(THROTTLE_MAX, data.get('throttle', THROTTLE_MIN)))

    now = time.time()
    if now - last_send >= 1.0 / send_rate:
        last_send = now
        serial_comm.send_control(
            channels['aileron'], channels['elevator'],
            channels['rudder'], channels['throttle']
        )

    emit('channels', channels)


@socketio.on('connect_arduino')
def handle_connect_arduino():
    if serial_comm.connect():
        emit('arduino_status', {'connected': True, 'port': serial_comm.port})
    else:
        emit('arduino_status', {'connected': False, 'error': 'Arduino bulunamadi'})


@socketio.on('disconnect_arduino')
def handle_disconnect_arduino():
    serial_comm.disconnect()
    emit('arduino_status', {'connected': False})


@socketio.on('toggle_log')
def handle_toggle_log():
    global flight_log
    with log_lock:
        if flight_log is None:
            log_dir = Path(__file__).parent / "logs"
            log_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = log_dir / f"flight_{timestamp}.csv"
            flight_log = open(filepath, 'w', newline='')
            writer = csv.writer(flight_log)
            writer.writerow(['timestamp', 'aileron', 'elevator', 'rudder', 'throttle',
                             'battery_v', 'rssi', 'failsafe', 'connected'])
            emit('log_status', {'logging': True, 'file': str(filepath)})
        else:
            flight_log.close()
            flight_log = None
            emit('log_status', {'logging': False})


@socketio.on('request_state')
def handle_request_state():
    emit('full_state', {
        'serial_connected': serial_comm.connected,
        'port': serial_comm.port,
        'tx_count': serial_comm.tx_count,
        'rx_count': serial_comm.rx_count,
        'channels': channels,
        'telemetry': telemetry,
        'flight_time': time.time() - flight_start
    })


if __name__ == '__main__':
    # Telemetri arka plan thread
    tel_thread = threading.Thread(target=telemetry_loop, daemon=True)
    tel_thread.start()

    print("=== RC Ucak Yer Istasyonu (Web) ===")
    print("Tarayici: http://localhost:8080")
    print("Steam Deck: http://localhost:8080")
    socketio.run(app, host='0.0.0.0', port=8080, debug=False, allow_unsafe_werkzeug=True)
