import sys, os
import time, random, math, threading
import numpy as np
import argparse
from pyo import *

# --- Cross-Platform Keyboard Module (from test_speakers.py) ---
try:
    import msvcrt
    WINDOWS = True
except ImportError:
    import select, termios, tty
    WINDOWS = False

try:
    import mido
    HAS_MIDO = True
except ImportError:
    HAS_MIDO = False

try:
    import launchpad_py as launchpad
    HAS_LAUNCHPAD_PY = True
except ImportError:
    HAS_LAUNCHPAD_PY = False

"""
Experiential psychoacoustic tests
============================================================================
This script is a series of psychoacoustic tests that offer the opportunity 
to gain experiential knowledge in the context of quadraphonic setup.
============================================================================
- Top Buttons 0-3: Momentary Channel Solo (Sine Wave, Red)
- Top Button 4: Toggles Auto-Scan (Pink Noise, Green/Red)
- Top Button 5: Toggles Manual Mode (Sine Wave over Grid, Green/Red)
- Top Buttons 6-7: Master Volume

- Side Button 0: Doppler (Cycle: Low -> Mid -> High -> Off)
- Side Button 1: Binaural Beats (Cycle: 36Hz -> 72Hz -> 108Hz -> Off)
- Side Button 2: Toggles Ascending Shepherd (Green)
- Side Button 3: Toggles Descending Shepherd (Green)
- Side Button 4: Toggles Risset Accelerando (Blue)
- Side Button 5: Toggles Risset Decelerando (Blue)
- Side Button 6: EXIT / POWER OFF (Blue/Cyan)

============================================================
- Universal Launchpad Support (Mk1, Mk2, Pro, MK3 Pro)
- Auto detection 2 or 4 channel sounds
- Cross-platform Keyboard Emulation (Windows & macOS)
- 64-Key Full Grid Mapping
- Global ESC key to exit with ANSI-sequence filtering
- Auto Programmer Mode entry for MK3 Pro (via Mido/RtMidi)
"""

# --- CLI Arguments (Extended from test_speakers.py) ---
parser = argparse.ArgumentParser(description="Psychoacoustic Tests - 4-Channel Audio")
parser.add_argument('-e', '--emulate', action='store_true', help='Force Launchpad emulation mode')
parser.add_argument('-c', '--channels', type=int, choices=[2, 4], help='Force number of audio channels (2 or 4)')
parser.add_argument('-d', '--device', type=int, help='Set audio output device ID')
args, _ = parser.parse_known_args()

AUDIO_DEVICE = 10 if sys.platform != 'darwin' else -1
if args.device is not None:
    AUDIO_DEVICE = args.device

AUDIO_HOST = 'coreaudio' if sys.platform == 'darwin' else 'asio'
BUFFER_SIZE = 512

# --- Keyboard Manager (Handles global ESC & Emulation input) ---
class KeyboardManager:
    def __init__(self):
        if not WINDOWS:
            self.fd = sys.stdin.fileno()
            self.old_settings = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)

    def get_key(self):
        if WINDOWS:
            if msvcrt.kbhit():
                char = msvcrt.getch()
                if char in (b'\x00', b'\xe0'):  # Handle special keys
                    msvcrt.getch()
                    return None
                if char == b'\x1b':
                    return '\x1b'
                return char.decode('utf-8', 'ignore')
            return None
        else:
            if select.select([sys.stdin], [], [], 0)[0]:
                char = sys.stdin.read(1)
                if char == '\x1b':
                    # Wait a tiny fraction to see if it's an ANSI sequence (like focus events or arrows)
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        seq = sys.stdin.read(1)
                        # Drain the rest of the sequence so it doesn't trigger random keys
                        while select.select([sys.stdin], [], [], 0.01)[0]:
                            seq += sys.stdin.read(1)
                        return char + seq  # Return the full sequence (won't trigger ESC)
                return char
            return None

    def close(self):
        if not WINDOWS:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.old_settings)

