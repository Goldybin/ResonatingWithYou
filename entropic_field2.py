import sys, os
import time
import random
import threading
import argparse
from collections import deque
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
Entropic field
======================================================================================
- Top Buttons 0-1: Scale Selection (Cycle SCALES_DICT, Green/Amber)
- Top Buttons 2-3: Position Selection (Cycle LEFT/RIGHT/TOP/BOTTOM, Amber)
- Top Buttons 6-7: Main Volume (Amber 60%, Adjusts user_vol)

- Side Button 0: Start Sequence (Locks Setup Mode, Red/Green)
- Side Button 1: Reverb Toggle (Cycle 0.0-0.7 Mix, Green/Amber/Red)
- Side Button 2: Filter Toggle (Schumann Resonance 7.83Hz, Green/Amber)
- Side Button 3: Delay Toggle (Temporal Delay 0.1s-0.2s, Green/Amber)
- Side Button 6: EXIT / POWER OFF (Blue/Cyan - Matched to test_speakers)

======================================================================================
This script creates a chaotic motion of cells, initially stacked in two columns. 
You can select the initial layout, default to left which works also in stereo, 
when top or bottom, which goes from bright to dull tone or opposite, 
only works with 4 speakers; you may also experiment with reverb, delay and speed. 
Entropy increases and the cells move for about 4 minutes, reaching the opposite side.
======================================================================================

- Universal Launchpad Support (Mk1, Mk2, Pro, MK3 Pro)
- Auto detection 2 or 4 channel sounds
- Cross-platform Keyboard Emulation (Windows & macOS)
- Global ESC key to exit with ANSI-sequence filtering
- Auto Programmer Mode entry for MK3 Pro (via Mido/RtMidi)

======================================================================================
Example of default scale (Partch Otonality)

[Y]  TOP of Grid (High Pitch)
   0 |  10/4    11/4    3/1     13/4* ...  <-- Higher Harmonics
   1 |  8/4     9/4     10/4    11/4    ...  
   2 |  6/4     7/4     8/4     9/4     ...  
   3 |  4/4     5/4     6/4     7/4     ...  <-- Degree 0 (Root 1/1)
   4 |  2/1     9/4     10/4    11/4    ...  
   5 |  7/4     8/4     9/4     10/4    ...  
   6 |  5/4     6/4     7/4     8/4     ...  
   7 |  1/1     5/4     6/4     7/4     ...  <-- Root (4/4)
     +--------------------------------------
 [X]    0        1       2       3      RIGHT (+1 Degree)
