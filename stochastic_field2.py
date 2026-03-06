import sys
import time, random, math, threading
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
Stochastic Field
=============================================================================================
This script script is a musical instrument that allows you to explore rhythm and 
its relationship with internal time; rhythmic pulses are generated when a cell from 
the grid is activated, they are pitched according to the root note and scale selected. 
Cells on the grid, with their relative positioning in a quadraphonic configuration, 
play until deactivaed a sequence chosen randomly.
=============================================================================================

- Top Button 0: Decrements global root note (C, C#, etc.)
- Top Button 1: Increments global root note
- Top Button 2: Cycles backward through the SCALES
- Top Button 3: Cycles forward through the SCALES
- Top Button 4: Reverb, cycles through Small Room, Medium Hall, and Large Hall
- Top Button 5: Displacement, active cells jump to empty one
- Top Button 6: Volume up
- Top Button 7: Volume down

- Side Button 0: Fades master out, clears all active agents, then restores volume
- Side Button 1: Delay, cycles delay timings: OFF -> 1/4 -> 1/8 -> 1/16
- Side Button 2: Chorus, cycles chorus settings: OFF -> SUBTLE -> MOD -> DEEP
- Side Button 3: Sound, change timbre (e.g., Glass Pluck, Bamboo FM)
- Side Button 4: Sound, change timbre (e.g., Crystal Tine, Digital Marimba)
- Side Button 5: Switch off, initiates a 4-second fade out and exits

- 8x8 Grid: Toggle action. Press to activate a Cell Agent; press again to deactivate
            X/Y position calculates gain across 4 output channels (Quadraphonic)
            Position determines octave offset, scale note, and playback frequency
            Dim color = Ready; Bright color = Triggering; Red = Scale Root

=============================================================================================
The left area of ​​the grid generates even rhythms, while the right area generates odd rhythms. 

LEFT (x < 4)                 RIGHT (x >= 4)
        "EVEN" Rhythms                 "ODD" Rhythms
      (Divisions: 1, 2, 4)           (Divisions: 1, 3, 5)
    +-----------------------+      +-----------------------+
    | Zone 12  |  Zone 13   |      | Zone 14  |  Zone 15   |
7   | (Fastest | (Fast)     |      | (Fastest | (Fast)     |
6   |  Center) |            |      |  Center) |            |
5   |          |            |      |          |            |
    +----------+------------+      +----------+------------+  <-- Row 5
4   | Zone 8   |  Zone 9    |      | Zone 10  |  Zone 11   |
3   | (Slow)   | (Slowest)  |      | (Slow)   | (Slowest)  |
    +----------+------------+      +----------+------------+  <-- Row 3
2   | Zone 4   |  Zone 5    |      | Zone 6   |  Zone 7    |
1   | (Fastest | (Fast)     |      | (Fastest | (Fast)     |
0   |  Center) |            |      |  Center) |            |
    |          |            |      |          |            |
    +----------+------------+      +----------+------------+
(Y)    0  1  2  3                4  5  6  7    (X)

* Horizontal Split (Rhythm Type):
  - Left (x < 4): Cells are marked as is_even = True. When activated, they choose a beat division of 1, 2, or 4.
  - Right (x >= 4): Cells are marked as is_even = False. They choose a beat division of 1, 3, or 5, creating triplets and quintuplets.

*  Quadrant Speed (speed_mult):
   - Within each 4x4 quadrant, the speed is calculated based on the distance from the center of that quadrant (coordinates 1.5, 1.5).
   - Center of 4x4: The speed_mult is highest (up to 4.0x), making the notes trigger very fast.
   - Corners of 4x4: The speed_mult is lowest (closer to 1.0x), resulting in a standard tempo.

=============================================================================================
The notes are arranged vertically, from top to bottom.

LEFT (x < 4)          RIGHT (x >= 4)
    +---------------------+---------------------+
    |                     |                     |
7   |       +1.5          |       +0.5          |
6   |      Octave         |      Octave         |
5   |                     |                     |
    +---------------------+---------------------+  <-- Row 5 boundary
4   |       +0.5          |       -0.5          |
3   |      Octave         |      Octave         |
    +---------------------+---------------------+  <-- Row 3 boundary
2   |                     |                     |
1   |       -1.0          |       -1.5          |
0   |      Octave         |      Octave         |
    |                     |                     |
    +---------------------+---------------------+
(Y)    0    1    2    3      4    5    6    7 (X)
```
* Key Distribution Details:
    - Top Section (Rows 5, 6, 7): Provides the highest pitches, with the left side being one full octave higher than the right.
    - Middle Section (Rows 3, 4): Provides a transition zone with a subtle one-octave difference (+0.5 vs -0.5) across the vertical split.
    - Bottom Section (Rows 0, 1, 2): Provides the bass registers, where the right side (-1.5) is the lowest point on the grid.
These offsets are multiplied by 12 and added to the scale degree and root note to determine the final frequency.

Finally, the timbre can be modified by adding effects or changing the instrument's performance.

============================================================
- Universal Launchpad Support (Mk1, Mk2, Pro, MK3 Pro)
- Auto detection 2 or 4 channel sounds
- Cross-platform Keyboard Emulation (Windows & macOS)
- 64-Key Full Grid Mapping
- Global ESC key to exit with ANSI-sequence filtering
- Auto Programmer Mode entry for MK3 Pro (via Mido/RtMidi)
"""

# --- CLI Arguments (Extended from test_speakers.py) ---
parser = argparse.ArgumentParser(description="Stochastic Field - Rhythmic Cell Instrument")
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
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)

# --- Virtual Launchpad Class (Emulation) ---
class VirtualLaunchpad:
    def __init__(self, emu_mode="Mk1"):
        self.mode = emu_mode
        self.key_states = {}
        print("\n" + "=" * 60)
        print(" EMULATION MODE STARTED (Keyboard Control)")
        print("")
        print(" TOP CONTROLS:")
        print(" [9] - Root Note Down         [0] - Root Note Up")
        print(" [o] - Scale Down             [p] - Scale Up")
        print(" [l] - Reverb Cycle           [;] - Migration Toggle")
        print(" [-] - Vol Down               [+] - Vol Up")
        print("")
        print(" SIDE CONTROLS:")
        print(" [Enter] - Panic Reset (fade + clear)")
        print(" [.] - Delay Cycle            [/] - Chorus Cycle")
        print(" ['] - Next Sound             [\\] - Prev Sound")
        print("")
        print(" 64-KEY GRID (Toggle Cells):")
        print(" Row 1 (Top)   :  1 2 3 4 5 6 7 8")
        print(" Row 2         :  q w e r t y u i")
        print(" Row 3         :  a s d f g h j k")
        print(" Row 4         :  z x c v b n m ,")
        print(" Row 5 (Shift) :  ! @ # $ % ^ & *")
        print(" Row 6 (Shift) :  Q W E R T Y U I")
        print(" Row 7 (Shift) :  A S D F G H J K")
        print(" Row 8 (Bottom):  Z X C V B N M <")
        print("=" * 60 + "\n")

    def close(self):
        pass  # Handled globally by KeyboardManager

    def set_led(self, bid, color): pass
    def set_led_rgb(self, bid, r, g, b): pass

    def process_key(self, char):
        if not char:
            for bid in list(self.key_states.keys()):
                if self.key_states[bid]:
                    self.key_states[bid] = False
                    return [(bid, 0)]
            return []

        # Top button controls (Mk1 raw IDs)
        ctrl_map = {
            '9': 200, '0': 201,       # Root Note Down / Up (TOP_BTNS[0], TOP_BTNS[1])
            'o': 202, 'p': 203,       # Scale Down / Up (TOP_BTNS[2], TOP_BTNS[3])
            'l': 204,                  # Reverb Cycle (TOP_BTNS[4])
            ';': 205,                  # Migration Toggle (TOP_BTNS[5])
            '-': 206, '+': 207, '=': 207,  # Vol Down / Up (VOL_BTNS)
        }
        # Side button controls (Mk1 raw IDs)
        side_map = {
            '\n': 8,    # Panic Reset (SIDE_BTNS[0])
            '\r': 8,    # Panic Reset (Windows Enter)
            '.': 24,    # Delay Cycle (SIDE_DELAY_BTN)
            '/': 40,    # Chorus Cycle (SIDE_CHORUS_BTN)
            "'": 72,    # Next Sound (SIDE_NEXT_SOUND)
            '\\': 88,   # Prev Sound (SIDE_PREV_SOUND)
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
            bid = y * 16 + x
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

    def set_led(self, bid, color_index):
        self.out_port.send(mido.Message('note_on', channel=0, note=bid, velocity=color_index))

    def set_led_rgb(self, bid, r, g, b):
        # Scale from Mk1/Mk2 style to SysEx range (0-127)
        r_val, g_val, b_val = min(127, int(r * 2)), min(127, int(g * 2)), min(127, int(b * 2))
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
            if color_index in [5, 72]: r = 3
            elif color_index in [21, 87]: g = 3
            elif color_index in [13, 62]: r, g = 3, 3
            self.lp.LedCtrlRaw(bid, r, g)
        else:
            try: self.lp.LedCtrlRawByCode(bid, color_index)
            except: pass

    def set_led_rgb(self, bid, r, g, b):
        if self.mode == "Mk1":
            self.lp.LedCtrlRaw(bid, min(3, int(r / 16)), min(3, int(g / 16)))
        else:
            try: self.lp.LedCtrlRaw(bid, min(127, int(r * 2)), min(127, int(g * 2)), min(127, int(b * 2)))
            except: pass

    def get_events(self):
        ev = self.lp.ButtonStateRaw()
        if ev: return [(ev[0], ev[1])]
        return []

    def close(self):
        self.lp.Reset()
        self.lp.Close()

print("\n" + "=" * 50)
print(" Stochastic Field - Rhythmic Cell Instrument")
print("=============================================================================================")
print("This script script is a musical instrument that allows you to explore rhythm and ")
print("its relationship with internal time; rhythmic pulses are generated when a cell from ")
print("the grid is activated, they are pitched according to the root note and scale selected. ")
print("Cells on the grid, with their relative positioning in a quadraphonic configuration, ")
print("play until deactivaed a sequence chosen randomly.")
print("=============================================================================================")
print("- Top Button 0: Decrements global root note (C, C#, etc.)")
print("- Top Button 1: Increments global root note")
print("- Top Button 2: Cycles backward through the SCALES")
print("- Top Button 3: Cycles forward through the SCALES")
print("- Top Button 4: Reverb, cycles through Small Room, Medium Hall, and Large Hall")
print("- Top Button 5: Displacement, active cells jump to empty one")
print("- Top Button 6: Volume up")
print("- Top Button 7: Volume down")
print("- Side Button 0: Fades master out, clears all active agents, then restores volume")
print("- Side Button 1: Delay, cycles delay timings: OFF -> 1/4 -> 1/8 -> 1/16")
print("- Side Button 2: Chorus, cycles chorus settings: OFF -> SUBTLE -> MOD -> DEEP")
print("- Side Button 3: Sound, change timbre (e.g., Glass Pluck, Bamboo FM)")
print("- Side Button 4: Sound, change timbre (e.g., Crystal Tine, Digital Marimba)")
print("- Side Button 5: Switch off, initiates a 4-second fade out and exits")
print("- 8x8 Grid: Toggle action. Press to activate a Cell Agent; press again to deactivate")
print("X/Y position calculates gain across 4 output channels (Quadraphonic)")
print("Position determines octave offset, scale note, and playback frequency")
print("Dim color = Ready; Bright color = Triggering; Red = Scale Root")
print("The left area of ​​the grid generates even rhythms, while the right area generates odd rhythms. ")

print("\n" + "=" * 50)
print(" COMMAND LINE ARGUMENTS:")
print(" '-e', '--emulate', Force Launchpad emulation mode ")
print(" '-c <2 or 4>', '--channels <2 or 4>', Force number of audio channels (2 or 4) ")
print(" '-d <id>', '--device <id>', Set audio output device ID ")

# --- Print Audio Devices Debug ---
print("\n" + "=" * 50)
print(" AVAILABLE AUDIO DEVICES:")
pa_list_devices()
print("=" * 50 + "\n")

# --- Audio Channel Auto-Detection (from test_speakers.py) ---
try:
    actual_dev_id = pa_get_default_output() if AUDIO_DEVICE == -1 else AUDIO_DEVICE
    max_chans = pa_get_output_max_channels(actual_dev_id)
    if max_chans == 0: max_chans = 2
except:
    actual_dev_id = AUDIO_DEVICE
    max_chans = 2

if args.channels:
    num_channels = args.channels
else:
    num_channels = 4 if max_chans >= 4 else 2

print(f"\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
print(f" FORCED AUDIO DEVICE: ID {actual_dev_id}")
print(f" TOTAL CHANNELS: {num_channels}")
print(f"<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<\n")

# --- 1. Find Launchpad Ports & Assign Mode ---
lp = None
mode = None
EMULATE_MODE = args.emulate

# 1. Try Mido for MK3 Pro First
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

# 2. Try launchpad_py for Older Models
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
    TOP_BTNS = [200, 201, 202, 203, 204, 205, 206, 207]
    SIDE_BTNS = [8, 24, 40, 56, 72, 88, 104, 120]
    SIDE_POWER_BTN = 104
    VOL_BTNS = [206, 207]
    SIDE_DELAY_BTN = 24
    SIDE_CHORUS_BTN = 40
    SIDE_NEXT_SOUND = 72; SIDE_PREV_SOUND = 88
elif mode == "Mk2":
    TOP_BTNS = [104, 105, 106, 107, 108, 109, 110, 111]
    SIDE_BTNS = [89, 79, 69, 59, 49, 39, 29, 19]
    SIDE_POWER_BTN = 29
    VOL_BTNS = [110, 111]
    SIDE_DELAY_BTN = 79
    SIDE_CHORUS_BTN = 69
    SIDE_NEXT_SOUND = 49; SIDE_PREV_SOUND = 39
elif mode in ["Pro", "ProMk3"]:
    TOP_BTNS = [91, 92, 93, 94, 95, 96, 97, 98]
    SIDE_BTNS = [89, 79, 69, 59, 49, 39, 29, 19]
    SIDE_POWER_BTN = 29
    VOL_BTNS = [97, 98]
    SIDE_DELAY_BTN = 79
    SIDE_CHORUS_BTN = 69
    SIDE_NEXT_SOUND = 49; SIDE_PREV_SOUND = 39

# --- 2. Audio Setup ---
s = Server(sr=48000, nchnls=num_channels, duplex=0, buffersize=BUFFER_SIZE, winhost=AUDIO_HOST)
if AUDIO_DEVICE != -1:
    s.setOutputDevice(AUDIO_DEVICE)
s.deactivateMidi()
s.boot().start()


# --- 3. Global State ---
running = True
is_fading_out = False
reverb_mode = 0
sound_profile_idx = 0
migration_active = False
last_migration_tick = 0
BPM = 120
BEAT_TIME = (60.0 / BPM) * 16.0

# FX State
delay_times = [0.0, 60.0/BPM, 30.0/BPM, 15.0/BPM]
delay_cycle_idx = 0
chorus_cycle_idx = 0
chorus_settings = [{"depth":0, "fb":0}, {"depth":1, "fb":0.1}, {"depth":3, "fb":0.3}, {"depth":5, "fb":0.5}]
fx_colors = [(0,0), (0,63), (63,63), (63,0)] # Off, Blue, Cyan, Red

# --- 4. Profiles & Scales ---
SOUND_PROFILES = [
    {"name": "V7.4 Pulse", "bell": (3.5, 12), "mid": (1.0, 1.5), "bass": (1.0, 0.8)},
    {"name": "Glass Pluck", "bell": (7.1, 5), "mid": (2.0, 1.2), "bass": (1.0, 0.5)},
    {"name": "Digital Marimba", "bell": (1.618, 2), "mid": (1.0, 0.5), "bass": (0.5, 1)},
    {"name": "Crystal Tine", "bell": (11.0, 8), "mid": (4.0, 2.0), "bass": (2.0, 1.0)},
    {"name": "Bamboo FM", "bell": (5.0, 1.5), "mid": (2.0, 0.8), "bass": (0.5, 2)},
    {"name": "Sine Perc", "bell": (1.0, 0.2), "mid": (1.0, 0.1), "bass": (1.0, 0.05)},
    {"name": "Bells in Rain", "bell": (13.5, 10), "mid": (2.1, 3), "bass": (1.0, 1.5)},
    {"name": "Woody FM", "bell": (2.12, 4), "mid": (1.5, 2.5), "bass": (0.7, 5)},
    {"name": "Tiny Prisms", "bell": (9.0, 15), "mid": (3.0, 4), "bass": (1.0, 2)}
]

SCALES_DICT = {
    "Chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    "Harmonic Series": [0, 3.86, 7.02, 9.69, 12, 14.04, 15.86, 17.51, 19.02, 20.41, 21.69, 22.88, 24],
    "Partch Otonality": [0, 2.04, 3.86, 4.98, 7.02, 8.84, 10.88, 12, 14.04, 15.86, 16.98, 19.02, 20.84, 22.88, 24, 26],
    "Partch Utonality": [0, 1.12, 3.16, 4.98, 7.02, 8.14, 9.96, 12, 13.12, 15.16, 16.98, 19.02, 20.14, 21.96, 24, 25.12],
    "Major": [0, 2, 4, 5, 7, 9, 11, 12, 14, 16, 17, 19, 21, 23, 24, 26],
    "Minor": [0, 2, 3, 5, 7, 8, 10, 12, 14, 15, 17, 19, 20, 22, 24, 26],
}
SCALE_NAMES = list(SCALES_DICT.keys())
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
target_scale_idx, root_note = 0, 0

COLOR_MAP_BRIGHT = {"Chromatic": (63,63) if mode=="Mk2" else (3,3), "Harmonic Series": (63,15) if mode=="Mk2" else (3,1), "Partch Otonality": (0,63) if mode=="Mk2" else (0,3), "Partch Utonality": (40,63) if mode=="Mk2" else (2,3), "Major": (63,40) if mode=="Mk2" else (3,2), "Minor": (20,20) if mode=="Mk2" else (1,1)}
COLOR_MAP_DIM = {k: (max(1, v[0]//6), max(1, v[1]//6)) for k, v in COLOR_MAP_BRIGHT.items()}
COLOR_ROOT_BRIGHT, COLOR_ROOT_DIM = ((63,0), (12,0)) if mode=="Mk2" else ((3,0), (1,0))

rev_inputs = [Sig(0) for _ in range(4)]
delays = [Delay(rev_inputs[i], delay=0.1, feedback=0.35, mul=0.5) for i in range(4)]
chorus_inputs = [delays[i] + (rev_inputs[i] * 0.5) for i in range(4)]
choruses = [Chorus(chorus_inputs[i], depth=0, feedback=0, bal=0.5) for i in range(4)]
# Channel assignment: auto-fold to 2 channels when num_channels == 2
reverbs = [Freeverb(choruses[i], size=0.2, damp=0.1, bal=1.0).out(i % num_channels) for i in range(4)]

master_fader = Fader(fadein=4.0, fadeout=4.0, dur=0, mul=0.6).play()
master_port = Port(master_fader, 0.1, 0.1)

print("--- Audio Engine Started ---")
print("\n***************************************************")
print("    >>> PRESS [ESC] AT ANY TIME TO EXIT <<<")
print("***************************************************\n")

# --- Initialize Global Keyboard Manager SAFELY ---
# (Done AFTER audio boots to prevent termios from crashing CoreAudio)
kb_mgr = KeyboardManager()

# --- 5. Helpers ---
def get_quadrant_info(x, y):
    if y < 3: octv = 1.5 if x < 4 else 0.5
    elif 3 <= y <= 4: octv = 0.5 if x < 4 else -0.5
    else: octv = -1.0 if x < 4 else -1.5
    speed = 1.0 + (3.0 * (1.0 - (math.sqrt((x%4 - 1.5)**2 + (y%4 - 1.5)**2) / 2.12)))
    return octv, (x < 4), speed, (x%4) + ((y%4)*4)

def lp_led_raw(bid, r, g):
    """LED control preserving the original 2-argument color interface (r, g)."""
    if EMULATE_MODE: return
    try:
        if mode in ["Mk2", "Pro", "ProMk3"]:
            lp.set_led_rgb(bid, int(r), int(g), 0)
        else:
            lp.set_led_rgb(bid, int(r), int(g), 0)
    except: pass

def lp_led_grid(x, y, r, g):
    bid = (7-y)*10+x+11 if mode in ["Mk2", "Pro", "ProMk3"] else y*16+x
    lp_led_raw(bid, r, g)

def get_xy_from_raw(bid):
    if mode == "Mk1":
        x, y = bid % 16, bid // 16
        if x < 8 and y < 8: return x, y
    else:
        r, c = bid // 10, bid % 10
        if 1 <= r <= 8 and 1 <= c <= 8: return c-1, 8 - r
    return None

def update_ui():
    for i in range(4):
        color = (0,20) if i%2==0 else (0,63)
        lp_led_raw(TOP_BTNS[i], color[0], color[1])

    if reverb_mode == 0: lp_led_raw(TOP_BTNS[4], 0, 63) if mode=="Mk2" else lp_led_raw(TOP_BTNS[4], 0, 3)
    elif reverb_mode == 1: lp_led_raw(TOP_BTNS[4], 63, 63) if mode=="Mk2" else lp_led_raw(TOP_BTNS[4], 3, 3)
    else: lp_led_raw(TOP_BTNS[4], 63, 0) if mode=="Mk2" else lp_led_raw(TOP_BTNS[4], 3, 0)

    lp_led_raw(TOP_BTNS[5], 63, 63) if migration_active else lp_led_raw(TOP_BTNS[5], 0, 0)

    vol = master_fader.mul
    v_col = (0,63) if vol < 0.4 else ((63,63) if vol < 0.7 else (30,0))
    for b in VOL_BTNS: lp_led_raw(b, v_col[0], v_col[1])

    # Side Button LEDs (Delay & Chorus)
    lp_led_raw(SIDE_DELAY_BTN, fx_colors[delay_cycle_idx][0], fx_colors[delay_cycle_idx][1])
    lp_led_raw(SIDE_CHORUS_BTN, fx_colors[chorus_cycle_idx][0], fx_colors[chorus_cycle_idx][1])

    lp_led_raw(SIDE_BTNS[0], 0, 63)
    # Modified Power Button Color to match synth_harms.py
    if mode == "Mk2":
        lp_led_raw(SIDE_POWER_BTN, 10, 10) # Using first two args for R, G as per lp_led_raw definition
        try: lp.set_led_rgb(SIDE_POWER_BTN, 10, 10, 63) # Direct call to include the Blue channel for MK2
        except: pass
    else:
        lp_led_raw(SIDE_POWER_BTN, 1, 3)

    lp_led_raw(SIDE_NEXT_SOUND, 0, 63); lp_led_raw(SIDE_PREV_SOUND, 0, 63)

def update_reverb_settings():
    for rv in reverbs:
        if reverb_mode == 0: rv.size = 0.2; rv.damp = 0.1
        elif reverb_mode == 1: rv.size = 0.6; rv.damp = 0.4
        else: rv.size = 0.95; rv.damp = 0.8
    modes = ["Small room", "Medium hall", "Large hall"]
    print(f"REVERB: {modes[reverb_mode]}")

# --- 6. Agent Logic ---
class CellAgent:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.active = False
        self.last_tick = 0
        self.assigned_prof_idx = 0
        self.assigned_scale_idx = 0
        self.assigned_root = 0
        self.current_div = 1
        self.env = Adsr(attack=0.005, decay=0.15, sustain=0, release=0.1, mul=0.4)
        self.mod_env = Adsr(attack=0.002, decay=0.1, sustain=0, release=0.05)
        self.car = None
        self.qid = (0 if x < 4 and y < 4 else (1 if x >= 4 and y < 4 else (2 if x < 4 and y >= 4 else 3)))
        self.octave_off, self.is_even, self.speed_mult, self.note_idx = get_quadrant_info(x, y)

    def activate(self, force_interval=None):
        self.active = True
        self.assigned_prof_idx = sound_profile_idx
        self.assigned_scale_idx = target_scale_idx
        self.assigned_root = root_note
        base_div = force_interval if force_interval else (random.choice([1,2,4]) if self.is_even else random.choice([1,3,5]))
        self.current_div = base_div
        self.interval = (BEAT_TIME / base_div) / self.speed_mult
        self.apply_tuning()
        self.refresh_led()

    def refresh_led(self):
        if not self.active: return
        s_name = SCALE_NAMES[self.assigned_scale_idx]
        is_root = (SCALES_DICT[s_name][self.note_idx % len(SCALES_DICT[s_name])] == 0)
        lp_led_grid(self.x, self.y, *(COLOR_ROOT_DIM if is_root else COLOR_MAP_DIM[s_name]))

    def apply_tuning(self, source="Manual"):
        scale_list = SCALES_DICT[SCALE_NAMES[self.assigned_scale_idx]]
        freq = 220 * (2**((scale_list[self.note_idx % len(scale_list)] + self.assigned_root + (self.octave_off * 12))/12.0))
        prof = SOUND_PROFILES[self.assigned_prof_idx]
        ratio, index = prof["bell"] if self.octave_off >= 1.0 else (prof["bass"] if self.octave_off <= -1.0 else prof["mid"])
        if self.car: self.car.stop()
        self.mod = Sine(freq=freq * ratio, mul=self.mod_env * index * freq)
        self.car = Sine(freq=freq + self.mod, mul=self.env)
        nx, ny = self.x/7.0, self.y/7.0
        gains = [(1-nx)*(1-ny), nx*(1-ny), (1-nx)*ny, nx*ny]
        # Channel assignment: auto-fold to 2 channels when num_channels == 2
        for i in range(4): (self.car * gains[i] * master_port).out(i % num_channels)
        rev_inputs[self.qid].value = self.car * 0.2 * master_port

    def deactivate(self):
        self.active = False
        rev_inputs[self.qid].value = 0
        if self.car: self.car.stop()
        lp_led_grid(self.x, self.y, 0, 0)

    def update(self, now):
        if not self.active: return
        if now - self.last_tick >= self.interval:
            self.last_tick = now
            self.env.play(); self.mod_env.play()
            s_name = SCALE_NAMES[self.assigned_scale_idx]
            is_root = (SCALES_DICT[s_name][self.note_idx % len(SCALES_DICT[s_name])] == 0)
            color_b = COLOR_ROOT_BRIGHT if is_root else COLOR_MAP_BRIGHT[s_name]
            lp_led_grid(self.x, self.y, color_b[0], color_b[1])
            threading.Timer(0.1, self.refresh_led).start()

agents = [CellAgent(x, y) for y in range(8) for x in range(8)]
last_scale_transition = 0

# --- 7. Main Loop ---
update_ui()
try:
    print("--- SERVER STARTED ---")
    while running:
        current_time = time.time()

        # Cross-platform ESC exit check
        key = kb_mgr.get_key()
        if key == '\x1b':  # ESC key
            print("\n--- System: ESC Pressed. Fading out... ---")
            is_fading_out = True; master_fader.stop()
            threading.Timer(4.1, lambda: globals().update(running=False)).start()

        # Unified event handling: keyboard emulation or hardware Launchpad
        if EMULATE_MODE:
            events = lp.process_key(key)
        else:
            events = lp.get_events()

        for bid_state in events:
            bid, state = bid_state[0], bid_state[1]
            if bid == SIDE_POWER_BTN and state > 0:
                print("FADING OUT..."); is_fading_out = True; master_fader.stop()
                threading.Timer(4.1, lambda: globals().update(running=False)).start()
            elif bid == SIDE_BTNS[0] and state > 0:
                print("PANIC RESET..."); master_fader.stop()
                threading.Timer(4.0, lambda: [a.deactivate() for a in agents] + [master_fader.play()]).start()
            elif bid == SIDE_DELAY_BTN and state > 0:
                delay_cycle_idx = (delay_cycle_idx + 1) % 4
                for d in delays:
                    d.delay = delay_times[delay_cycle_idx] if delay_times[delay_cycle_idx] > 0 else 0.001
                    d.mul = 0.5 if delay_times[delay_cycle_idx] > 0 else 0.0
                print(f"DELAY: {['OFF', '1/4', '1/8', '1/16'][delay_cycle_idx]}")
                update_ui()
            elif bid == SIDE_CHORUS_BTN and state > 0:
                chorus_cycle_idx = (chorus_cycle_idx + 1) % 4
                cfg = chorus_settings[chorus_cycle_idx]
                for c in choruses: c.depth = cfg["depth"]; c.feedback = cfg["fb"]
                print(f"CHORUS: {['OFF', 'SUBTLE', 'MOD', 'DEEP'][chorus_cycle_idx]}")
                update_ui()
            elif bid == TOP_BTNS[4] and state > 0:
                reverb_mode = (reverb_mode + 1) % 3; update_reverb_settings(); update_ui()
            elif bid == TOP_BTNS[5] and state > 0:
                migration_active = not migration_active; update_ui()
                print(f"MIGRATION: {'ON' if migration_active else 'OFF'}")
            elif bid in [SIDE_NEXT_SOUND, SIDE_PREV_SOUND] and state > 0:
                sound_profile_idx = (sound_profile_idx + (1 if bid == SIDE_NEXT_SOUND else -1)) % len(SOUND_PROFILES)
                print(f"TARGET SOUND: {SOUND_PROFILES[sound_profile_idx]['name']}")
            elif bid in VOL_BTNS and state > 0:
                change = 0.05 if bid == VOL_BTNS[1] else -0.05
                master_fader.mul = max(0, min(1, master_fader.mul + change))
                print(f"VOLUME: {int(master_fader.mul * 100)}%"); update_ui()
            elif bid in TOP_BTNS[0:4] and state > 0:
                if bid in TOP_BTNS[0:2]:
                    root_note += (1 if bid == TOP_BTNS[1] else -1)
                    print(f"ROOT: {NOTE_NAMES[root_note % 12]}")
                else:
                    target_scale_idx = (target_scale_idx + (1 if bid == TOP_BTNS[3] else -1)) % len(SCALE_NAMES)
                    print(f"SCALE: {SCALE_NAMES[target_scale_idx]}")
                update_ui()
            else:
                coords = get_xy_from_raw(bid)
                if coords and state > 0:
                    idx = coords[1]*8 + coords[0]
                    if not agents[idx].active: agents[idx].activate()
                    else: agents[idx].deactivate()

        # STAGGERED TRANSITION (RESTORED)
        outdated = [a for a in agents if a.active and (a.assigned_prof_idx != sound_profile_idx or a.assigned_scale_idx != target_scale_idx or a.assigned_root != root_note)]
        if outdated and current_time - last_scale_transition > 0.1:
            lucky = random.choice(outdated)
            lucky.assigned_prof_idx, lucky.assigned_scale_idx, lucky.assigned_root = sound_profile_idx, target_scale_idx, root_note
            lucky.apply_tuning(source="Transition")
            lucky.refresh_led()
            last_scale_transition = current_time

        if migration_active and current_time - last_migration_tick > (BEAT_TIME * 0.5):
            last_migration_tick = current_time
            active_ones = [a for a in agents if a.active]
            if active_ones:
                a = random.choice(active_ones)
                empty = [ag for ag in agents if not ag.active]
                if empty:
                    dest = random.choice(empty); div = a.current_div
                    print(f"[MIGRATION] Displacing from ({a.x},{a.y}) to ({dest.x},{dest.y})")
                    a.deactivate(); dest.activate(force_interval=div)

        for a in agents: a.update(current_time)
        time.sleep(0.002)
finally:
    running = False; s.stop()
    if lp:
        if isinstance(lp, (LaunchpadMido, LaunchpadPyWrapper)):
            lp.close()
        elif not EMULATE_MODE:
            lp.close()
    if 'kb_mgr' in locals():
        kb_mgr.close()
    print("--- System Offline ---")