# --- Virtual Launchpad Class (Emulation) ---
class VirtualLaunchpad:
    def __init__(self, emu_mode="Mk1"):
        self.mode = emu_mode
        self.key_states = {}
        print("\n" + "=" * 60)
        print(" EMULATION MODE STARTED (Keyboard Control)")
        print("")
        print(" SOLO CHANNELS (Momentary Hold):")
        print(" [q] - Solo Ch 0              [w] - Solo Ch 1")
        print(" [e] - Solo Ch 2              [r] - Solo Ch 3")
        print("")
        print(" SCAN & MANUAL:")
        print(" [t] - Auto-Scan Toggle       [g] - Manual Mode Toggle")
        print(" [-] - Vol Down               [+] - Vol Up")
        print("")
        print(" PSYCHOACOUSTIC FX (Side Buttons):")
        print(" [a] - Doppler Cycle          [s] - Binaural Cycle")
        print(" [d] - Shepherd Ascending     [f] - Shepherd Descending")
        print(" [v] - Risset Accelerando     [b] - Risset Decelerando")
        print("")
        print(" 64-KEY GRID MAPPING (For Manual Mode):")
        print(" Row 1 (Top)   :  1 2 3 4 5 6 7 8")
        print(" Row 2         :  (q)(w)(e)(r) (t) y u i")
        print(" Row 3         :  (a)(s)(d)(f)(g) h j k")
        print(" Row 4         :  z x c (v)(b) n m ,")
        print(" Row 5 (Shift) :  ! @ # $ % ^ & *")
        print(" Row 6 (Shift) :  Q W E R T Y U I")
        print(" Row 7 (Shift) :  A S D F G H J K")
        print(" Row 8 (Bottom):  Z X C V B N M <")
        print(" (Keys in parentheses are used by controls)")
        print("=" * 60 + "\n")

    def close(self):
        pass  # Handled globally by KeyboardManager

    def set_led(self, bid, color): pass
    def set_led_rgb(self, bid, r, g, b): pass

    def process_key(self, char):
        if not char:
            # Auto-release keys on the next cycle
            for bid in list(self.key_states.keys()):
                if self.key_states[bid]:
                    self.key_states[bid] = False
                    return [(bid, 0)]
            return []

        # Top button controls (Mk1 raw IDs) — checked FIRST, override grid
        ctrl_map = {
            'q': 200, 'w': 201, 'e': 202, 'r': 203,   # Solo Ch 0-3 (SOLO_BTNS)
            't': 204,                                    # Auto-Scan Toggle (SCAN_CTRL_BTNS[0])
            'g': 205,                                    # Manual Mode Toggle (SCAN_CTRL_BTNS[1])
            '-': 206, '+': 207, '=': 207,               # Vol Down / Up (VOL_BTNS)
        }
        # Side button controls (Mk1 raw IDs)
        side_map = {
            'a': 8,     # Doppler Cycle (SIDE_BTNS[0])
            's': 24,    # Binaural Cycle (SIDE_BTNS[1])
            'd': 40,    # Shepherd Ascending (SIDE_BTNS[2])
            'f': 56,    # Shepherd Descending (SIDE_BTNS[3])
            'v': 72,    # Risset Accelerando (SIDE_BTNS[4])
            'b': 88,    # Risset Decelerando (SIDE_BTNS[5])
        }
        # 64-key grid mapping (same as test_speakers.py)
        grid_map = {
            '1': (0, 0), '2': (1, 0), '3': (2, 0), '4': (3, 0), '5': (4, 0), '6': (5, 0), '7': (6, 0), '8': (7, 0),
            'q': (0, 1), 'w': (1, 1), 'e': (2, 1), 'r': (3, 1), 't': (4, 1), 'y': (5, 1), 'u': (6, 1), 'i': (7, 1),
            'a': (0, 2), 's': (1, 2), 'd': (2, 2), 'f': (3, 2), 'g': (4, 2), 'h': (5, 2), 'j': (6, 2), 'k': (7, 2),
            'z': (0, 3), 'x': (1, 3), 'c': (2, 3), 'v': (3, 3), 'b': (4, 3), 'n': (5, 3), 'm': (6, 3), ',': (7, 3),
            '!': (0, 4), '@': (1, 4), '#': (2, 4), '$': (3, 4), '%': (4, 4), '^': (5, 4), '&': (6, 4), '*': (7, 4),
            'Q': (0, 5), 'W': (1, 5), 'E': (2, 5), 'R': (3, 5), 'T': (4, 5), 'Y': (5, 5), 'U': (6, 5), 'I': (7, 5),
            'A': (0, 6), 'S': (1, 6), 'D': (2, 6), 'F': (3, 6), 'G': (4, 6), 'H': (5, 6), 'J': (6, 6), 'K': (7, 6),
            'Z': (0, 7), 'X': (1, 7), 'C': (2, 7), 'V': (3, 7), 'B': (4, 7), 'N': (5, 7), 'M': (6, 7), '<': (7, 7),
        }

        # Controls take priority over grid
        if char in ctrl_map:
            bid = ctrl_map[char]
            self.key_states[bid] = True
            return [(bid, 127)]
        elif char in side_map:
            bid = side_map[char]
            self.key_states[bid] = True
            return [(bid, 127)]
        elif char in grid_map:
            x, y = grid_map[char]
            bid = y * 16 + x  # Using Mk1 layout for internal emulation
            self.key_states[bid] = True
            return [(bid, 127)]

        return []

