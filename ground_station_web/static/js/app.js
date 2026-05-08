/**
 * RC Uçak Yer İstasyonu - Web Arayüzü
 * Three.js 3D Spitfire + WebSocket + Input Yönetimi
 * 
 * Koordinat sistemi (Three.js kamera -Z'ye bakar):
 *   -Z = uçak önü (burun)
 *   +Y = yukarı
 *   +X = sağ kanat
 */

// === Sabitler ===
const SERVO_MIN = 1000, SERVO_CENTER = 1500, SERVO_MAX = 2000;
const THROTTLE_MIN = 1000, THROTTLE_MAX = 2000;
const SMOOTH = 0.15;

// === State ===
const state = {
    channels: { aileron: 1500, elevator: 1500, rudder: 1500, throttle: 1000 },
    targetChannels: { aileron: 1500, elevator: 1500, rudder: 1500, throttle: 1000 },
    simAngles: { roll: 0, pitch: 0, yaw: 0 },
    telemetry: { battery_v: 0, battery_percent: 0, battery_critical: false, rssi: 0, connected: false, failsafe: false },
    serialConnected: false,
    logging: false,
    flightStart: Date.now(),
    keysDown: new Set()
};

// === WebSocket ===
const socket = io();

socket.on('connect', () => {
    console.log('WebSocket bağlandı');
    socket.emit('request_state');
});

socket.on('status', (data) => {
    updateConnectionStatus(data.serial_connected, data.port);
});

socket.on('telemetry', (data) => {
    Object.assign(state.telemetry, data);
    updateTelemetryUI();
});

socket.on('channels', (data) => {
    Object.assign(state.channels, data);
});

socket.on('arduino_status', (data) => {
    updateConnectionStatus(data.connected, data.port);
});

socket.on('full_state', (data) => {
    state.serialConnected = data.serial_connected;
    Object.assign(state.channels, data.channels);
    Object.assign(state.telemetry, data.telemetry);
    state.flightStart = Date.now() - (data.flight_time * 1000);
    updateConnectionStatus(data.serial_connected, data.port);
    updateTelemetryUI();
});

socket.on('log_status', (data) => {
    state.logging = data.logging;
    const btn = document.getElementById('btnLog');
    if (data.logging) {
        btn.textContent = '⏹ Durdur';
        btn.classList.add('active');
    } else {
        btn.textContent = '⏺ Log Başlat';
        btn.classList.remove('active');
    }
});

// === UI Updates ===
function updateConnectionStatus(connected, port) {
    state.serialConnected = connected;
    const dot = document.getElementById('statusDot');
    const label = document.getElementById('connLabel');
    const connBtn = document.getElementById('btnConnect');
    const discBtn = document.getElementById('btnDisconnect');
    const connPort = document.getElementById('connPort');
    const connStatus = document.getElementById('connStatus');

    if (connected) {
        dot.classList.add('connected');
        label.textContent = 'UÇAK: BAĞLI';
        label.className = 'status-label status-connected';
        connBtn.style.display = 'none';
        discBtn.style.display = '';
        connPort.textContent = port || '—';
        connStatus.textContent = 'Bağlı';
        connStatus.style.color = 'var(--green)';
    } else {
        dot.classList.remove('connected');
        label.textContent = 'UÇAK: BAĞLI DEĞİL';
        label.className = 'status-label status-disconnected';
        connBtn.style.display = '';
        discBtn.style.display = 'none';
        connPort.textContent = '—';
        connStatus.textContent = 'Bağlı değil';
        connStatus.style.color = 'var(--red)';
    }
}