"""

# --- CLI Arguments (Extended from test_speakers.py) ---
parser = argparse.ArgumentParser(description="Entropic Field - 4-Channel Generative Audio")
parser.add_argument('-e', '--emulate', action='store_true', help='Force Launchpad emulation mode')
parser.add_argument('-c', '--channels', type=int, choices=[2, 4], help='Force number of audio channels (2 or 4)')
parser.add_argument('-d', '--device', type=int, help='Set audio output device ID')
parser.add_argument('-s', '--scale', type=int, help='Set initial scale index (0-based)')
parser.add_argument('-p', '--position', type=int, choices=[0, 1, 2, 3], help='Set initial position (0=LEFT, 1=RIGHT, 2=TOP, 3=BOTTOM)')
args, _ = parser.parse_known_args()

AUDIO_DEVICE = 10 if sys.platform != 'darwin' else -1
if args.device is not None:
    AUDIO_DEVICE = args.device

AUDIO_HOST = 'coreaudio' if sys.platform == 'darwin' else 'asio'
BUFFER_SIZE = 1024

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
        print(" SETUP CONTROLS:")
        print(" [q] - Scale Down            [w] - Scale Up")
        print(" [a] - Position Down         [s] - Position Up")
        print(" [-] - Vol Down              [+] - Vol Up")
        print(" [Enter] - Start Sequence")
        print("")
        print(" FX CONTROLS:")
        print(" [p] - Reverb Toggle")
        print(" [o] - Filter Toggle (Schumann Resonance)")
        print(" [l] - Delay Toggle (Temporal Delay)")
        print("=" * 60 + "\n")

    def close(self):
        pass  # Handled globally by KeyboardManager

    def LedCtrlRaw(self, bid, r, g, b=None):
        pass

    def LedCtrlXY(self, x, y, r, g):
        pass

    def Reset(self):
        pass

    def process_key(self, char):
        if not char:
            # Auto-release keys on the next cycle
            for bid in list(self.key_states.keys()):
                if self.key_states[bid]:
                    self.key_states[bid] = False
                    return [(bid, 0)]
            return []

        # Top button controls (Mk1 raw IDs)
        ctrl_map = {
            'q': 200, 'w': 201,   # Scale Down / Up (TOP_BTNS[0], TOP_BTNS[1])
            'a': 202, 's': 203,   # Position Down / Up (TOP_BTNS[2], TOP_BTNS[3])
            '-': 206, '+': 207, '=': 207,   # Vol Down / Up (TOP_BTNS[6], TOP_BTNS[7])
        }
        # Side button controls (Mk1 raw IDs)
        side_map = {
            '\n': 8,   # Start Sequence (SIDE_START_BTN)
            '\r': 8,   # Start Sequence (Windows Enter)
            'p': 24,   # Reverb Toggle (SIDE_REV_BTN)
            'o': 40,   # Filter Toggle (SIDE_FILT_BTN)
            'l': 56,   # Delay Toggle (SIDE_DLY_BTN)
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
        self._event_buffer = deque()
        print(f"--- MIDI IN Connected to: {in_port_name} ---")
        print(f"--- MIDI OUT Connected to: {out_port_name} ---")

        print("-> Entering Programmer Mode...")
        self.out_port.send(mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x0E, 0x01]))
        time.sleep(1.0)

        print("-> Clearing Grid...")
        # Send a batch of off-color specs to clear the surface
        self.out_port.send(mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x03, 0x00, 0x00]))
        time.sleep(0.1)

        for i in range(128):
            self.out_port.send(mido.Message('note_off', note=i, velocity=0))
            self.out_port.send(mido.Message('control_change', control=i, value=0))
        time.sleep(0.1)

    def LedCtrlRaw(self, bid, r, g, b=None):
        """LED control compatible with launchpad_py API.
        For RGB mode (3 color args): r,g,b in range 0-63 (MK2/Pro/ProMk3 convention).
        For Mk1 mode (2 color args): r,g in range 0-3."""
        if b is not None:
            # RGB mode (0-63 from launchpad_py) -> scale to 0-127 for SysEx
            r_val = min(127, int(r * 2))
            g_val = min(127, int(g * 2))
            b_val = min(127, int(b * 2))
        else:
            # Mk1 style (r,g = 0-3) -> approximate RGB
            r_val = min(127, int(r * 42))
            g_val = min(127, int(g * 42))
            b_val = 0
        self.out_port.send(mido.Message('sysex',
            data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x03, 0x03, bid, r_val, g_val, b_val]))

    def LedCtrlXY(self, x, y, r, g):
        """LED control by X/Y coordinates (Mk1 style), converted to ProMk3 raw ID."""
        bid = (8 - y) * 10 + x + 1
        self.LedCtrlRaw(bid, r, g)

    def Reset(self):
        """Clear all LEDs by exiting programmer mode."""
        self.out_port.send(mido.Message('sysex',
            data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x03, 0x00, 0x00]))
        time.sleep(0.1)

    def ButtonStateRaw(self):
        """Return a single event [bid, state] or empty list, compatible with launchpad_py."""
        for msg in self.in_port.iter_pending():
            if msg.type in ['note_on', 'note_off']:
                state = msg.velocity if msg.type == 'note_on' else 0
                self._event_buffer.append([msg.note, state])
            elif msg.type == 'control_change':
                self._event_buffer.append([msg.control, msg.value])
        if self._event_buffer:
            return self._event_buffer.popleft()
        return []

    def close(self):
        print("-> Exiting Programmer Mode...")
        self.out_port.send(mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x0E, 0x00]))
        self.in_port.close()
        self.out_port.close()

print("\n" + "=" * 50)
print(" Entropic Field - Generative Audio")
print("======================================================================================")
print("This script creates a chaotic motion of cells, initially stacked in two columns. ")
print("You can select the initial layout, default to left which works also in stereo, ")
print("when top or bottom, which goes from bright to dull tone or opposite, ")
print("only works with 4 speakers; you may also experiment with reverb, delay and speed. ")
print("Entropy increases and the cells move for about 4 minutes, reaching the opposite side.")
print("======================================================================================")
print("- Top Buttons 0-1: Scale Selection (Cycle SCALES_DICT, Green/Amber)")
print("- Top Buttons 2-3: Position Selection (Cycle LEFT/RIGHT/TOP/BOTTOM, Amber)")
print("- Top Buttons 6-7: Main Volume (Amber 60%, Adjusts user_vol)")
print("- Side Button 0: Start Sequence (Locks Setup Mode, Red/Green)")
print("- Side Button 1: Reverb Toggle (Cycle 0.0-0.7 Mix, Green/Amber/Red)")
print("- Side Button 2: Filter Toggle (Schumann Resonance 7.83Hz, Green/Amber)")
print("- Side Button 3: Delay Toggle (Temporal Delay 0.1s-0.2s, Green/Amber)")
print("- Side Button 6: EXIT / POWER OFF (Blue/Cyan - Matched to test_speakers)")

print("\n" + "=" * 50)
print(" COMMAND LINE ARGUMENTS:")
print(" '-e', '--emulate', Force Launchpad emulation mode ")
print(" '-c <2 or 4>', '--channels <2 or 4>', Force number of audio channels (2 or 4) ")
print(" '-d <id>', '--device <id>', Set audio output device ID ")
print(" '-s <idx>', '--scale <idx>', Set initial scale index (0-based) ")
print(" '-p <0-3>', '--position <0-3>', Set initial position (LEFT/RIGHT/TOP/BOTTOM) ")

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

# --- Find Launchpad Ports & Assign Mode ---
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
        if lp_check.Check(0, "mk2"):
            lp = launchpad.LaunchpadMk2()
            lp.Open(0, "mk2")
            mode = "Mk2"
            print("--- System: Launchpad Mk2 detected ---")
        elif lp_check.Check(0, "pro"):
            lp = launchpad.LaunchpadPro()
            lp.Open(0, "pro")
            mode = "Pro"
            print("--- System: Launchpad Pro detected ---")
        elif lp_check.Check(0):
            lp.Open(0)
            mode = "Mk1"
            print("--- System: Launchpad Mk1/S/Mini detected ---")
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
    SIDE_START_BTN = 8
    SIDE_REV_BTN = 24
    SIDE_FILT_BTN = 40
    SIDE_DLY_BTN = 56
    SIDE_POWER_BTN = 120
    TOP_BTNS = [200, 201, 202, 203, 204, 205, 206, 207]
elif mode == "Mk2":
    SIDE_START_BTN = 89
    SIDE_REV_BTN = 79
    SIDE_FILT_BTN = 69
    SIDE_DLY_BTN = 59
    SIDE_POWER_BTN = 29
    TOP_BTNS = [104, 105, 106, 107, 108, 109, 110, 111]
elif mode in ["Pro", "ProMk3"]:
    SIDE_START_BTN = 89
    SIDE_REV_BTN = 79
    SIDE_FILT_BTN = 69
    SIDE_DLY_BTN = 59
    SIDE_POWER_BTN = 29
    TOP_BTNS = [91, 92, 93, 94, 95, 96, 97, 98]

# --- 2. Audio Setup ---
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

# --- 3. Configuration & Palette ---
SCALES_DICT = {
    "Chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    "Indian Bhairav": [0, 1.12, 3.86, 4.98, 7.02, 8.14, 10.88],
    "Partch Otonality": [0, 2.04, 3.86, 4.98, 7.02, 8.84, 10.88],
    "Partch Utonality": [0, 1.12, 3.16, 4.98, 7.02, 8.14, 9.96],
    "Partch Diamond": [0, 1.51, 1.65, 1.82, 2.04, 2.31, 2.67, 3.18, 3.47, 3.86, 4.35, 4.98, 5.51, 6.49, 7.02, 7.65, 8.14, 8.53, 8.84, 9.33, 9.69, 9.96, 10.18, 10.35, 10.49, 10.88, 11.44],
    "Young Lamonte": [0, 1.14, 3.86, 4.98, 7.02, 8.14, 10.88],
    "31-TET Pure": [0, 1.93, 3.87, 5.03, 6.96, 8.90, 10.83],
    "Bohlen-Pierce": [0, 1.46, 2.92, 4.38, 5.84, 7.30, 8.76, 10.22, 11.68],
    "Carlos Alpha": [0, 0.78, 1.56, 2.34, 3.12, 3.90, 4.68, 5.46, 6.24, 7.02],
    "Gamelan Slendro": [0, 2.4, 4.8, 7.2, 9.6],
    "Random 1": sorted([0] + [round(random.uniform(0.5, 11.5), 2) for _ in range(6)]),
}
SCALE_NAMES = list(SCALES_DICT.keys())
POS_NAMES = ["LEFT", "RIGHT", "TOP", "BOTTOM"]

COLOR_MAP = {
    "Chromatic": (63, 63, 63) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 3),
    "Indian Bhairav": (63, 10, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 1),
    "Partch Otonality": (0, 63, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (0, 3),
    "Partch Utonality": (63, 0, 30) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 1),
    "Partch Diamond": (63, 40, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 2),
    "Young Lamonte": (30, 0, 63) if mode in ["Mk2", "Pro", "ProMk3"] else (1, 1),
    "31-TET Pure": (0, 63, 63) if mode in ["Mk2", "Pro", "ProMk3"] else (0, 2),
    "Bohlen-Pierce": (63, 0, 63) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 0),
    "Carlos Alpha": (63, 63, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 2),
    "Gamelan Slendro": (0, 15, 63) if mode in ["Mk2", "Pro", "ProMk3"] else (1, 3),
    "Random 1": (20, 63, 20) if mode in ["Mk2", "Pro", "ProMk3"] else (1, 2),
}

# --- 4. Logic State ---
cells = []
running = True
setup_mode = True
lock = threading.Lock()
sel_scale_idx = args.scale if args.scale is not None and 0 <= args.scale < len(SCALE_NAMES) else 2
sel_pos_idx = args.position if args.position is not None else 0
last_led_state = set()

MAX_VOICES = 16

global_harms_base = Sig(1)
base_port = Port(global_harms_base, risetime=0.1, falltime=0.1)
global_harms_range = Sig(0)
range_port = Port(global_harms_range, risetime=0.1, falltime=0.1)
user_vol = Sig(0.6)
fade_vol = Sig(0)
fade_port = Port(fade_vol, risetime=0.1, falltime=0.1)
master_gain = user_vol * fade_port

rev_levels = [0.0, 0.3, 0.5, 0.7]
rev_gains = [1.0, 1.05, 1.15, 1.35]
rev_idx = 1
global_rev_bal = Sig(rev_levels[rev_idx])
global_rev_comp = Sig(rev_gains[rev_idx])
rev_port = Port(global_rev_bal, risetime=0.1, falltime=0.1)
comp_port = Port(global_rev_comp, risetime=0.1, falltime=0.1)

filt_idx = 0
filt_rates = [0.0, 7.83, 15.66]
filt_base_rate = Sig(0)

dly_idx = 0
dly_times = [0.0, 0.2, 0.1]
dly_time_sig = Sig(0)
dly_feed = Sig(0.4)

class GridVoice:
    def __init__(self, voice_idx):
        self.freq = Sig(0); self.gate = Sig(0)
        self.amp = Port(self.gate, 0.5, 2.0)
        self.lfo = Sine(freq=random.uniform(0.025, 0.1), mul=0.5, add=0.5)
        self.harms = global_harms_base + (self.lfo * global_harms_range)
        self.osc = Blit(freq=self.freq, harms=self.harms, mul=self.amp * 0.1)
        self.v_rate = filt_base_rate * random.uniform(0.99, 1.01)
        self.f_lfo = LFO(freq=self.v_rate, type=1, mul=2200, add=400)
        self.filt_obj = MoogLP(self.osc, freq=self.f_lfo, res=0.7, mul=2.5)
        self.is_moving_gate = Sig(0)
        self.moving_port = Port(self.is_moving_gate, risetime=0.02, falltime=0.25)
        self.sig_source = (self.osc * (1 - self.moving_port)) + (self.filt_obj * self.moving_port)
        self.pan_x = Sig(0.5); self.pan_y = Sig(0.5)
        self.ch_tl = (self.sig_source * (1 - self.pan_x) * (1 - self.pan_y) * master_gain)
        self.ch_tr = (self.sig_source * self.pan_x * (1 - self.pan_y) * master_gain)
        self.ch_bl = (self.sig_source * (1 - self.pan_x) * self.pan_y * master_gain)
        self.ch_br = (self.sig_source * self.pan_x * self.pan_y * master_gain)
        self.dly_tl = Delay(self.ch_tl * self.moving_port, delay=dly_time_sig, feedback=dly_feed)
        self.dly_tr = Delay(self.ch_tr * self.moving_port, delay=dly_time_sig, feedback=dly_feed)
        self.dly_bl = Delay(self.ch_bl * self.moving_port, delay=dly_time_sig, feedback=dly_feed)
        self.dly_br = Delay(self.ch_br * self.moving_port, delay=dly_time_sig, feedback=dly_feed)
        # Channel assignment: auto-fold to 2 channels when num_channels == 2
        self.rev_tl = Freeverb(self.ch_tl + self.dly_tl, size=0.8, damp=0.5, bal=rev_port, mul=comp_port).out(0)
        self.rev_tr = Freeverb(self.ch_tr + self.dly_tr, size=0.8, damp=0.5, bal=rev_port, mul=comp_port).out(1)
        self.rev_bl = Freeverb(self.ch_bl + self.dly_bl, size=0.8, damp=0.5, bal=rev_port, mul=comp_port).out(2 % num_channels)
        self.rev_br = Freeverb(self.ch_br + self.dly_br, size=0.8, damp=0.5, bal=rev_port, mul=comp_port).out(3 % num_channels)

    def update(self, x, y, pitch, effect_active):
        self.freq.value = midiToHz(pitch)
        self.pan_x.value = x / 7.0; self.pan_y.value = y / 7.0
        self.gate.value = 1
        self.is_moving_gate.value = 1 if (effect_active and (filt_idx > 0 or dly_idx > 0)) else 0

voice_pool = [GridVoice(i) for i in range(MAX_VOICES)]

print("--- Audio Engine Started ---")
print("\n***************************************************")
print("    >>> PRESS [ESC] AT ANY TIME TO EXIT <<<")
print("***************************************************\n")

# --- Initialize Global Keyboard Manager SAFELY ---
# (Done AFTER audio boots to prevent termios from crashing CoreAudio)
kb_mgr = KeyboardManager()

# --- 5. Helpers ---
def get_pitch(x, y):
    root = 48
    scale = SCALES_DICT[SCALE_NAMES[sel_scale_idx]]
    degree = x + ((7 - y) * 2)
    octave = degree // len(scale)
    return root + scale[int(degree % len(scale))] + (octave * 12)

def set_top_led(idx, r, g, b):
    if EMULATE_MODE: return
    if mode in ["Mk2", "Pro", "ProMk3"]:
        lp.LedCtrlRaw(TOP_BTNS[idx], r, g, b)
    else:
        lp.LedCtrlRaw(TOP_BTNS[idx], 3 if r > 0 else 0, 3 if g > 0 else 0)

def update_leds():
    global last_led_state
    if EMULATE_MODE: return  # Skip LED updates in emulation mode
    curr = set()
    if setup_mode:
        if sel_pos_idx == 0:
            for y in range(8): curr.add((0, y)); curr.add((1, y))
        elif sel_pos_idx == 1:
            for y in range(8): curr.add((6, y)); curr.add((7, y))
        elif sel_pos_idx == 2:
            for x in range(8): curr.add((x, 0)); curr.add((x, 1))
        elif sel_pos_idx == 3:
            for x in range(8): curr.add((x, 6)); curr.add((x, 7))
        color = (0, 15, 63) if mode in ["Mk2", "Pro", "ProMk3"] else (0, 3)
    else:
        with lock:
            for c in cells: curr.add((c['x'], c['y']))
        color = COLOR_MAP.get(SCALE_NAMES[sel_scale_idx], (63, 63, 0))

    for (x, y) in (last_led_state - curr):
        if mode in ["Mk2", "Pro", "ProMk3"]:
            lp.LedCtrlRaw(11 + x + (7 - y) * 10, 0, 0, 0)
        else:
            lp.LedCtrlXY(x, y, 0, 0)
    for (x, y) in (curr - last_led_state):
        if mode in ["Mk2", "Pro", "ProMk3"]:
            lp.LedCtrlRaw(11 + x + (7 - y) * 10, *color)
        else:
            lp.LedCtrlXY(x, y, *color)
    last_led_state = curr

    if setup_mode:
        set_top_led(0, 0, 63, 0); set_top_led(1, 0, 63, 0)
        set_top_led(2, 63, 63, 0); set_top_led(3, 63, 63, 0)
        if mode in ["Mk2", "Pro", "ProMk3"]:
            lp.LedCtrlRaw(SIDE_START_BTN, 63, 0, 0)
        else:
            lp.LedCtrlRaw(SIDE_START_BTN, 3, 0)
    else:
        for i in range(4): set_top_led(i, 0, 0, 0)
        if mode in ["Mk2", "Pro", "ProMk3"]:
            lp.LedCtrlRaw(SIDE_START_BTN, 0, 63, 0)
        else:
            lp.LedCtrlRaw(SIDE_START_BTN, 0, 3)

    vol = user_vol.value
    if vol < 0.4:
        v_col = (0, 63, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (0, 3)
    elif vol >= 0.7:
        v_col = (63, 0, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 0)
    else:
        v_col = (63, 35, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 2)
    set_top_led(6, *v_col); set_top_led(7, *v_col)

    # Power Button Color matching test_speakers.py
    if mode in ["Mk2", "Pro", "ProMk3"]:
        try:
            lp.LedCtrlRaw(SIDE_POWER_BTN, 10, 10, 63)
        except:
            lp.LedCtrlRaw(SIDE_POWER_BTN, 10, 10)
    else:
        lp.LedCtrlRaw(SIDE_POWER_BTN, 1, 3)

    if filt_idx == 0:
        f_col = (0, 0, 0)
    elif filt_idx == 1:
        f_col = (0, 63, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (0, 3)
    else:
        f_col = (63, 35, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 2)
    if mode in ["Mk2", "Pro", "ProMk3"]:
        lp.LedCtrlRaw(SIDE_FILT_BTN, *f_col)
    else:
        lp.LedCtrlRaw(SIDE_FILT_BTN, f_col[0], f_col[1])

    if dly_idx == 0:
        d_col = (0, 0, 0)
    elif dly_idx == 1:
        d_col = (0, 63, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (0, 3)
    else:
        d_col = (63, 35, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 2)
    if mode in ["Mk2", "Pro", "ProMk3"]:
        lp.LedCtrlRaw(SIDE_DLY_BTN, *d_col)
    else:
        lp.LedCtrlRaw(SIDE_DLY_BTN, d_col[0], d_col[1])

    curr_rev = rev_levels[rev_idx]
    if curr_rev == 0.0:
        r_col = (0, 0, 0)
    elif curr_rev == 0.3:
        r_col = (0, 63, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (0, 3)
    elif curr_rev == 0.5:
        r_col = (63, 35, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 2)
    else:
        r_col = (63, 0, 0) if mode in ["Mk2", "Pro", "ProMk3"] else (3, 0)
    if mode in ["Mk2", "Pro", "ProMk3"]:
        lp.LedCtrlRaw(SIDE_REV_BTN, *r_col)
    else:
        lp.LedCtrlRaw(SIDE_REV_BTN, r_col[0], r_col[1])

# --- 6. Sequence (AUDIO LOGIC PRESERVED) ---
def main_loop():
    global running, setup_mode, cells
    while running and setup_mode:
        update_leds(); time.sleep(0.1)

    if not running: return

    if sel_pos_idx == 0: cells = [{'x': x, 'y': y} for x in range(2) for y in range(8)]
    elif sel_pos_idx == 1: cells = [{'x': x, 'y': y} for x in range(6, 8) for y in range(8)]
    elif sel_pos_idx == 2: cells = [{'x': x, 'y': y} for y in range(2) for x in range(8)]
    else: cells = [{'x': x, 'y': y} for y in range(6, 8) for x in range(8)]

    print(f"| GENESIS | Scale: {SCALE_NAMES[sel_scale_idx]} | Origin: {POS_NAMES[sel_pos_idx]} |")

    SCHUMANN_TICK = 0.128
    steps = 160
    print(">>> FADING IN: Initializing voice harmonics and volume ramp...")
    for i in range(steps):
        if not running: break
        p = i / steps
        fade_vol.value = p
        global_harms_base.value = 1 + (4 * p)
        with lock:
            for idx, c in enumerate(cells):
                if idx < MAX_VOICES: voice_pool[idx].update(c['x'], c['y'], get_pitch(c['x'], c['y']), False)
        update_leds(); time.sleep(SCHUMANN_TICK)

    start_time = time.time()
    print(">>> STEADY STATE: Cellular movement and entropy active (4-minute cycle).")
    while running and (time.time() - start_time < 240):
        global_harms_range.value = 40 * ((time.time() - start_time) / 240)
        with lock:
            effect_voice_idx = random.randint(0, min(len(cells), MAX_VOICES) - 1)
            for idx, c in enumerate(cells):
                moved = False
                if random.random() < 0.05:
                    c['x'] = max(0, min(7, c['x'] + random.choice([-1, 0, 1])))
                    c['y'] = max(0, min(7, c['y'] + random.choice([-1, 0, 1])))
                    moved = True
                if idx < MAX_VOICES:
                    voice_pool[idx].update(c['x'], c['y'], get_pitch(c['x'], c['y']), (moved and idx == effect_voice_idx))
        update_leds(); time.sleep(SCHUMANN_TICK)

    print(">>> FADING OUT: Reducing harmonic complexity and master gain.")
    curr_range = global_harms_range.value
    for i in range(steps):
        if not running: break
        inv_p = 1.0 - (i / steps)
        fade_vol.value = inv_p
        global_harms_base.value = 1 + (4 * inv_p)
        global_harms_range.value = curr_range * inv_p
        update_leds(); time.sleep(SCHUMANN_TICK)
    running = False

# --- 7. Input Handling (Unified Keyboard + Hardware) ---
def handle_button(bid, state):
    """Process a single button event. Called from input_listener."""
    global running, setup_mode, sel_scale_idx, sel_pos_idx, rev_idx, filt_idx, dly_idx
    if state <= 0:
        return  # Only process press events

    # Exit / Power Off
    if bid == SIDE_POWER_BTN:
        print("[SYSTEM] KILL SWITCH TRIGGERED: Shutting down safely.")
        running = False

    # Filter Toggle
    if bid == SIDE_FILT_BTN:
        filt_idx = (filt_idx + 1) % 3
        filt_base_rate.value = filt_rates[filt_idx]
        print(f"[FX] SCHUMANN FILTER MODE: {filt_idx} (Rate: {filt_rates[filt_idx]}Hz)")
        update_leds()

    # Delay Toggle
    if bid == SIDE_DLY_BTN:
        dly_idx = (dly_idx + 1) % 3
        dly_time_sig.value = dly_times[dly_idx]
        print(f"[FX] TEMPORAL DELAY MODE: {dly_idx} (Time: {dly_times[dly_idx]}s)")
        update_leds()

    # Reverb Toggle
    if bid == SIDE_REV_BTN:
        rev_idx = (rev_idx + 1) % len(rev_levels)
        global_rev_bal.value = rev_levels[rev_idx]
        global_rev_comp.value = rev_gains[rev_idx]
        print(f"[FX] REVERB MIX: {rev_levels[rev_idx]} | GAIN COMP: {rev_gains[rev_idx]}x")
        update_leds()

    # Start Sequence
    if setup_mode and bid == SIDE_START_BTN:
        print("[SYSTEM] Setup locked. Commencing sequence.")
        setup_mode = False
        update_leds()

    # Scale & Position Selection (setup mode only)
    if setup_mode and bid in TOP_BTNS:
        idx = TOP_BTNS.index(bid)
        if idx == 0: sel_scale_idx = (sel_scale_idx - 1) % len(SCALE_NAMES)
        elif idx == 1: sel_scale_idx = (sel_scale_idx + 1) % len(SCALE_NAMES)
        elif idx == 2: sel_pos_idx = (sel_pos_idx - 1) % 4
        elif idx == 3: sel_pos_idx = (sel_pos_idx + 1) % 4
        if setup_mode:
            print(f"[SETUP] Selection: {SCALE_NAMES[sel_scale_idx]} | Start Pos: {POS_NAMES[sel_pos_idx]}")
        update_leds()

    # Volume Control (available in all modes)
    is_vol_down = bid == TOP_BTNS[6]
    is_vol_up = bid == TOP_BTNS[7]
    if is_vol_down:
        user_vol.value = max(0, user_vol.value - 0.1)
        print(f"[AUDIO] Master Volume Decreased: {round(user_vol.value, 1)}")
        update_leds()
    elif is_vol_up:
        user_vol.value = min(1.0, user_vol.value + 0.1)
        print(f"[AUDIO] Master Volume Increased: {round(user_vol.value, 1)}")
        update_leds()

def input_listener():
    """Unified input listener: keyboard (ESC + emulation) and hardware Launchpad."""
    global running
    while running:
        # Cross-platform keyboard input (ESC + emulation keys)
        key = kb_mgr.get_key()
        if key == '\x1b':  # ESC key (Clean standalone press)
            print("\n--- System: ESC (Escape) Pressed. Exiting... ---")
            running = False
            break

        if EMULATE_MODE:
            events = lp.process_key(key)
            for bid, state in events:
                handle_button(bid, state)
        else:
            # Hardware Launchpad: poll events via ButtonStateRaw
            ev = lp.ButtonStateRaw()
            if ev:
                handle_button(ev[0], ev[1])

        time.sleep(0.01)

# --- 8. Launch Threads ---
t_logic = threading.Thread(target=main_loop, daemon=True)
t_input = threading.Thread(target=input_listener, daemon=True)
t_logic.start()
t_input.start()

try:
    while running: time.sleep(0.5)
except KeyboardInterrupt:
    running = False
finally:
    running = False
    # Give daemon threads time to notice running=False and exit cleanly
    time.sleep(0.3)
    s.stop()
    time.sleep(0.1)
    if lp:
        if isinstance(lp, LaunchpadMido):
            lp.close()
        elif not EMULATE_MODE:
            lp.Reset()
            lp.Close()
    if 'kb_mgr' in locals():
        kb_mgr.close()
    print("--- Goodbye ---")
    os._exit(0)