# --- Real Launchpad Pro MK3 Class (Mido) ---
class LaunchpadMido:
    def __init__(self, in_port_name, out_port_name):
        self.in_port = mido.open_input(in_port_name)
        self.out_port = mido.open_output(out_port_name)
        print(f"--- MIDI IN Connected to: {in_port_name} ---")
        print(f"--- MIDI OUT Connected to: {out_port_name} ---")

        print("-> Entering Programmer Mode...")
        self.out_port.send(mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x0E, 0x01]))
        time.sleep(1.0)

        print("-> Clearing Grid...")
        self.out_port.send(mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x03, 0x00, 0x00]))
        time.sleep(0.1)

        for i in range(128):
            self.out_port.send(mido.Message('note_off', note=i, velocity=0))
            self.out_port.send(mido.Message('control_change', control=i, value=0))
        time.sleep(0.1)

    def set_led(self, bid, color_index):
        self.out_port.send(mido.Message('note_on', channel=0, note=bid, velocity=color_index))

    def set_led_rgb(self, bid, r, g, b):
        # Scale from Mk1-style (0-3) to SysEx range (0-127): 0->0, 1->42, 2->84, 3->126
        r_val, g_val, b_val = min(127, int(r * 42)), min(127, int(g * 42)), min(127, int(b * 42))
        self.out_port.send(mido.Message('sysex',
            data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x03, 0x03, bid, r_val, g_val, b_val]))

    def get_events(self):
        events = []
        for msg in self.in_port.iter_pending():
            if msg.type in ['note_on', 'note_off']:
                state = msg.velocity if msg.type == 'note_on' else 0
                events.append((msg.note, state))
            elif msg.type == 'control_change':
                events.append((msg.control, msg.value))
        return events

    def close(self):
        print("-> Exiting Programmer Mode...")
        self.out_port.send(mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x0E, 0x00]))
        self.in_port.close()
        self.out_port.close()

# --- Legacy Launchpad Wrapper (launchpad_py) ---
class LaunchpadPyWrapper:
    def __init__(self, lp_instance, lp_mode):
        self.lp = lp_instance
        self.mode = lp_mode

    def set_led(self, bid, color_index):
        if self.mode == "Mk1":
            r, g = 0, 0
            if color_index in [5, 72]: r = 3       # Red
            elif color_index in [21, 87]: g = 3     # Green
            elif color_index in [13, 62]: r, g = 3, 3  # Yellow
            self.lp.LedCtrlRaw(bid, r, g)
        else:
            try: self.lp.LedCtrlRawByCode(bid, color_index)
            except: pass

    def set_led_rgb(self, bid, r, g, b):
        if self.mode == "Mk1":
            color = 0
            if r > 0 and g == 0: color = 5
            elif r == 0 and g > 0: color = 21
            elif r > 0 and g > 0: color = 13
            self.set_led(bid, color)
        else:
            try: self.lp.LedCtrlRaw(bid, min(127, int(r * 42)), min(127, int(g * 42)), min(127, int(b * 42)))
            except: pass

    def get_events(self):
        ev = self.lp.ButtonStateRaw()
        if ev: return [(ev[0], ev[1])]
        return []

    def close(self):
        self.lp.Reset()
        self.lp.Close()

print("\n" + "=" * 50)
print(" Psychoacoustic Tests - Multi-Channel Audio")
print("============================================================================")
print("This script is a series of psychoacoustic tests that offer the opportunity ")
print("to gain experiential knowledge in the context of quadraphonic setup.")
print("============================================================================")
print("- Top Buttons 0-3: Momentary Channel Solo (Sine Wave, Red)")
print("- Top Button 4: Toggles Auto-Scan (Pink Noise, Green/Red)")
print("- Top Button 5: Toggles Manual Mode (Sine Wave over Grid, Green/Red)")
print("- Top Buttons 6-7: Master Volume")
print("- Side Button 0: Doppler (Cycle: Low -> Mid -> High -> Off)")
print("- Side Button 1: Binaural Beats (Cycle: 36Hz -> 72Hz -> 108Hz -> Off)")
print("- Side Button 2: Toggles Ascending Shepherd (Green)")
print("- Side Button 3: Toggles Descending Shepherd (Green)")
print("- Side Button 4: Toggles Risset Accelerando (Blue)")
print("- Side Button 5: Toggles Risset Decelerando (Blue)")
print("- Side Button 6: EXIT / POWER OFF (Blue/Cyan)")

print("\n" + "=" * 50)
print(" COMMAND LINE ARGUMENTS:")
print(" '-e', '--emulate', Force Launchpad emulation mode ")
print(" '-c <2 or 4>', '--channels <2 or 4>', Force number of audio channels (2 or 4) ")
print(" '-d <id>', '--device <id>', Set audio output device ID ")

# --- Print Audio Devices Debug ---
print("\n" + "=" * 50)
print(" AVAILABLE AUDIO DEVICES:")

