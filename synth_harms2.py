import sys, os
import time
import random
import threading
import queue
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
Quadraphonic Harmonic Synth
=============================================================================================
This script features a musical instrument that allows you to explore melodic lines, 
to acquire a sensitivity to harmony, to create hybrid textures between harmonics and rhythm. 
It is selectable by its starting note (root) and scale. There are many interesting scales, 
including tonal, non-tonal and microtonal, one of which is randomly generated upon startup. 
=============================================================================================

- Top Button 0: Key Up (Increments root note)
- Top Button 1: Key Down (Decrements root note)
- Top Button 2: Scale Up (Cycles through 20+ musical scales)
- Top Button 3: Scale Down (Cycles through 20+ musical scales)
- Top Button 4: Harmonics Up (Momentary increase for Blit oscillator)
- Top Button 5: Harmonics Down (Momentary decrease for Blit oscillator)
- Top Button 6: Main Volume Down (Decrements master gain)
- Top Button 7: Main Volume Up (Increments master gain)

- Side Button 0: Reverb Cycle (OFF -> LOW -> MED -> HIGH)
- Side Button 1: Delay Cycle (OFF -> LOW -> MED -> HIGH)
- Side Button 2: Arpeggiator (ON/OFF)
- Side Button 3: Drum Machine (OFF -> GREEN: Even -> AMBER: Odd -> RED: Silenced)
- Side Button 4: Octave Up (Shifts grid pitch +3 octaves)
- Side Button 5: Octave Down (Shifts grid pitch -3 octaves)
- Side Button 6: Exit (Stops server and shuts down)

- 8x8 Grid: Note trigger with Quad Panning (X/Y position determines output channel gain)
=============================================================================================
The grid adopts isomorphic not layout, scales start at (0,0) as the root note, 
    therefore changing scale draws a different chromatic organizazion, 
    opens with C Major scale. Same note show as white color, 
    so playing F on row (0) will light up also on row (1); 
    the notes on the 8x8 grid are laid out in fourths vertically. 

0      1      2      3      4      5      6      7    (X)
    +------+------+------+------+------+------+------+------+
 7  |  C   |  ··  |  D   |  ··  |  E   |  F   |  ··  |  G   |
    +------+------+------+------+------+------+------+------+
 6  |  G   |  ··  |  A   |  ··  |  B   |  C   |  ··  |  D   |
    +------+------+------+------+------+------+------+------+
 5  |  D   |  ··  |  E   |  F   |  ··  |  G   |  ··  |  A   |
    +------+------+------+------+------+------+------+------+
 4  |  A   |  ··  |  B   |  C   |  ··  |  D   |  ··  |  E   |
    +------+------+------+------+------+------+------+------+
 3  |  E   |  F   |  ··  |  G   |  ··  |  A   |  ··  |  B   |
    +------+------+------+------+------+------+------+------+
 2  |  B   |  C   |  ··  |  D   |  ··  |  E   |  F   |  ··  |
    +------+------+------+------+------+------+------+------+
 1  |  F   |  ··  |  G   |  ··  |  A   |  ··  |  B   |  C   |
    +------+------+------+------+------+------+------+------+
 0  |  C   |  ··  |  D   |  ··  |  E   |  F   |  ··  |  G   |
    +------+------+------+------+------+------+------+------+
(Y)    0      1      2      3      4      5      6      7

