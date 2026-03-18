import sys, time, random, math, threading, argparse
import os
import numpy as np
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
Formalized music
==================================================================================
This script retraces the main stages of Iannis Xenakis's text, arranging the iconic 
sounds in conflict with each other in quadraphonic sound, as is predictable, according 
to game theory; the grid is occupied with known statistical models and algorithms.
==================================================================================
- Top Buttons 0-3: Momentary Channel Solo (Sine Wave, Red on press)
- Top Button 4: Delay Multi-State (Cycle Off/Low/Mid/High, Green/Amber/Red)
- Top Button 5: Reverb Multi-State (Cycle Off/Low/Mid/High, Green/Amber/Red)
- Top Buttons 6-7: Main Volume (Amber 60%, Red at Peak)

- Side Buttons 0-3: Toggle Stochastic Engines (Markov, Analog, GENDYN, Poisson)
- Side Buttons 4-6: Density Selectors (Half, Normal, Double Density)
- Side Button 7: EXIT / POWER OFF (Blue/Cyan, 2-sec Fade Out on press)

============================================================

- Universal Launchpad Support (Mk1, Mk2, Pro, MK3 Pro)
- Auto detection 2 or 4 channel sounds
- Cross-platform Keyboard Emulation (Windows & macOS)
- Global ESC key to exit with ANSI-sequence filtering
- Auto Programmer Mode entry for MK3 Pro (via Mido/RtMidi)
"""

# --- CLI Arguments (Extended from test_speakers.py) ---
parser = argparse.ArgumentParser(description="Formalized Music - 4-Channel Stochastic Audio")
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
        print(" FX & VOLUME:")
        print(" [t] - Delay Toggle           [y] - Reverb Toggle")
        print(" [-] - Vol Down               [+] - Vol Up")
        print("")
        print(" ENGINE TOGGLES (Side Buttons):")
        print(" [a] - Engine 0 (Markov)      [s] - Engine 1 (Analog)")
        print(" [d] - Engine 2 (GENDYN)      [f] - Engine 3 (Poisson)")
        print("")
        print(" DENSITY SELECTORS:")
        print(" [z] - Half Density   [x] - Normal Density   [c] - Double Density")
        print("=" * 60 + "\n")

    def close(self):
        pass  # Handled globally by KeyboardManager

    def set_led(self, bid, color_index):
        pass

    def set_led_rgb(self, bid, r, g, b):
        pass

    def reset_leds(self):
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
            'q': 200, 'w': 201, 'e': 202, 'r': 203,   # Solo Ch 0-3
            't': 204,                                    # Delay Toggle
            'y': 205,                                    # Reverb Toggle
            '-': 206, '+': 207, '=': 207,               # Vol Down / Up
        }
        # Side button controls (Mk1 raw IDs)
        side_map = {
            'a': 8,     # Engine 0: Markov
            's': 24,    # Engine 1: Analog
            'd': 40,    # Engine 2: GENDYN
            'f': 56,    # Engine 3: Poisson
            'z': 72,    # Density: Half
            'x': 88,    # Density: Normal
            'c': 104,   # Density: Double
        }

        if char in ctrl_map:
            bid = ctrl_map[char]
            self.key_states[bid] = True
            return [(bid, 127)]
        elif char in side_map:
            bid = side_map[char]
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

    def reset_leds(self):
        self.out_port.send(mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x03, 0x00, 0x00]))
        time.sleep(0.1)
        """Turn off only the 8x8 grid LEDs (IDs 11-18, 21-28, ... 81-88), leaving top/side buttons intact."""
        for row in range(1, 9):
            for col in range(1, 9):
                bid = row * 10 + col
                self.out_port.send(mido.Message('note_off', note=bid, velocity=0))
        time.sleep(0.05)

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

    def reset_leds(self):
        self.lp.Reset()

    def get_events(self):
        ev = self.lp.ButtonStateRaw()
        if ev: return [(ev[0], ev[1])]
        return []

    def close(self):
        self.lp.Reset()
        self.lp.Close()

print("\n" + "=" * 50)
print(" Formalized Music - Stochastic Audio")
print("==================================================================================")
print("This script retraces the main stages of Iannis Xenakis's text, arranging the iconic ")
print("sounds in conflict with each other in quadraphonic sound, as is predictable, according ")
print("to game theory; the grid is occupied with known statistical models and algorithms.")
print("==================================================================================")
print("- Top Buttons 0-3: Momentary Channel Solo (Sine Wave, Red on press)")
print("- Top Button 4: Delay Multi-State (Cycle Off/Low/Mid/High, Green/Amber/Red)")
print("- Top Button 5: Reverb Multi-State (Cycle Off/Low/Mid/High, Green/Amber/Red)")
print("- Top Buttons 6-7: Main Volume (Amber 60%, Red at Peak)")
print("- Side Buttons 0-3: Toggle Stochastic Engines (Markov, Analog, GENDYN, Poisson)")
print("- Side Buttons 4-6: Density Selectors (Half, Normal, Double Density)")
print("- Side Button 7: EXIT / POWER OFF (Blue/Cyan, 2-sec Fade Out on press)")

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
    VOL_BTNS = [206, 207]
    DELAY_BTN = 204
    REVERB_BTN = 205
    EXIT_PWR_BTN = 120
    SIDE_BTNS = [8, 24, 40, 56, 72, 88, 104]
elif mode == "Mk2":
    SOLO_BTNS = [104, 105, 106, 107]
    VOL_BTNS = [110, 111]
    DELAY_BTN = 108
    REVERB_BTN = 109
    EXIT_PWR_BTN = 19
    SIDE_BTNS = [89, 79, 69, 59, 49, 39, 29]
elif mode in ["Pro", "ProMk3"]:
    SOLO_BTNS = [91, 92, 93, 94]
    VOL_BTNS = [97, 98]
    DELAY_BTN = 95
    REVERB_BTN = 96
    EXIT_PWR_BTN = 19
    SIDE_BTNS = [89, 79, 69, 59, 49, 39, 29]

# --- 2. Audio Server Configuration ---
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

# --- 3. Xenakis Vector Synthesis (Recalibrated Red Engine) ---
sustain_mod = Sig(0.1)
master_vol = Sig(0.6)
master_vol_port = Port(master_vol, 4.0, 4.0)

# Sound Sources
vector_stochastic = Sig(440); logic_markov = Clip(FM(carrier=vector_stochastic, ratio=[0.5, 0.51], index=10, mul=0.6), min=-0.9, max=0.9)
vector_analogique = Sig(220); analogique_v = Clip(MoogLP(LFO(freq=vector_analogique, type=3, mul=0.7), freq=1200, res=0.5), min=-0.9, max=0.9)
vector_gendyn = Sig(880); gendyn_v = Clip(Reson(PinkNoise(mul=0.15), freq=vector_gendyn, q=10, mul=3.8), min=-0.9, max=0.9) 
vector_achorripsis = Sig(110); achorripsis_v = Clip(LFO(freq=vector_achorripsis, type=1, sharp=0.5, mul=0.6), min=-0.9, max=0.9)

xenakis_sets = [logic_markov, analogique_v, gendyn_v, achorripsis_v]

spatial_matrix = [[Sig(0) for _ in range(4)] for _ in range(4)]
spatial_ports = [[Port(sig, 0.05, sustain_mod) for sig in row] for row in spatial_matrix]

solo_sines = [Sine(freq=440, mul=0).out(i % num_channels) for i in range(4)]

delay_fb = Sig(0.4); delay_t = Sig(0.25); rev_size = Sig(0.4)

# --- 4. Quadrophonic Signal Matrix ---
for i in range(4):
    set_union = sum([xenakis_sets[j] * spatial_ports[j][i] for j in range(4)])
    chan_delay = Delay(set_union, delay=delay_t, feedback=delay_fb)
    chan_rev_wet = Freeverb(set_union + chan_delay, size=rev_size, damp=0.5, bal=1.0)

    # Mix Stage: Using 0.7 Dry/Delay + 0.25 Reverb for better balance
    mix_stage = (set_union + chan_delay) * 0.7 + (chan_rev_wet * 0.25)

    final_sig = Tanh(mix_stage * master_vol_port)
    final_sig.out(i % num_channels)

print("--- Audio Engine Started: Red Generator Calibrated for Balanced Mix ---")
print("\n***************************************************")
print("    >>> PRESS [ESC] AT ANY TIME TO EXIT <<<")
print("***************************************************\n")

# --- Initialize Global Keyboard Manager SAFELY ---
# (Done AFTER audio boots to prevent termios from crashing CoreAudio)
kb_mgr = KeyboardManager()

# --- 5. Formalized Music Helper Functions ---
STRATEGIC_PAYOFF = [[0.1, 0.5, 0.9], [0.4, 0.1, 0.2], [0.8, 0.3, 0.1]]
current_state_k = 1

def boolean_intersection(set_a, set_b):
    return (set_a % 8 == set_b % 8) or (set_a // 8 == set_b // 8)

def sieve_theory(n, modules):
    for m, shift in modules:
        if n % m == shift: return True
    return False

def quantize_to_sieve(root, index, modules):
    search_idx = int(index)
    for offset in range(32):
        if sieve_theory(search_idx + offset, modules): return root * (search_idx + offset)
        if sieve_theory(search_idx - offset, modules): return root * (search_idx - offset)
    return root * search_idx

def cauchy_dist(a):
    return a * math.tan(math.pi * (random.random() - 0.5))

def poisson_density(mu):
    l, k, p = math.exp(-mu), 0, 1
    while p > l: k += 1; p *= random.random()
    return k - 1

MARKOV_TRANSITION = [[0.1, 0.7, 0.2], [0.4, 0.2, 0.4], [0.2, 0.7, 0.1]]
def markov_step(state):
    r, cumulative = random.random(), 0
    for next_state, prob in enumerate(MARKOV_TRANSITION[state]):
        cumulative += prob
        if r <= cumulative: return next_state
    return state

def calculate_spatial_vector(x, y):
    nx, ny = x / 7.0, (y - 1) / 7.0
    return [(1.-nx)*(1.-ny), nx*(1.-ny), (1.-nx)*ny, nx*ny]

# --- LED Helper Functions (Adapted for unified Launchpad interface) ---
def lp_led_raw(bid, r, g, b=0):
    """LED control using unified interface. r,g,b in original 0-3 range."""
    if EMULATE_MODE: return
    if r > 0 and g == 0 and b == 0: lp.set_led(bid, 5)       # Red
    elif r == 0 and g > 0 and b == 0: lp.set_led(bid, 21)    # Green
    elif r > 0 and g > 0 and b == 0: lp.set_led(bid, 13)     # Yellow/Amber
    elif b > 0 and r == 0 and g == 0: lp.set_led(bid, 45)    # Blue
    elif r == 0 and g == 0 and b == 0: lp.set_led(bid, 0)    # Off
    else: lp.set_led_rgb(bid, r / 3.0, g / 3.0, b / 3.0)    # Custom RGB (normalize 0-3 to 0-1)

def lp_led_grid(x, y, r, g, b=0):
    if mode == "Mk1":
        bid = y * 16 + x
    else:
        bid = (8 - y) * 10 + x + 1
    lp_led_raw(bid, r, g, b)

def update_vol_leds():
    v = master_vol.value
    print(f"--- System: Master Volume at {v:.2f} ---")
    v_col = (0, 3) if v < 0.4 else (3, 3) if v < 0.7 else (2, 0) if v < 0.9 else (3, 0)
    for btn in VOL_BTNS: lp_led_raw(btn, *v_col)

# --- 6. Stochastic State Management ---
schumann_base = 7.83
stochastic_density = schumann_base
grid_occupancy = [0.0] * 64
glissandi_points = [random.randint(0, 63) for _ in range(4)]
active_stochastic_states = [False] * 4
rev_level = 1; delay_mode = 1; is_fading = False

OTONAL_ROOT = 27.5
ALGO_COLS_BRIGHT = [(0, 3, 0), (3, 3, 0), (3, 0, 0), (0, 3, 3)]
ALGO_COLS_DIM = [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 1, 1)]

def total_entropy_reset():
    global grid_occupancy, active_stochastic_states, is_fading, glissandi_points
    is_fading = True
    print("--- SEQUENCE: CAPACITY REACHED. RESETTING SYSTEM ---")
    master_vol_port.value = 0
    time.sleep(4.1)
    for r in spatial_matrix:
        for s_sig in r: s_sig.value = 0
    grid_occupancy = [0.0] * 64; active_stochastic_states = [False] * 4
    glissandi_points = [random.randint(0, 63) for _ in range(4)]
    if not EMULATE_MODE:
        try:
            lp.reset_leds(); update_vol_leds()
            for btn in SOLO_BTNS: lp_led_raw(btn, 0, 3)
            for i, b in enumerate(SIDE_BTNS):
                lp_led_raw(b, *(ALGO_COLS_DIM[i] if i < 4 else (3, 3) if i == 5 else (0, 1)))
            lp_led_raw(DELAY_BTN, 0, 3); lp_led_raw(REVERB_BTN, 0, 3)
            lp_led_raw(EXIT_PWR_BTN, 0, 0, 1)            
        except: pass
    master_vol_port.value = master_vol.value
    is_fading = False
    print("--- SEQUENCE: RESET COMPLETE ---")

# --- 7. Main Loop ---
try:
    print("--- Initialization: Setting Launchpad Default State ---")
    update_vol_leds()
    for btn in SOLO_BTNS: lp_led_raw(btn, 0, 3)
    for i, b in enumerate(SIDE_BTNS):
        lp_led_raw(b, *(ALGO_COLS_DIM[i] if i < 4 else (3, 3) if i == 5 else (0, 1)))
    lp_led_raw(DELAY_BTN, 0, 3); lp_led_raw(REVERB_BTN, 0, 3)
    lp_led_raw(EXIT_PWR_BTN, 0, 0, 1)

    last_event = time.time(); rhythm_sieve = 0
    while True:
        # Cross-platform ESC exit check + keyboard input
        key = kb_mgr.get_key()
        if key == '\x1b':  # ESC key (Clean standalone press)
            print("\n--- System: ESC (Escape) Pressed. Exiting... ---")
            break

        # Gather events: emulation keyboard or hardware Launchpad
        if EMULATE_MODE:
            events = lp.process_key(key)
        else:
            events = lp.get_events()

        for bid, state in events:
            if bid == EXIT_PWR_BTN and state > 0:
                print("--- System: Initiating 2s Fade Out and Shutdown ---")
                master_vol_port.value = 0
                time.sleep(2.0)
                raise KeyboardInterrupt

            if not is_fading:
                if bid in SOLO_BTNS:
                    idx = SOLO_BTNS.index(bid)
                    solo_sines[idx].mul = 0.25 if state > 0 else 0
                    lp_led_raw(bid, 3 if state > 0 else 0, 0)
                    if state > 0: print(f"--- Audio: Solo Channel {idx} Active ---")

                if bid in SIDE_BTNS and state > 0:
                    idx = SIDE_BTNS.index(bid)
                    if idx < 4:
                        active_stochastic_states[idx] = not active_stochastic_states[idx]
                        lp_led_raw(bid, *(ALGO_COLS_BRIGHT[idx] if active_stochastic_states[idx] else ALGO_COLS_DIM[idx]))
                        print(f"--- Engine: Engine {idx} {'Enabled' if active_stochastic_states[idx] else 'Disabled'} ---")
                    elif idx in [4, 5, 6]:
                        speeds = ["Half", "Normal", "Double"]
                        stochastic_density = [schumann_base / 2, schumann_base, schumann_base * 2][idx - 4]
                        print(f"--- Clock: Density set to {speeds[idx - 4]} ({stochastic_density:.2f} Hz) ---")
                        for i in range(4, 7): lp_led_raw(SIDE_BTNS[i], (3 if i - 4 == idx - 4 else 0), (idx - 4 + 1 if i - 4 == idx - 4 else 1))

                if bid == REVERB_BTN and state > 0:
                    rev_level = (rev_level + 1) % 4
                    rev_size.value = [0, 0.4, 0.6, 0.85][rev_level]
                    lp_led_raw(bid, *[(1, 1), (0, 3), (3, 3), (3, 0)][rev_level])
                    print(f"--- FX: Reverb Level {rev_level} (Size: {rev_size.value}) ---")

                if bid == DELAY_BTN and state > 0:
                    delay_mode = (delay_mode + 1) % 4
                    vals = [(0, 0, (1, 1)), (0.4, 0.25, (0, 3)), (0.6, 0.5, (3, 3)), (0.8, 0.125, (3, 0))]
                    delay_fb.value, delay_t.value = vals[delay_mode][0], vals[delay_mode][1]
                    lp_led_raw(bid, *vals[delay_mode][2])
                    print(f"--- FX: Delay Mode {delay_mode} (FB: {delay_fb.value}) ---")

                if bid in VOL_BTNS and state > 0:
                    master_vol.value = max(0.0, min(1.0, master_vol.value + (-0.05 if VOL_BTNS.index(bid) == 0 else 0.05)))
                    update_vol_leds()

        if not is_fading and time.time() - last_event > (1.0 / stochastic_density):
            rhythm_sieve += 1
            if sieve_theory(rhythm_sieve, [(3, 0), (4, 0)]):
                curr_t = time.time()
                occ_count = sum(1 for x in grid_occupancy if x > 0)
                sustain_mod.value = 0.1 + (occ_count / 64.0) * 3.9

                if occ_count >= 64: threading.Thread(target=total_entropy_reset).start()

                for i in range(4):
                    if active_stochastic_states[i]:
                        interact = boolean_intersection(glissandi_points[i], glissandi_points[(i + 1) % 4])
                        strategy_mod = STRATEGIC_PAYOFF[i % 3][random.randint(0, 2)] if interact else 1.0

                        glissandi_points[i] = (glissandi_points[i] + random.choice([-1, 1, -8, 8])) % 64
                        grid_occupancy[glissandi_points[i]] = curr_t
                        gx, gy = glissandi_points[i] % 8, glissandi_points[i] // 8
                        lp_led_grid(gx, gy, *ALGO_COLS_BRIGHT[i])

                        h_idx = (8 + gx + (gy * 8)) * strategy_mod
                        slope_comp = 1.0 if i == 2 else 1.0 / math.sqrt(h_idx / 8)
                        algo_amp = max(0.05, 1.0 - ((curr_t - grid_occupancy[glissandi_points[i]]) * 0.2)) * slope_comp

                        if i == 0: vector_stochastic.value = quantize_to_sieve(OTONAL_ROOT, h_idx, [(3, 0), (5, 0)])
                        elif i == 1:
                            current_state_k = markov_step(current_state_k)
                            vector_analogique.value = quantize_to_sieve(OTONAL_ROOT, [8, 25, 49][current_state_k] + (h_idx % 16), [(4, 0), (7, 1)])
                        elif i == 2:
                            raw_f = abs(vector_gendyn.value + cauchy_dist(100)) % 2000
                            vector_gendyn.value = quantize_to_sieve(OTONAL_ROOT, raw_f / OTONAL_ROOT, [(11, 0), (13, 0)])
                        elif i == 3: vector_achorripsis.value = OTONAL_ROOT * (h_idx + poisson_density(2))

                        g_vals = calculate_spatial_vector(gx, gy + 1)
                        for ch in range(4): spatial_matrix[i][ch].value = g_vals[ch] * algo_amp

            last_event = time.time()
        time.sleep(0.002)

except KeyboardInterrupt: pass
finally:
    s.stop(); s.shutdown()
    if lp:
        lp.close()
    if 'kb_mgr' in locals():
        kb_mgr.close()
    print("--- System Offline: All Formalized Processes Stopped ---")
    os._exit(0)