# Capture pa_list_devices() text output for parsing
import io as _io
_capture = _io.StringIO()
_old_stdout = sys.stdout
sys.stdout = _capture
pa_list_devices()
sys.stdout = _old_stdout
_dev_text = _capture.getvalue()
print(_dev_text, end='')  # Print it for the user to see
print("=" * 50 + "\n")

# --- Audio Device & Channel Auto-Detection ---
# Parse pa_list_devices() output to find multi-channel OUT devices
# (pa_get_output_max_channels() returns 0 before server boot on macOS CoreAudio)
import re as _re
_out_devices = []  # [(dev_id, name, guessed_channels), ...]
for _line in _dev_text.splitlines():
    _m = _re.match(r'^\s*(\d+):\s*OUT,\s*name:\s*(.+?),\s*host', _line)
    if _m:
        _dev_id = int(_m.group(1))
        _dev_name = _m.group(2).strip()
        # Try to extract channel count from name (e.g. "BlackHole 16ch", "BlackHole 2ch")
        _ch_match = _re.search(r'(\d+)\s*ch', _dev_name, _re.IGNORECASE)
        _guessed_ch = int(_ch_match.group(1)) if _ch_match else 2
        _out_devices.append((_dev_id, _dev_name, _guessed_ch))
        print(f"   OUT Device {_dev_id}: \"{_dev_name}\" (~{_guessed_ch}ch)")

if args.device is not None:
    actual_dev_id = args.device
    max_chans = next((ch for did, _, ch in _out_devices if did == actual_dev_id), 2)
    print(f"   DEVICE: Manually set to ID {actual_dev_id}")
else:
    # Pick first output device with 4+ channels
    _quad = [(d, n, ch) for d, n, ch in _out_devices if ch >= 4]
    if _quad:
        actual_dev_id = _quad[0][0]
        max_chans = _quad[0][2]
        print(f"   >>> AUTO-SELECTED: Device {actual_dev_id} \"{_quad[0][1]}\" ({max_chans}ch)")
    elif _out_devices:
        actual_dev_id = _out_devices[0][0]
        max_chans = _out_devices[0][2]
        print(f"   No 4+ channel device found, using first output: ID {actual_dev_id}")
    else:
        try:
            actual_dev_id = pa_get_default_output()
        except:
            actual_dev_id = 0
        max_chans = 2
        print(f"   No output devices parsed, using system default: ID {actual_dev_id}")

AUDIO_DEVICE = actual_dev_id

if args.channels:
    num_channels = args.channels
else:
    num_channels = min(4, max_chans)
    if num_channels < 4:
        print(f"   NOTE: Selected device supports {max_chans}ch, using {num_channels} channels")