============================================================
- Universal Launchpad Support (Mk1, Mk2, Pro, MK3 Pro)
- Auto detection 2 or 4 channel sounds
- Cross-platform Keyboard Emulation (Windows & macOS)
- 64-Key Full Grid Mapping
- Global ESC key to exit with ANSI-sequence filtering
- Auto Programmer Mode entry for MK3 Pro (via Mido/RtMidi)
"""

# --- CLI Arguments ---
parser = argparse.ArgumentParser(description="Quadraphonic Harmonic Synth")
parser.add_argument('-e', '--emulate', action='store_true', help='Force Launchpad emulation mode')
parser.add_argument('-c', '--channels', type=int, choices=[2, 4], help='Force number of audio channels (2 or 4)')
parser.add_argument('-d', '--device', type=int, help='Set audio output device ID')
args, _ = parser.parse_known_args()

AUDIO_DEVICE = 10 if sys.platform != 'darwin' else -1
if args.device is not None:
    AUDIO_DEVICE = args.device

AUDIO_HOST = 'coreaudio' if sys.platform == 'darwin' else 'asio'
BUFFER_SIZE = 512

# --- Keyboard Manager ---
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
                if char in (b'\x00', b'\xe0'): msvcrt.getch(); return None
                if char == b'\x1b': return '\x1b'
                return char.decode('utf-8', 'ignore')
            return None
        else:
            if select.select([sys.stdin], [], [], 0)[0]:
                char = sys.stdin.read(1)
                if char == '\x1b':
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        seq = sys.stdin.read(1)
                        while select.select([sys.stdin], [], [], 0.01)[0]: seq += sys.stdin.read(1)
                        return char + seq
                return char
            return None
    def close(self):
        if not WINDOWS: termios.tcsetattr(self.fd, termios.TCSANOW, self.old_settings)

# --- Virtual Launchpad Class (Emulation) ---
class VirtualLaunchpad:
    def __init__(self, emu_mode="Mk1"):
        self.mode = emu_mode
        self.key_states = {}
        print("\n" + "=" * 60)
        print(" EMULATION MODE STARTED (Keyboard Control)")
        print("")
        print(" TOP CONTROLS:")
        print(" [9] - Key Up                 [0] - Key Down")
        print(" [o] - Scale Up               [p] - Scale Down")
        print(" [l] - Harmonics Up (hold)    [;] - Harmonics Down (hold)")
        print(" [-] - Vol Down               [+] - Vol Up")
        print("")
        print(" SIDE CONTROLS:")
        print(" [.] - Reverb Cycle           [/] - Delay Cycle")
        print(" ['] - Arpeggiator Toggle     [\\] - Drum Machine Cycle")
        print(" [`] - Octave Up              [Enter] - Octave Down")
        print("")
        print(" 64-KEY GRID (Note Trigger):")
        print(" Row 1 (Top)   :  1 2 3 4 5 6 7 8")
        print(" Row 2         :  q w e r t y u i")
        print(" Row 3         :  a s d f g h j k")
        print(" Row 4         :  z x c v b n m ,")
        print(" Row 5 (Shift) :  ! @ # $ % ^ & *")
        print(" Row 6 (Shift) :  Q W E R T Y U I")
        print(" Row 7 (Shift) :  A S D F G H J K")
        print(" Row 8 (Bottom):  Z X C V B N M <")
        print("=" * 60 + "\n")

    def close(self): pass
    def ButtonFlush(self): pass

    def LedCtrlRaw(self, bid, *args): pass

    def process_key(self, char):
        if not char:
            for bid in list(self.key_states.keys()):
                if self.key_states[bid]:
                    self.key_states[bid] = False
                    return [(bid, 0)]
            return []

        # Top button controls (Mk1 raw IDs)
        ctrl_map = {
            '9': 200, '0': 201,       # Key Up / Down (TOP 0,1)
            'o': 202, 'p': 203,       # Scale Up / Down (TOP 2,3)
            'l': 204, ';': 205,       # Harmonics Up / Down (TOP 4,5)
            '-': 206, '+': 207, '=': 207,  # Vol Down / Up (TOP 6,7)
        }
        # Side button controls (Mk1 raw IDs)
        side_map = {
            '.': 8,     # Reverb Cycle (SIDE 0)
            '/': 24,    # Delay Cycle (SIDE 1)
            "'": 40,    # Arpeggiator Toggle (SIDE 2)
            '\\': 56,   # Drum Machine Cycle (SIDE 3)
            '`': 72,    # Octave Up (SIDE 4)
            '\n': 88,   # Octave Down (SIDE 5)
            '\r': 88,   # Octave Down (Windows Enter)
        }
        # 64-key grid mapping
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

        if char in ctrl_map:
            bid = ctrl_map[char]; self.key_states[bid] = True; return [(bid, 127)]
        elif char in side_map:
            bid = side_map[char]; self.key_states[bid] = True; return [(bid, 127)]
        elif char in grid_map:
            x, y = grid_map[char]; bid = y * 16 + x
            self.key_states[bid] = True; return [(bid, 127)]
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

    def ButtonFlush(self): pass

    def LedCtrlRaw(self, bid, r, g, b=0):
        r_v, g_v, b_v = min(127, int(r * 2)), min(127, int(g * 2)), min(127, int(b * 2))
        self.out_port.send(mido.Message('sysex',
            data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x03, 0x03, bid, r_v, g_v, b_v]))

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
        self.in_port.close(); self.out_port.close()

# --- Legacy Launchpad Wrapper (launchpad_py) ---
class LaunchpadPyWrapper:
    def __init__(self, lp_instance, lp_mode):
        self.lp = lp_instance; self.mode = lp_mode

    def ButtonFlush(self):
        try: self.lp.ButtonFlush()
        except: pass

    def LedCtrlRaw(self, bid, *args):
        """Pass through to native LedCtrlRaw with mode-appropriate args."""
        try:
            if self.mode == "Mk1":
                r = args[0] if len(args) > 0 else 0
                g = args[1] if len(args) > 1 else 0
                self.lp.LedCtrlRaw(bid, r, g)
            else:
                r = args[0] if len(args) > 0 else 0
                g = args[1] if len(args) > 1 else 0
                b = args[2] if len(args) > 2 else 0
                self.lp.LedCtrlRaw(bid, r, g, b)
        except: pass

    def get_events(self):
        ev = self.lp.ButtonStateRaw()
        if ev: return [(ev[0], ev[1])]
        return []

    def close(self):
        self.lp.Reset(); self.lp.Close()

print("\n" + "=" * 50)
print(" Quadraphonic Harmonic Synth")
print("=============================================================================================")
print("This script features a musical instrument that allows you to explore melodic lines, ")
print("to acquire a sensitivity to harmony, to create hybrid textures between harmonics and rhythm. ")
print("It is selectable by its starting note (root) and scale. There are many interesting scales, ")
print("including tonal, non-tonal and microtonal, one of which is randomly generated upon startup. ")
print("=============================================================================================")
print("- Top Button 0: Key Up (Increments root note)")
print("- Top Button 1: Key Down (Decrements root note)")
print("- Top Button 2: Scale Up (Cycles through 20+ musical scales)")
print("- Top Button 3: Scale Down (Cycles through 20+ musical scales)")
print("- Top Button 4: Harmonics Up (Momentary increase for Blit oscillator)")
print("- Top Button 5: Harmonics Down (Momentary decrease for Blit oscillator)")
print("- Top Button 6: Main Volume Down (Decrements master gain)")
print("- Top Button 7: Main Volume Up (Increments master gain)")
print("- Side Button 0: Reverb Cycle (OFF -> LOW -> MED -> HIGH)")
print("- Side Button 1: Delay Cycle (OFF -> LOW -> MED -> HIGH)")
print("- Side Button 2: Arpeggiator (ON/OFF)")
print("- Side Button 3: Drum Machine (OFF -> GREEN: Even -> AMBER: Odd -> RED: Silenced)")
print("- Side Button 4: Octave Up (Shifts grid pitch +3 octaves)")
print("- Side Button 5: Octave Down (Shifts grid pitch -3 octaves)")
print("- Side Button 6: Exit (Stops server and shuts down)")
print("- 8x8 Grid: Note trigger with Quad Panning (X/Y position determines output channel gain)")
print("=============================================================================================")
print("The grid adopts isomorphic not layout, scales start at (0,0) as the root note, ")
print("therefore changing scale draws a different chromatic organizazion, ")
print("opens with C Major scale. Same note show as white color, ")
print("so playing F on row (0) will light up also on row (1); ")
print("the notes on the 8x8 grid are laid out in fourths vertically. ")

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

# --- LAUNCHPAD DETECTION ---
lp = None
mode = None
EMULATE_MODE = args.emulate

if not EMULATE_MODE and HAS_MIDO:
    try:
        in_names = mido.get_input_names(); out_names = mido.get_output_names()
        lp_in = next((n for n in in_names if ("LPProMK3" in n or "Pro MK3" in n) and "DAW" not in n and "DIN" not in n), None)
        lp_out = next((n for n in out_names if ("LPProMK3" in n or "Pro MK3" in n) and "DAW" not in n and "DIN" not in n), None)
        if lp_in and lp_out:
            lp = LaunchpadMido(lp_in, lp_out); mode = "ProMk3"
            print("--- System: Launchpad Pro MK3 detected via Mido ---")
    except Exception as e: print(f"--- Mido Error: {e} ---")

if not EMULATE_MODE and lp is None and HAS_LAUNCHPAD_PY:
    try:
        lp_check = launchpad.Launchpad()
        if lp_check.Check(0, "mk2"):
            lp_check = launchpad.LaunchpadMk2(); lp_check.Open(0, "mk2")
            lp = LaunchpadPyWrapper(lp_check, "Mk2"); mode = "Mk2"
            print("--- System: Launchpad Mk2 detected ---")
        elif lp_check.Check(0):
            lp_check.Open(0)
            lp = LaunchpadPyWrapper(lp_check, "Mk1"); mode = "Mk1"
            print("--- System: Launchpad Mk1/S/Mini detected ---")
    except Exception as e: print(f"--- launchpad_py Error: {e} ---")

if lp is None:
    print("--- No hardware Launchpad found. Falling back to Emulation. ---")
    EMULATE_MODE = True; mode = "Mk1"; lp = VirtualLaunchpad(mode)

# Hardware Constants
# mode is "Mk1", "Mk2", "Pro", or "ProMk3"
# For LED and pad_id logic, Pro/ProMk3 behave like Mk2 (10-based grid)
IS_MK2_STYLE = (mode in ["Mk2", "Pro", "ProMk3"])

if IS_MK2_STYLE:
    SIDE_POWER_BTN = 29
else:
    SIDE_POWER_BTN = 104

print(f"--- Mode: {mode} ---")
lp_lock = threading.Lock()

# --- PYO SETUP ---
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

# --- 30 MUSICAL SCALES ---
SCALES = {
    "Major": [0, 2, 4, 5, 7, 9, 11], 
    "Minor": [0, 2, 3, 5, 7, 8, 10],
    "Indian Bhairav": [0, 1.12, 3.86, 4.98, 7.02, 8.14, 10.88],
    "Indian Marwa": [0, 1.12, 3.86, 5.90, 7.02, 9.06, 10.88],
    "Chinese Pentatonic": [0, 2.04, 3.86, 7.02, 9.06],
    "Ligeti Micro": [0, 0.5, 2.5, 3.5, 6.5, 7.5, 10.5],
    "Spectral": [0, 2.04, 3.86, 5.51, 7.02, 8.41, 9.69, 10.88],
    "Partch Otonality": [0, 2.04, 3.86, 4.98, 7.02, 8.84, 10.88],
    "Japanese Hirajoshi": [0, 2.04, 3.16, 7.02, 8.14],
    "Japanese In Sen": [0, 1.12, 4.98, 7.02, 8.14],
    "Dorian": [0, 2, 3, 5, 7, 9, 10], 
    "Phrygian": [0, 1, 3, 5, 7, 8, 10],
    "Lydian": [0, 2, 4, 6, 7, 9, 11], 
    "Mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "Locrian": [0, 1, 3, 5, 6, 8, 10], 
    "Harmonic Minor": [0, 2, 3, 5, 7, 8, 11],
    "Melodic Minor": [0, 2, 3, 5, 7, 9, 11], 
    "Pentatonic Maj": [0, 2, 4, 7, 9],
    "Pentatonic Min": [0, 3, 5, 7, 10], 
    "Blues": [0, 3, 5, 6, 7, 10],
    "Whole Tone": [0, 2, 4, 6, 8, 10], 
    "Acoustic": [0, 2, 4, 6, 7, 9, 10],
    "Altered": [0, 1, 3, 4, 6, 8, 10], 
    "Phrygian Dom": [0, 1, 4, 5, 7, 8, 10],
    "Hungarian Min": [0, 2, 3, 6, 7, 8, 11], 
    "Double Harm": [0, 1, 4, 5, 7, 8, 11],
    "15-TET": [0, 1.6, 4.0, 5.6, 8.0, 9.6, 11.2],
    "19-TET": [0, 1.89, 3.79, 5.05, 6.95, 8.84, 10.74],
    "Bohlen-Pierce": [0, 1.46, 2.93, 4.39, 5.85, 7.32, 8.78],
    "Just Intonation": [0, 2.31, 3.86, 4.98, 7.02, 9.33, 10.88]
}

def init_random_scale():
    count = random.randint(5, 8)
    scale = [0]
    while len(scale) < count:
        val = random.uniform(0.8, 11.5)
        if all(abs(val - x) > 0.5 for x in scale):
            scale.append(val)
    scale.sort()
    name = f"Rnd Micro {random.randint(100, 999)}"
    SCALES[name] = scale


init_random_scale()
SCALE_NAMES = list(SCALES.keys())
KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# --- GLOBAL & AUDIO STATE ---
cur_key, cur_scale, octave_offset = 0, 0, 0
active_voices = {}
held_pitches = set()
running = True
harms_up_held = False
harms_down_held = False
arp_active = False
drum_mode = 0 
drum_beats = 16

# --- QUAD AUDIO CHAIN ---
MAX_VOICES = 16
harms_sig = Sig(value=5)
harms_port = Port(harms_sig, risetime=0.5, falltime=0.5)

voices_osc = []
voices_env = []
voices_gains = [] 
voices_outs = []  

for _ in range(MAX_VOICES):
    env = Adsr(attack=0.1, decay=0.3, sustain=0.6, release=0.8, dur=0, mul=0.2)
    osc = Blit(freq=100, harms=harms_port, mul=env)
    gains = [Sig(0) for _ in range(4)]
    ports = [Port(g, 0.05, 0.05) for g in gains]
    outs = [osc * p for p in ports]
    voices_osc.append(osc)
    voices_env.append(env)
    voices_gains.append(gains)
    voices_outs.append(outs)

quad_buses = [Mix([v[i] for v in voices_outs], voices=1) for i in range(4)]

# --- DRUM SYNTH SECTION (Lower Amplitude) ---
d_env = Adsr(attack=0.001, decay=0.1, sustain=0, release=0.05, dur=0.15, mul=0.04)
d_bd = Sine(freq=55, mul=d_env)
d_noise = Noise(mul=d_env)
d_snare = Resonx(d_noise, freq=1200, q=4)
d_hh = ButHP(d_noise, freq=6000)
d_fm = CrossFM(carrier=1000, ratio=1.4, ind1=12, mul=d_env) 
d_mix = Mix([d_bd, d_snare, d_hh, d_fm], voices=1)

# Quad LFO for Drums
d_lfo_pan = [d_mix * Sine(freq=0.15, phase=i/4.0, mul=0.5, add=0.5) for i in range(4)]

# --- EFFECTS (DELAY -> REVERB) ---

# 1. DELAY (WITH NATURAL TAIL FADE)
delay_time_sig = Sig(0.0075) 
delay_feed_sig = Sig(0.55)
delay_feed_port = Port(delay_feed_sig, 0.2, 0.2)
delay_input_mix = Sig(0) 
delay_input_port = Port(delay_input_mix, 0.2, 0.2) # Ramps input to delay

# Mix Grid + Drum LFO before delay
combined_to_delay = [(quad_buses[i] + d_lfo_pan[i]) for i in range(4)]

delays = [Delay(combined_to_delay[i] * delay_input_port, delay=delay_time_sig, feedback=delay_feed_port, mul=1.0) for i in range(4)]
delay_to_reverb = [combined_to_delay[i] + delays[i] for i in range(4)]

# 2. REVERB
SIZE = [.59,.8,.65,.75]
rev_mix_sig = Sig(0)
rev_mix_port = Port(rev_mix_sig, risetime=0.5, falltime=0.5)
#rev_size_sig = Sig(0.5)
reverbs = [Freeverb(delay_to_reverb[i], size=Sig(SIZE[i]), damp=0.5, bal=rev_mix_port) for i in range(4)]

# --- Master Volume with Fader 
master_fader = Fader(fadein=4.0, fadeout=2.0, dur=0, mul=0.6).play()
master_vol_port = Port(master_fader, 0.1, 0.1)
amp_scale = Min(harms_port / 5.0, 2.0)

GLOBAL_BOOST = 2.0 
amp_final = master_vol_port * amp_scale * GLOBAL_BOOST

# Channel assignment: auto-fold to 2 channels when num_channels == 2
final_outs = [(reverbs[i] * amp_final).out(i % num_channels) for i in range(4)]

voice_ptr = 0

print("--- Audio Engine Started ---")
print("\n***************************************************")
print("    >>> PRESS [ESC] AT ANY TIME TO EXIT <<<")
print("***************************************************\n")

# --- Initialize Global Keyboard Manager SAFELY ---
kb_mgr = KeyboardManager()

# --- HELPER FUNCTIONS ---
fx_states = [0, 0, 0, 0] 
led_queue = queue.Queue()
led_cache = {}

def led_worker():
    while True:
        func, args = led_queue.get()
        try: func(*args)
        except Exception as e: print(f"LED Error: {e}")
        led_queue.task_done()

t_led = threading.Thread(target=led_worker); t_led.daemon = True; t_led.start()

def clear_all_leds():
    if EMULATE_MODE: led_cache.clear(); return
    with lp_lock:
        lp.ButtonFlush()
        if IS_MK2_STYLE:
            for i in range(11, 112): lp.LedCtrlRaw(i, 0, 0, 0)
        else:
            for i in range(128): lp.LedCtrlRaw(i, 0, 0)
        led_cache.clear()

def get_quad_gains(x, y_logical):
    nx = x / 7.0; ny = (7 - y_logical) / 7.0 
    return [(1.-nx)*(1.-ny), nx*(1.-ny), (1.-nx)*ny, nx*ny]

def get_pitch(x, y_logical):
    return 36 + cur_key + x + (y_logical * 5) + (octave_offset * 12)

def get_led_color(pitch, pad_id):
    if pad_id in active_voices or pitch in held_pitches:
        return (63, 63, 63) if IS_MK2_STYLE else (3, 3)
    rel_pitch = (pitch - cur_key) % 12
    scale = SCALES[SCALE_NAMES[cur_scale]]
    closest = min(scale, key=lambda x: abs(x - rel_pitch))
    if abs(closest - rel_pitch) < 0.5:
        if abs(closest) < 0.1: return (63, 0, 0) if IS_MK2_STYLE else (3, 0)
        return (0, 63, 0) if IS_MK2_STYLE else (0, 3)
    return (0, 0, 0)

def update_pad_immediate(x, y_logical):
    if EMULATE_MODE: return
    if IS_MK2_STYLE: pad_id = (y_logical + 1) * 10 + (x + 1)
    else: pad_id = ((7 - y_logical) * 16) + x
    pitch = get_pitch(x, y_logical)
    col = get_led_color(pitch, pad_id)
    with lp_lock:
        if pad_id in led_cache and led_cache[pad_id] == col: return
        if IS_MK2_STYLE: lp.LedCtrlRaw(pad_id, col[0], col[1], col[2])
        else: lp.LedCtrlRaw(pad_id, col[0], col[1])
        led_cache[pad_id] = col

def queue_pad_update(x, y_logical): led_queue.put((update_pad_immediate, (x, y_logical)))

def refresh_grid_immediate():
    if EMULATE_MODE: return
    for y_logical in range(8):
        for x in range(8): update_pad_immediate(x, y_logical)
        time.sleep(0.003) 
    with lp_lock:
        for i in range(4):
            state = fx_states[i]
            if i == 0: # Reverb
                if IS_MK2_STYLE:
                    col = [(0,0,0),(0,63,0),(63,63,0),(63,0,0)][state] 
                    lp.LedCtrlRaw(89 - (i * 10), *col)
                else:
                    col = [(0,0),(0,3),(3,3),(3,0)][state] 
                    lp.LedCtrlRaw(8 + (i * 16), col[0], col[1])
            elif i == 1: # Delay
                if IS_MK2_STYLE:
                    col = [(0,0,0), (0,30,0), (63,40,0), (63,0,0)][state] 
                    lp.LedCtrlRaw(89 - (i * 10), *col)
                else:
                    col = [(0,0), (0,1), (3,1), (3,0)][state] 
                    lp.LedCtrlRaw(8 + (i * 16), col[0], col[1])
            elif i == 2: # Arpeggiator
                col = (0, 63, 0) if arp_active else (0, 0, 0)
                if IS_MK2_STYLE: lp.LedCtrlRaw(89 - (i * 10), *col)
                else: lp.LedCtrlRaw(8 + (i * 16), 0 if not arp_active else 3, 0)
            elif i == 3: # Drum Machine
                d_col = [(0,0,0), (0,63,0), (63,63,0), (63,0,0)][drum_mode] if IS_MK2_STYLE else [(0,0), (0,3), (3,3), (3,0)][drum_mode]
                if IS_MK2_STYLE: lp.LedCtrlRaw(89 - (i * 10), *d_col)
                else: lp.LedCtrlRaw(8 + (i * 16), d_col[0], d_col[1])
        for i in range(4, 6):
            if octave_offset == 0: col = (0, 63, 0) if IS_MK2_STYLE else (0, 3)
            else: col = (63, 20, 0) if IS_MK2_STYLE else (3, 1)
            if IS_MK2_STYLE: lp.LedCtrlRaw(89 - (i * 10), *col)
            else: lp.LedCtrlRaw(8 + (i * 16), col[0], col[1])
        if IS_MK2_STYLE: lp.LedCtrlRaw(SIDE_POWER_BTN, 10, 10, 63)
        else: lp.LedCtrlRaw(SIDE_POWER_BTN, 1, 3)
    
    h_val = int(harms_sig.value)
    with lp_lock:
        if IS_MK2_STYLE:
            h_col = (0,63,0) if h_val<20 else (63,63,0) if h_val<40 else (63,0,0)
            lp.LedCtrlRaw(104+4 if mode == "Mk2" else 95, *h_col)
            lp.LedCtrlRaw(104+5 if mode == "Mk2" else 96, *h_col)
        else:
            h_col = (0,3) if h_val<20 else (3,3) if h_val<40 else (3,0)
            lp.LedCtrlRaw(200+4, *h_col); lp.LedCtrlRaw(200+5, *h_col)
    
    vol = master_fader.mul
    with lp_lock:
        if IS_MK2_STYLE:
            v_col = (0,63,0) if vol<0.4 else (63,63,0) if vol<0.7 else (63,0,0)
            lp.LedCtrlRaw(104+6 if mode == "Mk2" else 97, *v_col)
            lp.LedCtrlRaw(104+7 if mode == "Mk2" else 98, *v_col)
        else:
            v_col = (0,3) if vol<0.4 else (3,3) if vol<0.7 else (3,0)
            lp.LedCtrlRaw(200+6, *v_col); lp.LedCtrlRaw(200+7, *v_col)

def refresh_grid(): led_queue.put((refresh_grid_immediate, ()))

def update_pitch_leds(target_pitch):
    for y in range(8):
        for x in range(8):
            if get_pitch(x, y) == target_pitch: queue_pad_update(x, y)

def apply_immediate_transpose():
    """Recalculates frequency for all currently active voices."""
    for pid, v_idx in active_voices.items():
        if IS_MK2_STYLE: x, y_log = (pid % 10) - 1, (pid // 10) - 1
        else: x, y_log = pid % 16, 7 - (pid // 16)
        pitch = get_pitch(x, y_log)
        scale = SCALES[SCALE_NAMES[cur_scale]]
        rel_pitch = (pitch - cur_key) % 12
        closest = min(scale, key=lambda x: abs(x - rel_pitch))
        if abs(closest - rel_pitch) < 0.5:
            voices_osc[v_idx].setFreq(midiToHz(pitch - rel_pitch + closest))
        else:
            voices_osc[v_idx].setFreq(midiToHz(pitch))

def play_note(pad_id, x, y_logical):
    global voice_ptr
    pitch = get_pitch(x, y_logical); scale = SCALES[SCALE_NAMES[cur_scale]]
    rel_pitch = (pitch - cur_key) % 12; closest = min(scale, key=lambda x: abs(x - rel_pitch))
    if abs(closest - rel_pitch) < 0.5: voices_osc[voice_ptr].setFreq(midiToHz(pitch - rel_pitch + closest))
    else: voices_osc[voice_ptr].setFreq(midiToHz(pitch))
    gains = get_quad_gains(x, y_logical)
    for i in range(4): voices_gains[voice_ptr][i].value = gains[i]
    voices_env[voice_ptr].play(); active_voices[pad_id] = voice_ptr
    voice_ptr = (voice_ptr + 1) % MAX_VOICES; held_pitches.add(pitch); update_pitch_leds(pitch)

def stop_note(pad_id, x, y_logical):
    pitch = get_pitch(x, y_logical)
    if pad_id in active_voices: voices_env[active_voices[pad_id]].stop(); del active_voices[pad_id]
    still_held = any(get_pitch((pid%10-1 if IS_MK2_STYLE else pid%16), (pid//10-1 if IS_MK2_STYLE else 7-(pid//16))) == pitch for pid in active_voices)
    if not still_held and pitch in held_pitches: held_pitches.remove(pitch)
    update_pitch_leds(pitch)

# --- ARPEGGIATOR THREAD ---
def arpeggiator_loop():
    arp_ptr = 0
    arp_octave = 0
    direction = 1
    while running:
        if arp_active and held_pitches:
            sorted_held = sorted(list(held_pitches))
            pitch = sorted_held[arp_ptr % len(sorted_held)]
            final_pitch = pitch + (arp_octave * 12)
            # Default to green delay speed (0.2s) if delay is OFF
            current_speed = delay_time_sig.value if fx_states[1] > 0 else 0.2
            for v_idx in range(MAX_VOICES):
                voices_osc[v_idx].setFreq(midiToHz(final_pitch))
            arp_ptr += 1
            arp_octave += direction
            if abs(arp_octave) >= 3: direction *= -1
            time.sleep(current_speed)
        else:
            time.sleep(0.1)

t_arp = threading.Thread(target=arpeggiator_loop); t_arp.daemon = True; t_arp.start()

# --- DRUM MACHINE THREAD ---
def drum_loop():
    step = 0
    while running:
        if drum_mode > 0:
            # Silence mode (Red) logic
            is_silent = (drum_mode == 3 and random.random() < 0.25)
            
            if not is_silent:
                # Random repetition for Even (Green) or Odd (Amber)
                reps = random.randint(1, 4) if drum_mode in [1, 2] else 1
                inst = random.randint(0, 11)
                
                for _ in range(reps):
                    if step >= 16: break # Keep strictly to 16 beats
                    
                    if inst == 0: d_bd.freq = random.choice([50, 55, 60]); d_env.play()
                    elif inst == 1: d_snare.mul = 0.2; d_env.play()
                    elif inst == 2: d_hh.mul = 0.15; d_env.play()
                    elif inst == 3: d_fm.carrier = 220; d_env.play()
                    elif inst == 4: d_fm.carrier = 4000; d_env.play()
                    elif inst == 5: d_fm.carrier = 800; d_env.play()
                    elif inst == 6: d_fm.carrier = 140; d_env.play()
                    elif inst == 7: d_hh.mul = 0.08; d_env.play()
                    elif inst == 8: d_snare.mul = 0.4; d_env.play()
                    
                    step = (step + 1) % 16
                    time.sleep(delay_time_sig.value if fx_states[1] > 0 else 0.2)
            else:
                step = (step + 1) % 16
                time.sleep(delay_time_sig.value if fx_states[1] > 0 else 0.2)
        else:
            time.sleep(0.1)

t_drum = threading.Thread(target=drum_loop); t_drum.daemon = True; t_drum.start()

clear_all_leds(); refresh_grid()

def launchpad_listener():
    global cur_key, cur_scale, harms_sig, running, octave_offset, harms_up_held, harms_down_held, arp_active, drum_mode, drum_beats
    while running:
        if harms_up_held:
            harms_sig.value = min(60, harms_sig.value + 1.0)
            print(f"Harmonics: {int(harms_sig.value)} | Vol: {round(master_fader.mul, 2)} | Key: {KEYS[cur_key]} | Scale: {SCALE_NAMES[cur_scale]}")
            refresh_grid(); time.sleep(0.1)
        if harms_down_held:
            harms_sig.value = max(5, harms_sig.value - 1.0)
            print(f"Harmonics: {int(harms_sig.value)} | Vol: {round(master_fader.mul, 2)} | Key: {KEYS[cur_key]} | Scale: {SCALE_NAMES[cur_scale]}")
            refresh_grid(); time.sleep(0.1)

        # Cross-platform ESC exit check
        key = kb_mgr.get_key()
        if key == '\x1b':
            print("\n--- System: ESC Pressed. Fading out... ---")
            master_fader.stop()
            threading.Timer(2.1, lambda: globals().update(running=False)).start()
            break

        # Unified event handling
        if EMULATE_MODE:
            events = lp.process_key(key)
        else:
            events = lp.get_events()

        for ev_item in events:
            bid, state = ev_item[0], ev_item[1]

            # Top button detection
            if IS_MK2_STYLE:
                top_base = 104 if mode == "Mk2" else 91
                is_top = (top_base <= bid <= top_base + 7)
                idx = bid - top_base if is_top else -1
            else:
                is_top = (200 <= bid <= 207)
                idx = (bid - 200) if is_top else -1

            if is_top:
                if state > 0:
                    if idx == 0: cur_key = (cur_key + 1) % 12; apply_immediate_transpose()
                    elif idx == 1: cur_key = (cur_key - 1) % 12; apply_immediate_transpose()
                    elif idx == 2: cur_scale = (cur_scale + 1) % len(SCALE_NAMES)
                    elif idx == 3: cur_scale = (cur_scale - 1) % len(SCALE_NAMES)
                    elif idx == 4: harms_up_held = True
                    elif idx == 5: harms_down_held = True
                    elif idx == 6: master_fader.mul = max(0.0, master_fader.mul - 0.05)
                    elif idx == 7: master_fader.mul = min(1.0, master_fader.mul + 0.05)
                    
                    if idx in [0,1,2,3,6,7]:
                        print(f"Key: {KEYS[cur_key]} | Scale: {SCALE_NAMES[cur_scale]} | Volume: {round(master_fader.mul, 2)}")
                        refresh_grid()
                else:
                    if idx == 4: harms_up_held = False
                    elif idx == 5: harms_down_held = False

            # Side button detection
            if IS_MK2_STYLE:
                side_idx = (8 - (bid // 10)) if (bid % 10 == 9) else -1
            else:
                side_idx = (bid // 16) if (bid % 16 == 8) else -1

            if side_idx == 0 and state > 0:
                fx_states[0] = (fx_states[0] + 1) % 4
                rev_mix_sig.value = [0.0, 0.3, 0.5, 0.65][fx_states[0]]
                rev_size_sig.value = [0.5, 0.4, 0.7, 0.95][fx_states[0]]
                print(f"Reverb: {['OFF', 'LOW', 'MED', 'HIGH'][fx_states[0]]} | Mix: {rev_mix_sig.value} | Size: {rev_size_sig.value}")
                refresh_grid()
            elif side_idx == 1 and state > 0:
                fx_states[1] = (fx_states[1] + 1) % 4
                delay_input_mix.value = [0.0, 0.3, 0.45, 0.6][fx_states[1]] 
                delay_time_sig.value = [0.0075, 0.2, 0.4, 1.0][fx_states[1]] 
                delay_feed_sig.value = [0.55, 0.6, 0.7, 0.8][fx_states[1]]
                print(f"Delay: {['OFF', 'LOW', 'MED', 'HIGH'][fx_states[1]]} | Time: {delay_time_sig.value}s | Feedback: {delay_feed_sig.value} | Input: {delay_input_mix.value}")
                refresh_grid()
            elif side_idx == 2 and state > 0:
                arp_active = not arp_active
                print(f"Arpeggiator: {'ON' if arp_active else 'OFF'}")
                refresh_grid()
            elif side_idx == 3 and state > 0:
                drum_mode = (drum_mode + 1) % 4
                print(f"Drums: {['OFF', 'GREEN (Even)', 'AMBER (Odd)', 'RED (Silence)'][drum_mode]}")
                refresh_grid()
            elif (side_idx == 4 or side_idx == 5) and state > 0:
                octave_offset = min(3, octave_offset + 1) if side_idx == 4 else max(-3, octave_offset - 1)
                apply_immediate_transpose()
                print(f"Octave: {octave_offset}"); refresh_grid()

            elif bid == SIDE_POWER_BTN and state > 0: 
                print("FADING OUT..."); master_fader.stop()
                # Delay shutdown to allow for the 2-second fade
                threading.Timer(2.1, lambda: globals().update(running=False)).start()
            elif not is_top:
                if IS_MK2_STYLE and bid % 10 != 9: x, y_log = (bid % 10) - 1, (bid // 10) - 1
                elif not IS_MK2_STYLE and bid % 16 < 8: x, y_log = bid % 16, 7 - (bid // 16)
                else: x, y_log = -1, -1
                if 0 <= x < 8 and 0 <= y_log < 8:
                    if state > 0: play_note(bid, x, y_log)
                    else: stop_note(bid, x, y_log)
        time.sleep(0.001)

t = threading.Thread(target=launchpad_listener); t.daemon = True; t.start()
try:
    while running: time.sleep(0.1)
except KeyboardInterrupt: print("\nKeyboard Interrupt detected."); running = False
finally:
    running = False
    # Give daemon threads time to notice running=False and exit cleanly
    time.sleep(0.3)
    
    if 's' in locals():
        s.stop()
        try:
            s.shutdown()
        except:
            pass
        time.sleep(0.1)
    
    if 'lp' in locals() and lp:
        if isinstance(lp, (LaunchpadMido, VirtualLaunchpad)):
            lp.close()
        elif not EMULATE_MODE:
            try:
                lp.lp.Reset()
                lp.lp.Close()
            except:
                pass
                
    if 'kb_mgr' in locals():
        kb_mgr.close()
    print("--- System Offline ---")
    os._exit(0)