function updateTelemetryUI() {
    const t = state.telemetry;
    const battFill = document.getElementById('batteryFill');
    const battV = document.getElementById('batteryVoltage');
    const battPct = document.getElementById('batteryPercent');
    battFill.style.width = t.battery_percent + '%';
    battFill.className = 'battery-bar-fill' +
        (t.battery_critical ? ' critical' : t.battery_percent < 30 ? ' warning' : '');
    battV.textContent = t.battery_v.toFixed(1) + 'V';
    battPct.textContent = Math.round(t.battery_percent) + '%';
    battPct.style.color = t.battery_critical ? 'var(--red)' : t.battery_percent < 30 ? 'var(--orange)' : 'var(--green)';

    const rssiVal = document.getElementById('rssiValue');
    const rssiStat = document.getElementById('rssiStatus');
    rssiVal.textContent = t.rssi + '%';
    for (let i = 1; i <= 5; i++) {
        const bar = document.getElementById('sigBar' + i);
        const threshold = i * 20;
        bar.className = 'signal-bar';
        if (t.rssi >= threshold && t.connected) {
            bar.classList.add(i <= 2 ? 'active-1' : i <= 4 ? 'active-2' : 'active-3');
        }
        bar.style.height = (i * 7 + 3) + 'px';
    }
    if (t.connected) {
        rssiStat.textContent = 'BAĞLI';
        rssiStat.className = 'signal-status connected';
    } else {
        rssiStat.textContent = 'BAĞLI DEĞİL';
        rssiStat.className = 'signal-status';
    }
    document.getElementById('failsafeOverlay').style.display = t.failsafe ? '' : 'none';
}

function updateChannelBars() {
    const c = state.channels;
    const lerp = (a, b, t) => a + (b - a) * t;

    state.channels.aileron = lerp(state.channels.aileron, state.targetChannels.aileron, SMOOTH);
    state.channels.elevator = lerp(state.channels.elevator, state.targetChannels.elevator, SMOOTH);
    state.channels.rudder = lerp(state.channels.rudder, state.targetChannels.rudder, SMOOTH);
    state.channels.throttle = lerp(state.channels.throttle, state.targetChannels.throttle, SMOOTH);

    const norm = (v) => ((v - SERVO_MIN) / (SERVO_MAX - SERVO_MIN) * 100).toFixed(1);
    const setBar = (id, chId, value) => {
        document.getElementById(id).style.width = norm(value) + '%';
        document.getElementById(chId).textContent = Math.round(value);
    };
    setBar('barAileron', 'chAileron', c.aileron);
    setBar('barElevator', 'chElevator', c.elevator);
    setBar('barRudder', 'chRudder', c.rudder);

    const thrNorm = ((c.throttle - THROTTLE_MIN) / (THROTTLE_MAX - THROTTLE_MIN) * 100).toFixed(1);
    document.getElementById('barThrottle').style.height = thrNorm + '%';
    document.getElementById('chThrottle').textContent = Math.round(c.throttle);

    // Joystick göstergeleri
    const joyNorm = (v) => ((v - SERVO_MIN) / (SERVO_MAX - SERVO_MIN) * 100);
    document.getElementById('joyLeftHandle').style.left = joyNorm(c.aileron) + '%';
    document.getElementById('joyLeftHandle').style.top = joyNorm(3000 - c.elevator) + '%';
    document.getElementById('joyRightHandle').style.left = joyNorm(c.rudder) + '%';
    document.getElementById('joyRightHandle').style.top = joyNorm(3000 - c.throttle) + '%';
}