print(f"\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
print(f" AUDIO DEVICE: ID {actual_dev_id}")
print(f" TOTAL CHANNELS: {num_channels}")
print(f"<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<\n")

# --- 1. Find Launchpad Ports & Assign Mode ---
lp = None
mode = None
EMULATE_MODE = args.emulate

# 1. Try Mido for MK3 Pro First (from test_speakers.py)
if not EMULATE_MODE and HAS_MIDO:
    try:
        in_names = mido.get_input_names()
        out_names = mido.get_output_names()
        lp_in = next((n for n in in_names if ("LPProMK3" in n or "Pro MK3" in n) and "DAW" not in n and "DIN" not in n), None)
        lp_out = next((n for n in out_names if ("LPProMK3" in n or "Pro MK3" in n) and "DAW" not in n and "DIN" not in n), None)

        if lp_in and lp_out:
            lp = LaunchpadMido(lp_in, lp_out)
            mode = "ProMk3"
            print("--- System: Launchpad Pro MK3 detected via Mido ---")
    except Exception as e:
        print(f"--- Mido Error: {e} ---")

# 2. Try launchpad_py for Older Models (Mini, Mk2, Pro)
if not EMULATE_MODE and lp is None and HAS_LAUNCHPAD_PY:
    try:
        lp_check = launchpad.Launchpad()
        if lp_check.Check(0, "Mini"):
            lp_check.Open()
            lp = LaunchpadPyWrapper(lp_check, "Mk1")
            mode = "Mk1"
            print("--- System: Launchpad Mk1/S/Mini detected ---")
        elif lp_check.Check(0, "Mk2"):
            lp_check = launchpad.LaunchpadMk2()
            lp_check.Open()
            lp = LaunchpadPyWrapper(lp_check, "Mk2")
            mode = "Mk2"
            print("--- System: Launchpad Mk2 detected ---")
        elif lp_check.Check(0, "pro"):
            lp_check = launchpad.LaunchpadPro()
            lp_check.Open(0, "pro")
            lp = LaunchpadPyWrapper(lp_check, "Pro")
            mode = "Pro"
            print("--- System: Launchpad Pro detected ---")
    except Exception as e:
        print(f"--- launchpad_py Error: {e} ---")

# 3. Fallback to Emulation
if lp is None:
    print("--- No hardware Launchpad found. Falling back to Emulation. ---")
    EMULATE_MODE = True
    mode = "Mk1"
    lp = VirtualLaunchpad(mode)

# --- Hardware Constants Layout Mapping ---
if mode == "Mk1":
    SOLO_BTNS = [200, 201, 202, 203]
    SCAN_CTRL_BTNS = [204, 205]  # Top row 4-5
    VOL_BTNS = [206, 207]
    SIDE_BTNS = [8, 24, 40, 56, 72, 88, 104, 120]
elif mode == "Mk2":
    SOLO_BTNS = [104, 105, 106, 107]
    SCAN_CTRL_BTNS = [108, 109]  # Top row 4-5
    VOL_BTNS = [110, 111]
    SIDE_BTNS = [89, 79, 69, 59, 49, 39, 29, 19]
elif mode in ["Pro", "ProMk3"]:
    SOLO_BTNS = [91, 92, 93, 94]
    SCAN_CTRL_BTNS = [95, 96]    # Top row 4-5
    VOL_BTNS = [97, 98]
    SIDE_BTNS = [89, 79, 69, 59, 49, 39, 29, 19]

EXIT_PWR_BTN = SIDE_BTNS[6]

# --- 2. Audio Server ---
s = Server(sr=48000, nchnls=num_channels, duplex=0, buffersize=BUFFER_SIZE, winhost=AUDIO_HOST)
if AUDIO_DEVICE != -1:
    s.setOutputDevice(AUDIO_DEVICE)
s.deactivateMidi()
s.boot().start()

# Ensure the server is booted before creating any audio objects
time.sleep(0.1)
if not s.getIsBooted():
    print("\n[ERROR] Pyo Server failed to boot. This usually happens if the selected")
    print(f"        audio device (ID {actual_dev_id}) doesn't support {num_channels} output channels.")
    print("        Try running with -c 2 or selecting a different device with -d <id>.\n")
    if lp:
        if isinstance(lp, LaunchpadMido): lp.close()
        elif not EMULATE_MODE: lp.Reset(); lp.Close()
    if 'kb_mgr' in locals(): kb_mgr.close()
    sys.exit(1)

# --- Phase 2: Post-Boot Channel Verification ---
# Now that the server is booted, pa_get_output_max_channels() returns accurate values.
# Verify the selected device actually supports the requested channel count.
_verified_chans = 0
try:
    _verified_chans = pa_get_output_max_channels(actual_dev_id)
except:
    pass

if _verified_chans > 0:
    print(f"   VERIFIED: Device {actual_dev_id} supports {_verified_chans} output channels")
    if not args.channels and _verified_chans != max_chans:
        # Our Phase 1 guess was wrong — re-check all devices with accurate data
        print(f"   Phase 1 guessed {max_chans}ch, actual is {_verified_chans}ch")
        if _verified_chans < 4 and not args.device:
            # Scan all devices post-boot for a better candidate
            _best_dev, _best_ch = actual_dev_id, _verified_chans
            try:
                for _di in range(pa_count_devices()):
                    try:
                        _dch = pa_get_output_max_channels(_di)
                        if _dch >= 4 and _dch > _best_ch:
                            _best_dev, _best_ch = _di, _dch
                    except:
                        pass
            except:
                pass
            if _best_ch >= 4 and _best_dev != actual_dev_id:
                print(f"   RESELECTING: Device {_best_dev} has {_best_ch} verified channels")
                actual_dev_id = _best_dev
                AUDIO_DEVICE = actual_dev_id
                num_channels = min(4, _best_ch) if not args.channels else num_channels
                # Restart server with correct device
                s.stop()
                time.sleep(0.2)
                s = Server(sr=48000, nchnls=num_channels, duplex=0, buffersize=BUFFER_SIZE, winhost=AUDIO_HOST)
                s.setOutputDevice(AUDIO_DEVICE)
                s.deactivateMidi()
                s.boot().start()
                time.sleep(0.1)
                print(f"   SERVER RESTARTED: Device {actual_dev_id}, {num_channels} channels")
            else:
                num_channels = min(4, _verified_chans) if not args.channels else num_channels
        else:
            max_chans = _verified_chans
            if not args.channels:
                num_channels = min(4, _verified_chans)
    print(f"   FINAL CONFIG: Device {actual_dev_id}, {num_channels} channels")

# --- 3. Audio Engine ---
noise = PinkNoise(mul=0.2)
sine = Sine(freq=440, mul=0.2)

# --- Shepherd Engine ---
shep_gate = Sig(0)
shep_phasor = Phasor(freq=0.05, mul=1)
shep_pos = shep_phasor * shep_gate
shep_oscillators = []
for i in range(12):
    raw_pos = (shep_pos + (i / 12.0)) % 1.0
    freq_sig = Sig(110) * Pow(2, raw_pos * 10)
    amp_mask = Cos(raw_pos * math.pi * 2 - math.pi, mul=0.5, add=0.5)
    shep_oscillators.append(Sine(freq=freq_sig, mul=amp_mask * 0.15))
shep_sum = sum(shep_oscillators)

# --- Risset Engine ---
risset_gate = Sig(0)
risset_phasor = Phasor(freq=0.04, mul=1)
risset_pos = risset_phasor * risset_gate
env_table = CosTable([(0, 0), (1000, 1), (4000, .5), (8192, 0)])
risset_pulses = []
for i in range(12):
    r_pos = (risset_pos + (i / 12.0)) % 1.0
    pulse_freq = Sig(0.5) * Pow(2, r_pos * 4)
    r_amp = Cos(r_pos * math.pi * 2 - math.pi, mul=0.5, add=0.5)
    click = Metro(time=1.0 / pulse_freq).play()
    strike = TrigEnv(click, table=env_table, dur=0.15, mul=r_amp)
    filt_noise = Reson(PinkNoise(mul=strike), freq=600, q=2)
    risset_pulses.append(filt_noise)
risset_sum = sum(risset_pulses) * 0.6

# --- Doppler Engine (Cycling Frequencies) ---
dopp_gate = Sig(0)
dopp_depth = Sig(0)
dopp_freq_mod = Sine(freq=0.5, mul=dopp_depth, add=440)
doppler_sine = Sine(freq=dopp_freq_mod, mul=dopp_gate * 0.3)

# --- Binaural Engine ---
bin_gate = Sig(0)
bin_carrier = Sig(220)
bin_beat = 4
bin_oscs = [
    Sine(freq=bin_carrier, mul=bin_gate * 0.1),
    Sine(freq=bin_carrier + bin_beat, mul=bin_gate * 0.1),
    Sine(freq=bin_carrier, mul=bin_gate * 0.1),
    Sine(freq=bin_carrier + bin_beat, mul=bin_gate * 0.1)
]

# Control signals
noise_gains = [Sig(0) for _ in range(4)]
noise_ports = [Port(sig, 0.05, 0.05) for sig in noise_gains]
sine_gains = [Sig(0) for _ in range(4)]
sine_ports = [Port(sig, 0.05, 0.05) for sig in sine_gains]
shep_scan_gains = [Sig(0) for _ in range(4)]
shep_scan_ports = [Port(sig, 0.05, 0.05) for sig in shep_scan_gains]
risset_gains = [Sig(0) for _ in range(4)]
risset_ports = [Port(sig, 0.05, 0.05) for sig in risset_gains]
dopp_scan_gains = [Sig(0) for _ in range(4)]
dopp_scan_ports = [Port(sig, 0.05, 0.05) for sig in dopp_scan_gains]

master_vol = Sig(0.6)
master_vol_port = Port(master_vol, 0.1, 0.1)

for i in range(4):
    # Noise driven by Auto-Scan, Sine driven by Manual Grid + Top Buttons
    out = ((noise * noise_ports[i]) + (sine * sine_ports[i]) + \
           (shep_sum * shep_scan_ports[i]) + (risset_sum * risset_ports[i]) + \
           (doppler_sine * dopp_scan_ports[i]) + bin_oscs[i]) * master_vol_port
    # Channel assignment: auto-fold to 2 channels when num_channels == 2
    out.out(i % num_channels)

print("--- Audio Engine Started ---")
print("\n***************************************************")
print("    >>> PRESS [ESC] AT ANY TIME TO EXIT <<<")
print("***************************************************\n")

# --- Initialize Global Keyboard Manager SAFELY ---
# (Done AFTER audio boots to prevent termios from crashing CoreAudio)
kb_mgr = KeyboardManager()

# --- 4. Helper Functions ---
def get_quad_gains(x, y):
    nx, ny = x / 7.0, (y - 1) / 7.0
    return [(1.-nx)*(1.-ny), nx*(1.-ny), (1.-nx)*ny, nx*ny]

def lp_led_raw(bid, r, g, b=0):
    """Unified LED control: maps Mk1-style (r,g 0-3) color tuples to the unified API."""
    if EMULATE_MODE: return
    if r > 0 and g == 0 and b == 0: lp.set_led(bid, 5)       # Red
    elif r == 0 and g > 0 and b == 0: lp.set_led(bid, 21)    # Green
    elif r > 0 and g > 0 and b == 0: lp.set_led(bid, 13)     # Yellow
    elif b > 0 and r == 0 and g == 0: lp.set_led(bid, 45)    # Blue
    elif r == 0 and g == 0 and b == 0: lp.set_led(bid, 0)    # Off
    else: lp.set_led_rgb(bid, r, g, b)                        # Custom RGB

def lp_led_grid(x, y, r, g, b=0):
    if mode == "Mk1":
        bid = y * 16 + x
    else:
        bid = (8 - y) * 10 + x + 1
    lp_led_raw(bid, r, g, b)

def get_xy_from_raw(bid):
    if mode == "Mk1":
        x, y = bid % 16, bid // 16
        if x < 8 and y < 8: return x, y
    else:
        r, c = bid // 10, bid % 10
        if 1 <= r <= 8 and 1 <= c <= 8: return c - 1, 8 - r
    return None

def update_vol_leds():
    vol = master_vol.value
    if not EMULATE_MODE: print(f"--- Volume: {vol:.2f} ---")
    v_col = (0, 3) if vol < 0.4 else (3, 3) if vol < 0.7 else (2, 0) if vol < 0.9 else (3, 0)
    for btn in VOL_BTNS: lp_led_raw(btn, *v_col)

# --- 5. State Management ---
scan_active = manual_active = shep_asc_active = shep_des_active = r_acc_active = r_dec_active = False
dopp_mode = 0
bin_mode = 0
pressed_top_btns = set()
pressed_grid_cells = set()

for btn in SOLO_BTNS: lp_led_raw(btn, 0, 3)
for btn in SCAN_CTRL_BTNS: lp_led_raw(btn, 0, 3)
update_vol_leds()

# Initial Side Button Setup
for i, b in enumerate(SIDE_BTNS):
    if i == 0: lp_led_raw(b, 1, 0, 0)
    elif i == 1: lp_led_raw(b, 1, 0, 1)
    elif i < 4: lp_led_raw(b, 0, 3)
    elif i < 6: lp_led_raw(b, 0, 0, 1)
    elif i == 6: lp_led_raw(b, 0, 0, 1)  # Cyan Power button
    elif i == 7: lp_led_raw(b, 0, 0)

# --- 6. Main Loop ---
try:
    print("--- Starting V2 Loop ---")
    shep_step_interval = 4.0 / 64.0  # Faster scan speed from reference
    last_step_time = time.time()
    grid_idx = -1
    scan_gains = manual_scan_gains = shep_gains = r_gains = dopp_gains = [0.0] * 4
    last_side_states = {btn: 0 for btn in SIDE_BTNS}
    last_top_states = {btn: 0 for btn in SCAN_CTRL_BTNS}

    while True:
        current_time = time.time()

        # Cross-platform ESC exit check
        key = kb_mgr.get_key()
        if key == '\x1b':  # ESC key (Clean standalone press)
            print("\n--- System: ESC Pressed. Exiting... ---")
            break

        # Unified event handling: keyboard emulation or hardware Launchpad
        if EMULATE_MODE:
            events = lp.process_key(key)
        else:
            events = lp.get_events()

        for bid, state in events:
            if bid == EXIT_PWR_BTN and state > 0:
                print("\n--- System: Exit Triggered from Hardware ---")
                raise KeyboardInterrupt

            if bid in SCAN_CTRL_BTNS:
                idx = SCAN_CTRL_BTNS.index(bid)
                if state > 0 and last_top_states[bid] == 0:
                    if idx == 0:  # Top 4: Auto-Scan Toggle (Pink Noise)
                        scan_active = not scan_active
                        print(f"--- Auto-Scan: {scan_active} ---")
                    elif idx == 1:  # Top 5: Manual Mode Toggle (Sine Wave)
                        manual_active = not manual_active
                        print(f"--- Manual Mode: {manual_active} ---")
                        if not manual_active:
                            for (gx, gy) in pressed_grid_cells: lp_led_grid(gx, gy, 0, 0)
                            pressed_grid_cells.clear()

                    for i, b in enumerate(SCAN_CTRL_BTNS):
                        act = scan_active if i == 0 else manual_active
                        lp_led_raw(b, *((3, 0) if act else (0, 3)))
                last_top_states[bid] = state

            elif bid in SIDE_BTNS:
                idx = SIDE_BTNS.index(bid)
                if state > 0 and last_side_states[bid] == 0:
                    if idx == 2:
                        shep_asc_active, shep_des_active = not shep_asc_active, False; shep_phasor.freq = 0.05
                    elif idx == 3:
                        shep_des_active, shep_asc_active = not shep_des_active, False; shep_phasor.freq = -0.05
                    elif idx == 4:
                        r_acc_active, r_dec_active = not r_acc_active, False; risset_phasor.freq = 0.04
                    elif idx == 5:
                        r_dec_active, r_acc_active = not r_dec_active, False; risset_phasor.freq = -0.04
                    elif idx == 0:
                        dopp_mode = (dopp_mode + 1) % 4
                        dopp_depth.value = [0, 20, 60, 120][dopp_mode]
                    elif idx == 1:
                        bin_mode = (bin_mode + 1) % 4
                        bin_carrier.value = [0, 36, 72, 108][bin_mode]

                    shep_gate.value = 1 if (shep_asc_active or shep_des_active) else 0
                    risset_gate.value = 1 if (r_acc_active or r_dec_active) else 0
                    dopp_gate.value = 1 if dopp_mode > 0 else 0
                    bin_gate.value = 1 if bin_mode > 0 else 0

                    for i, b in enumerate(SIDE_BTNS):
                        if i == 6: continue
                        act_list = [(dopp_mode > 0), (bin_mode > 0), shep_asc_active, shep_des_active, r_acc_active, r_dec_active]
                        act = act_list[i] if i < len(act_list) else False
                        if i == 0: lp_led_raw(b, 3 if act else 1, 0, 0)
                        elif i == 1: lp_led_raw(b, 3 if act else 1, 0, 3 if act else 1)
                        elif i < 4: lp_led_raw(b, (3 if act else 0), (0 if act else 3))
                        elif i < 6: lp_led_raw(b, 0, 0, (3 if act else 1))
                last_side_states[bid] = state

            elif bid in SOLO_BTNS:
                if state > 0: pressed_top_btns.add(bid); lp_led_raw(bid, 3, 0)
                else:
                    if bid in pressed_top_btns: pressed_top_btns.remove(bid)
                    lp_led_raw(bid, 0, 3)

            elif bid in VOL_BTNS:
                if state > 0:
                    idx = VOL_BTNS.index(bid)
                    master_vol.value = max(0.0, min(1.0, master_vol.value + (-0.05 if idx == 0 else 0.05)))
                    update_vol_leds()
                    if EMULATE_MODE: print(f"--- Volume: {master_vol.value:.2f} ---")

            else:
                coords = get_xy_from_raw(bid)
                if coords and manual_active:
                    gx, gy = coords
                    if state > 0:
                        pressed_grid_cells.add((gx, gy))
                        lp_led_grid(gx, gy, 0, 3)  # Green for manual sine
                    else:
                        if (gx, gy) in pressed_grid_cells:
                            pressed_grid_cells.remove((gx, gy))
                            lp_led_grid(gx, gy, 0, 0)

        # Logic for Scan, Shepherd, Risset, and Doppler
        if (scan_active or shep_asc_active or shep_des_active or r_acc_active or r_dec_active or dopp_mode > 0):
            if current_time - last_step_time >= shep_step_interval:
                if grid_idx >= 0:
                    px, py = grid_idx % 8, grid_idx // 8
                    if (px, py) not in pressed_grid_cells: lp_led_grid(px, py, 0, 0)

                is_rev = shep_asc_active or r_acc_active
                grid_idx = (grid_idx - 1) % 64 if is_rev else (grid_idx + 1) % 64
                sx, sy = grid_idx % 8, grid_idx // 8

                current_quad = get_quad_gains(sx, sy + 1)
                if scan_active: scan_gains = current_quad
                if shep_asc_active or shep_des_active: shep_gains = current_quad
                if r_acc_active or r_dec_active: r_gains = current_quad
                if dopp_mode > 0: dopp_gains = current_quad

                lp_led_grid(sx, sy,
                    (3 if shep_asc_active or shep_des_active or dopp_mode > 0 else 0),
                    (3 if scan_active else 0),
                    (3 if r_acc_active or r_dec_active else 0))
                last_step_time = current_time

        # Manual Mode Logic
        manual_gains_res = [0.0] * 4
        if manual_active and pressed_grid_cells:
            for (mx, my) in pressed_grid_cells:
                gains = get_quad_gains(mx, my + 1)
                for i in range(4): manual_gains_res[i] = max(manual_gains_res[i], gains[i])

        for i in range(4):
            noise_gains[i].value = scan_gains[i] if scan_active else 0

            target_sine = manual_gains_res[i] if manual_active else 0
            if (len(SOLO_BTNS) > i and SOLO_BTNS[i] in pressed_top_btns): target_sine = 1.0
            sine_gains[i].value = target_sine

            shep_scan_gains[i].value = (shep_gains[i] if shep_asc_active or shep_des_active else 0)
            risset_gains[i].value = (r_gains[i] if r_acc_active or r_dec_active else 0)
            dopp_scan_gains[i].value = (dopp_gains[i] if dopp_mode > 0 else 0)

        time.sleep(0.005)

except KeyboardInterrupt: pass
finally:
    s.stop(); s.shutdown()
    if lp:
        if isinstance(lp, (LaunchpadMido, LaunchpadPyWrapper)):
            lp.close()
        elif not EMULATE_MODE:
            lp.close()
    if 'kb_mgr' in locals():
        kb_mgr.close()
    print("--- Goodbye ---")
    os._exit(0)