function updateFlightTimer() {
    const elapsed = Math.floor((Date.now() - state.flightStart) / 1000);
    const h = Math.floor(elapsed / 3600);
    const m = Math.floor((elapsed % 3600) / 60);
    const s = elapsed % 60;
    document.getElementById('flightTimer').textContent =
        `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

// ============================================================
// === Three.js 3D Model ===
// ============================================================
let scene, camera, renderer, aircraft;
let targetRoll = 0, targetPitch = 0, targetYaw = 0;

function initThreeJS() {
    const container = document.getElementById('simContainer');
    const w = container.clientWidth;
    const h = container.clientHeight;

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
    // Kamera sağ-üst-arkadan bakıyor
    camera.position.set(2.5, 1.5, 3.5);
    camera.lookAt(0, 0, 0);

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // Işıklandırma
    scene.add(new THREE.AmbientLight(0x445566, 0.7));
    const sun = new THREE.DirectionalLight(0xffffff, 0.9);
    sun.position.set(3, 5, 2);
    scene.add(sun);
    const fill = new THREE.DirectionalLight(0x6688aa, 0.3);
    fill.position.set(-3, 0, -2);
    scene.add(fill);

    aircraft = buildAircraft();
    scene.add(aircraft);

    // Alt referans düzlemi (silik)
    const gridGeo = new THREE.PlaneGeometry(6, 6);
    const gridMat = new THREE.MeshBasicMaterial({ color: 0x0a2010, transparent: true, opacity: 0.3, side: THREE.DoubleSide });
    const grid = new THREE.Mesh(gridGeo, gridMat);
    grid.rotation.x = -Math.PI / 2;
    grid.position.y = -1.8;
    scene.add(grid);

    window.addEventListener('resize', () => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
    });
}

/**
 * Basit gerçekçi uçak modeli
 * Koordinat: -Z burun, +Y yukarı, +X sağ kanat
 */
function buildAircraft() {
    const g = new THREE.Group();

    // Malzemeler
    const green = new THREE.MeshPhongMaterial({ color: 0x3a6632, flatShading: true });
    const gray = new THREE.MeshPhongMaterial({ color: 0x889098, flatShading: true });
    const dark = new THREE.MeshPhongMaterial({ color: 0x444850, flatShading: true });
    const glass = new THREE.MeshPhongMaterial({ color: 0x4499cc, transparent: true, opacity: 0.45, flatShading: true });
    const propMat = new THREE.MeshPhongMaterial({ color: 0x555555, flatShading: true });
    const navRed = new THREE.MeshBasicMaterial({ color: 0xff2200 });
    const navGrn = new THREE.MeshBasicMaterial({ color: 0x00cc44 });

    // === GÖVDE ===
    // Silindir gövde (burun -Z yönünde)
    const bodyGeo = new THREE.CylinderGeometry(0.07, 0.045, 2.0, 8);
    const body = new THREE.Mesh(bodyGeo, green);
    body.rotation.x = Math.PI / 2; // X ekseninde döndür → silindir Z ekseninde uzanır
    g.add(body);

    // Burun konisi
    const noseGeo = new THREE.ConeGeometry(0.07, 0.3, 8);
    const nose = new THREE.Mesh(noseGeo, dark);
    nose.rotation.x = Math.PI / 2;
    nose.position.z = -1.15;
    g.add(nose);

    // Kokpit kabini
    const canopyGeo = new THREE.SphereGeometry(0.08, 8, 6, 0, Math.PI * 2, 0, Math.PI * 0.55);
    const canopy = new THREE.Mesh(canopyGeo, glass);
    canopy.position.set(0, 0.06, 0.2);
    canopy.scale.set(1, 0.7, 1.5);
    g.add(canopy);

    // === KANATLAR ===
    // Sol kanat
    const wingGeo = new THREE.BoxGeometry(1.4, 0.025, 0.3);
    const wingL = new THREE.Mesh(wingGeo, green);
    wingL.position.set(-0.75, -0.01, 0);
    g.add(wingL);

    // Sağ kanat
    const wingR = new THREE.Mesh(wingGeo, green);
    wingR.position.set(0.75, -0.01, 0);
    g.add(wingR);

    // Kanat uç nav ışıkları
    const navGeo = new THREE.SphereGeometry(0.018, 6, 6);
    const navL = new THREE.Mesh(navGeo, navRed);
    navL.position.set(-1.45, -0.01, 0);
    g.add(navL);
    const navR = new THREE.Mesh(navGeo, navGrn);
    navR.position.set(1.45, -0.01, 0);
    g.add(navR);

    // === KUYRUK ===
    // Yatay stabilize
    const hTailGeo = new THREE.BoxGeometry(0.55, 0.02, 0.18);
    const hTail = new THREE.Mesh(hTailGeo, green);
    hTail.position.set(0, 0.02, 0.9);
    g.add(hTail);

    // Dikey stabilize
    const vTailGeo = new THREE.BoxGeometry(0.02, 0.3, 0.22);
    const vTail = new THREE.Mesh(vTailGeo, green);
    vTail.position.set(0, 0.17, 0.88);
    g.add(vTail);

    // === PERVANE ===
    const propGeo = new THREE.BoxGeometry(0.45, 0.015, 0.03);
    const prop1 = new THREE.Mesh(propGeo, propMat);
    prop1.position.z = -1.3;
    g.add(prop1);
    const prop2 = new THREE.Mesh(propGeo, propMat);
    prop2.position.z = -1.3;
    prop2.rotation.z = Math.PI / 2;
    g.add(prop2);

    // Spinner
    const spinGeo = new THREE.ConeGeometry(0.03, 0.08, 6);
    const spin = new THREE.Mesh(spinGeo, propMat);
    spin.rotation.x = Math.PI / 2;
    spin.position.z = -1.35;
    g.add(spin);

    return g;
}

/**
 * Kanal değerlerinden hedef açıları hesapla
 * Aileron (sol stick X): sola = roll sol, sağa = roll sağ
 * Elevator (sol stick Y): geri = pitch yukarı (burun yukarı), ileri = pitch aşağı
 * Rudder (sağ stick X): sola = yaw sol, sağa = yaw sağ
 */
function updateAircraftFromChannels() {
    const c = state.channels;
    const normAil = (c.aileron - SERVO_CENTER) / (SERVO_MAX - SERVO_MIN);   // -1 sol, +1 sağ
    const normElev = (c.elevator - SERVO_CENTER) / (SERVO_MAX - SERVO_MIN);  // +1 yukarı (geri çek), -1 aşağı
    const normRud = (c.rudder - SERVO_CENTER) / (SERVO_MAX - SERVO_MIN);     // -1 sol, +1 sağ

    // Sol stick sola → uçak sola yatar (roll negatif = sol kanat aşağı)
    targetRoll = normAil * (Math.PI / 4);
    // Sol stick geri → burun yukarı (pitch pozitif)
    targetPitch = normElev * (Math.PI / 6);
    // Sağ stick sola → burun sola döner (yaw pozitif - Y ekseni)
    targetYaw = normRud * (Math.PI / 5);
}

function animateThreeJS() {
    requestAnimationFrame(animateThreeJS);

    if (aircraft) {
        state.simAngles.roll += (targetRoll - state.simAngles.roll) * 0.1;
        state.simAngles.pitch += (targetPitch - state.simAngles.pitch) * 0.1;
        state.simAngles.yaw += (targetYaw - state.simAngles.yaw) * 0.1;

        // YXZ sıralaması: önce yaw(Y), sonra pitch(X), sonra roll(Z)
        aircraft.rotation.order = 'YXZ';
        aircraft.rotation.y = state.simAngles.yaw;
        aircraft.rotation.x = state.simAngles.pitch;
        aircraft.rotation.z = state.simAngles.roll;

        const rollDeg = Math.round(state.simAngles.roll * 180 / Math.PI);
        const pitchDeg = Math.round(state.simAngles.pitch * 180 / Math.PI);
        const yawDeg = Math.round(state.simAngles.yaw * 180 / Math.PI);
        document.getElementById('simAngles').textContent =
            `Roll: ${rollDeg}°  Pitch: ${pitchDeg}°  Yaw: ${yawDeg}°`;
    }

    renderer.render(scene, camera);
}

// ============================================================
// === Compass Strip ===
// ============================================================
const compassLabels = { 0: 'N', 45: 'NE', 90: 'E', 135: 'SE', 180: 'S', 225: 'SW', 270: 'W', 315: 'NW' };

function initCompass() {
    const track = document.getElementById('compassTrack');
    track.innerHTML = '';
    for (let deg = 0; deg < 360; deg += 5) {
        const tick = document.createElement('div');
        tick.className = 'compass-tick';
        tick.dataset.deg = deg;
        const isCardinal = deg % 90 === 0;
        const isMajor = deg % 30 === 0;
        if (isCardinal) {
            tick.classList.add('cardinal');
            tick.innerHTML = `<span class="compass-tick-label">${compassLabels[deg]}</span><div class="compass-tick-line"></div>`;
        } else if (isMajor) {
            tick.classList.add('major');
            tick.innerHTML = `<span class="compass-tick-label">${compassLabels[deg] || deg}</span><div class="compass-tick-line"></div>`;
        } else {
            tick.classList.add('minor');
            tick.innerHTML = `<div class="compass-tick-line"></div>`;
        }
        track.appendChild(tick);
    }
}

function updateCompass() {
    const yawDeg = state.simAngles.yaw * 180 / Math.PI;
    let heading = ((yawDeg % 360) + 360) % 360;
    document.getElementById('hdgValue').textContent = `HDG ${Math.round(heading)}°`;

    const strip = document.getElementById('compassStrip');
    const stripWidth = strip.clientWidth;
    const center = stripWidth / 2;
    const pxPerDeg = stripWidth / 90;

    document.querySelectorAll('.compass-tick').forEach(tick => {
        const deg = parseFloat(tick.dataset.deg);
        let offset = deg - heading;
        if (offset > 180) offset -= 360;
        if (offset < -180) offset += 360;
        if (Math.abs(offset) > 50) {
            tick.style.display = 'none';
        } else {
            tick.style.display = '';
            tick.style.left = (center + offset * pxPerDeg) + 'px';
        }
    });
}

// ============================================================
// === VSI — Dikey Hız Göstergesi ===
// ============================================================
function updateVSI() {
    // Elevator > 1500 = tırmanma (ibreyi yukarı)
    // Elevator < 1500 = alçalma (ibreyi aşağı)
    const norm = (state.channels.elevator - SERVO_CENTER) / (SERVO_MAX - SERVO_MIN);
    // norm: +1 = tırmanma, -1 = alçalma
    // SVG: yukarı = küçük y değeri (18), aşağı = büyük y değeri (102)
    // Saat 12 = yukarı, saat 6 = aşağı
    const angleDeg = norm * 110; // +110° yukarı, -110° aşağı
    const rad = (angleDeg - 90) * Math.PI / 180; // -90° offset: 0° = saat 3, -90° = saat 12
    const needle = document.getElementById('vsiNeedle');
    const len = 38;
    needle.setAttribute('x2', 60 + Math.cos(rad) * len);
    needle.setAttribute('y2', 60 + Math.sin(rad) * len);
}

// ============================================================
// === Input Handling ===
// ============================================================
function initInputHandlers() {
    document.addEventListener('keydown', (e) => {
        if (e.repeat) return;
        state.keysDown.add(e.code);
        handleKeyboardAction(e.code);
    });
    document.addEventListener('keyup', (e) => {
        state.keysDown.delete(e.code);
    });

    document.getElementById('btnConnect').addEventListener('click', () => socket.emit('connect_arduino'));
    document.getElementById('btnDisconnect').addEventListener('click', () => socket.emit('disconnect_arduino'));
    document.getElementById('btnLog').addEventListener('click', () => socket.emit('toggle_log'));

    document.querySelectorAll('.game-btn').forEach(btn => {
        btn.addEventListener('mousedown', () => btn.classList.add('pressed'));
        btn.addEventListener('mouseup', () => btn.classList.remove('pressed'));
        btn.addEventListener('mouseleave', () => btn.classList.remove('pressed'));
    });

    window.addEventListener('gamepadconnected', (e) => console.log(`Gamepad: ${e.gamepad.id}`));
    window.addEventListener('gamepaddisconnected', () => console.log('Gamepad çıkarıldı'));
}

function handleKeyboardAction(code) {
    switch (code) {
        case 'KeyC': socket.emit('connect_arduino'); break;
        case 'KeyD': socket.emit('disconnect_arduino'); break;
        case 'KeyL': socket.emit('toggle_log'); break;
    }
}

function processInput() {
    const step = 25;
    const t = state.targetChannels;

    // === Aileron (← →) ===
    // Sol ok = sol kanat aşağı (roll sol) = aileron azalır
    if (state.keysDown.has('ArrowLeft')) {
        t.aileron = Math.max(SERVO_MIN, t.aileron - step);
    } else if (state.keysDown.has('ArrowRight')) {
        t.aileron = Math.min(SERVO_MAX, t.aileron + step);
    } else {
        // Merkeze dön
        if (t.aileron < SERVO_CENTER) t.aileron = Math.min(SERVO_CENTER, t.aileron + step);
        else if (t.aileron > SERVO_CENTER) t.aileron = Math.max(SERVO_CENTER, t.aileron - step);
    }

    // === Elevator (↑ ↓) ===
    // Yukarı ok = burun yukarı (elevator artar)
    if (state.keysDown.has('ArrowUp')) {
        t.elevator = Math.min(SERVO_MAX, t.elevator + step);
    } else if (state.keysDown.has('ArrowDown')) {
        t.elevator = Math.max(SERVO_MIN, t.elevator - step);
    } else {
        if (t.elevator < SERVO_CENTER) t.elevator = Math.min(SERVO_CENTER, t.elevator + step);
        else if (t.elevator > SERVO_CENTER) t.elevator = Math.max(SERVO_CENTER, t.elevator - step);
    }

    // === Throttle (W/S) ===
    if (state.keysDown.has('KeyW')) {
        t.throttle = Math.min(THROTTLE_MAX, t.throttle + step);
    } else if (state.keysDown.has('KeyS')) {
        t.throttle = Math.max(THROTTLE_MIN, t.throttle - step);
    }

    // === Rudder (Z/X) ===
    // Z = burun sola (rudder azalır)
    if (state.keysDown.has('KeyZ')) {
        t.rudder = Math.max(SERVO_MIN, t.rudder - step);
    } else if (state.keysDown.has('KeyX')) {
        t.rudder = Math.min(SERVO_MAX, t.rudder + step);
    } else {
        if (t.rudder < SERVO_CENTER) t.rudder = Math.min(SERVO_CENTER, t.rudder + step);
        else if (t.rudder > SERVO_CENTER) t.rudder = Math.max(SERVO_CENTER, t.rudder - step);
    }

    // === Gamepad (Steam Deck) ===
    const gamepads = navigator.getGamepads();
    if (gamepads[0]) {
        const gp = gamepads[0];
        const deadzone = 0.12;
        const dz = (v) => Math.abs(v) > deadzone ? v : 0;

        // Sol stick: axis 0 = aileron, axis 1 = elevator
        t.aileron = SERVO_CENTER + dz(gp.axes[0]) * (SERVO_MAX - SERVO_MIN) / 2;
        t.elevator = SERVO_CENTER - dz(gp.axes[1]) * (SERVO_MAX - SERVO_MIN) / 2;
        // Sağ stick: axis 2 = rudder, axis 3 = throttle (veya trigger)
        t.rudder = SERVO_CENTER + dz(gp.axes[2]) * (SERVO_MAX - SERVO_MIN) / 2;
        // Throttle: trigger veya sağ stick Y
        if (gp.axes.length > 4) {
            // Steam Deck: axis 3 = sağ stick Y
            t.throttle = THROTTLE_MIN + ((1 - dz(gp.axes[3])) / 2) * (THROTTLE_MAX - THROTTLE_MIN);
        } else {
            t.throttle = THROTTLE_MIN + ((1 - dz(gp.axes[3])) / 2) * (THROTTLE_MAX - THROTTLE_MIN);
        }

        // Buton görsel feedback
        const btnMap = { 0: 'btnA', 1: 'btnB', 2: 'btnX', 3: 'btnY', 4: 'btnL1', 5: 'btnR1' };
        gp.buttons.forEach((btn, i) => {
            const el = document.getElementById(btnMap[i]);
            if (el) {
                if (btn.pressed) el.classList.add('pressed');
                else el.classList.remove('pressed');
            }
        });
    }
}

function sendControl() {
    socket.emit('control', {
        aileron: Math.round(state.channels.aileron),
        elevator: Math.round(state.channels.elevator),
        rudder: Math.round(state.channels.rudder),
        throttle: Math.round(state.channels.throttle)
    });
}

// === Main Loop ===
let lastSend = 0;

function mainLoop() {
    processInput();
    updateChannelBars();
    updateAircraftFromChannels();
    updateCompass();
    updateVSI();
    updateFlightTimer();

    const now = performance.now();
    if (now - lastSend > 20) {
        lastSend = now;
        sendControl();
    }
    requestAnimationFrame(mainLoop);
}

// === Init ===
document.addEventListener('DOMContentLoaded', () => {
    initThreeJS();
    initCompass();
    initInputHandlers();
    animateThreeJS();
    mainLoop();
    console.log('RC Uçak Yer İstasyonu başlatıldı');
});
