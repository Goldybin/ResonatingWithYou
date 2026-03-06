import sys
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
Generative Field (Walker Logic)
============================================================
- Top Buttons 0-3: Momentary Channel Solo (Sine Wave, Red on press)
- Top Button 4: Delay Multi-State (Cycle Off/Low/Mid/High, Green/Amber/Red)
- Top Button 5: Reverb Multi-State (Cycle Off/Low/Mid/High, Green/Amber/Red)
- Top Buttons 6-7: Main Volume (Amber 60%, Red at Peak)

- Side Buttons 0-3: Toggle Algorithmic Walkers (Markov, Brownian, Fractal, Genetic)
- Side Buttons 4-6: Speed Selectors (Half, Normal, Double Schumann Speed)
- Side Button 7: EXIT / POWER OFF (Blue/Cyan on Mk2, 2-sec Fade Out on press)

============================================================
- Universal Launchpad Support (Mk1, Mk2, Pro, MK3 Pro)
- Auto detection 2 or 4 channel sounds
- Cross-platform Keyboard Emulation (Windows & macOS)
- Global ESC key to exit with ANSI-sequence filtering
- Auto Programmer Mode entry for MK3 Pro (via Mido/RtMidi)
"""

# --- CLI Arguments (Extended from test_speakers.py) ---
parser = argparse.ArgumentParser(description="Generative Field - 4-Channel Walker Audio")
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
        print(" SOLO CHANNELS (Momentary Hold):")
        print(" [q] - Solo Ch 0              [w] - Solo Ch 1")
        print(" [e] - Solo Ch 2              [r] - Solo Ch 3")
        print("")
        print(" FX & VOLUME:")
        print(" [t] - Delay Toggle           [y] - Reverb Toggle")
        print(" [-] - Vol Down               [+] - Vol Up")
        print("")
        print(" WALKER TOGGLES (Side Buttons):")
        print(" [a] - Walker 0 (Markov)      [s] - Walker 1 (Brownian)")
        print(" [d] - Walker 2 (Fractal)     [f] - Walker 3 (Genetic)")
        print("")
        print(" SPEED SELECTORS:")
        print(" [z] - Half Speed   [x] - Normal Speed   [c] - Double Speed")
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

        # Top button controls (Mk1 raw IDs)
        ctrl_map = {
            'q': 200, 'w': 201, 'e': 202, 'r': 203,   # Solo Ch 0-3 (SOLO_BTNS)
            't': 204,                                    # Delay Toggle (DELAY_BTN)
            'y': 205,                                    # Reverb Toggle (REVERB_BTN)
            '-': 206, '+': 207, '=': 207,               # Vol Down / Up (VOL_BTNS)
        }
        # Side button controls (Mk1 raw IDs)
        side_map = {
            'a': 8,     # Walker 0: Markov (SIDE_BTNS[0])
            's': 24,    # Walker 1: Brownian (SIDE_BTNS[1])
            'd': 40,    # Walker 2: Fractal (SIDE_BTNS[2])
            'f': 56,    # Walker 3: Genetic (SIDE_BTNS[3])
            'z': 72,    # Speed: Half (SIDE_BTNS[4])
            'x': 88,    # Speed: Normal (SIDE_BTNS[5])
            'c': 104,   # Speed: Double (SIDE_BTNS[6])
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
print(" Generative Field - Walker Audio")
print("====================================================================================")
print("This script creates walker logic to navigate a stochastic soundscape, where four ")
print("independent algorithmic agents move across an 8x8 grid to trigger and spatialize sound.")
print("====================================================================================")
print("- Top Buttons 0-3: Momentary Channel Solo (Sine Wave, Red on press)")
print("- Top Button 4: Delay Multi-State (Cycle Off/Low/Mid/High, Green/Amber/Red)")
print("- Top Button 5: Reverb Multi-State (Cycle Off/Low/Mid/High, Green/Amber/Red)")
print("- Top Buttons 6-7: Main Volume (Amber 60%, Red at Peak)")
print("- Side Buttons 0-3: Toggle Algorithmic Walkers (Markov, Brownian, Fractal, Genetic)")
print("- Side Buttons 4-6: Speed Selectors (Half, Normal, Double Schumann Speed)")
print("- Side Button 7: EXIT / POWER OFF (Blue/Cyan on Mk2, 2-sec Fade Out on press)")

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
    DELAY_BTN = 204
    REVERB_BTN = 205
    VOL_BTNS = [206, 207]
    SIDE_BTNS = [8, 24, 40, 56, 72, 88, 104]
    EXIT_PWR_BTN = 120
elif mode == "Mk2":
    SOLO_BTNS = [104, 105, 106, 107]
    DELAY_BTN = 108
    REVERB_BTN = 109
    VOL_BTNS = [110, 111]
    SIDE_BTNS = [89, 79, 69, 59, 49, 39, 29]
    EXIT_PWR_BTN = 19
elif mode in ["Pro", "ProMk3"]:
    SOLO_BTNS = [91, 92, 93, 94]
    DELAY_BTN = 95
    REVERB_BTN = 96
    VOL_BTNS = [97, 98]
    SIDE_BTNS = [89, 79, 69, 59, 49, 39, 29]
    EXIT_PWR_BTN = 19

# --- 2. Audio Server Configuration ---
s = Server(sr=48000, nchnls=num_channels, duplex=0, buffersize=BUFFER_SIZE, winhost=AUDIO_HOST)
if AUDIO_DEVICE != -1:
    s.setOutputDevice(AUDIO_DEVICE)
s.deactivateMidi()
s.boot().start()

# --- 3. Audio Engine & Synthesis Blocks (HEAVY GAIN STAGING) ---
sustain_mod = Sig(0.1)
master_vol = Sig(0.6)
master_vol_port = Port(master_vol, 4.0, 4.0)

# Generator Multipliers: Increased for saturated presence
fm_f = Sig(440); markov_v = FM(carrier=fm_f, ratio=[0.5, 0.51], index=10, mul=0.6)
br_f = Sig(220); brownian_v = MoogLP(LFO(freq=br_f, type=3, mul=0.7), freq=1200, res=0.5)
fr_f = Sig(880); fractal_v = Reson(PinkNoise(mul=0.15), freq=fr_f, q=10, mul=3.8)
ge_f = Sig(110); genetic_v = LFO(freq=ge_f, type=1, sharp=0.5, mul=0.6)

gens = [markov_v, brownian_v, fractal_v, genetic_v]
gen_gains = [[Sig(0) for _ in range(4)] for _ in range(4)]
gen_ports = [[Port(sig, 0.05, sustain_mod) for sig in row] for row in gen_gains]
# Solo sines: auto-fold to 2 channels when num_channels == 2
solo_sines = [Sine(freq=440, mul=0).out(i % num_channels) for i in range(4)]

delay_fb = Sig(0.4); delay_t = Sig(0.25); rev_size = Sig(0.4)

# --- 4. Quadrophonic Signal Matrix (Aggressive Mix) ---
for i in range(4):
    chan_mix = sum([gens[j] * gen_ports[j][i] for j in range(4)])
    chan_delay = Delay(chan_mix, delay=delay_t, feedback=delay_fb)
    chan_rev_wet = Freeverb(chan_mix + chan_delay, size=rev_size, damp=0.5, bal=1.0)

    # Mix Stage: Bumped to 0.75 Dry/Delay + 0.3 Reverb
    # This will push the Tanh harder for a thicker sound
    mix_stage = (chan_mix + chan_delay) * 0.75 + (chan_rev_wet * 0.3)
    final_sig = Tanh(mix_stage * master_vol_port)
    # Channel assignment: auto-fold to 2 channels when num_channels == 2
    final_sig.out(i % num_channels)

print("--- Audio Engine: High-Gain Logic Active (Saturated Mix) ---")
print("\n***************************************************")
print("    >>> PRESS [ESC] AT ANY TIME TO EXIT <<<")
print("***************************************************\n")

# --- Initialize Global Keyboard Manager SAFELY ---
# (Done AFTER audio boots to prevent termios from crashing CoreAudio)
kb_mgr = KeyboardManager()

# --- 5. Helper Functions ---
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

def update_vol_leds():
    v = master_vol.value
    print(f"--- System: Master Volume at {v:.2f} ---")
    v_col = (0, 3) if v < 0.4 else (3, 3) if v < 0.7 else (2, 0) if v < 0.9 else (3, 0)
    for btn in VOL_BTNS: lp_led_raw(btn, *v_col)

# --- 6. State Management ---
schumann_base = 7.83
current_speed = schumann_base
grid_occupancy = [0.0] * 64
walkers = [random.randint(0, 63) for _ in range(4)]
active_algos = [False] * 4
rev_level = 1; delay_mode = 1; is_fading = False

OTONAL_ROOT = 27.5
ALGO_NAMES = ["Markov", "Brownian", "Fractal", "Genetic"]
ALGO_COLS_BRIGHT = [(0, 3, 0), (3, 3, 0), (3, 0, 0), (0, 3, 3)]
ALGO_COLS_DIM = [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 1, 1)]

def full_reset_sequence():
    global grid_occupancy, active_algos, is_fading, walkers, rev_level, delay_mode
    is_fading = True
    print("--- SEQUENCE: CAPACITY REACHED. RESETTING SYSTEM ---")
    master_vol_port.value = 0
    time.sleep(4.1)
    for r in gen_gains:
        for s_sig in r: s_sig.value = 0
    grid_occupancy = [0.0] * 64; active_algos = [False] * 4
    walkers = [random.randint(0, 63) for _ in range(4)]
    rev_level = 1; delay_mode = 1; rev_size.value = 0.4; delay_fb.value = 0.4
    if not EMULATE_MODE:
        try:
            update_vol_leds()
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

    last_step = time.time()
    while True:
        # Cross-platform ESC exit check
        key = kb_mgr.get_key()
        if key == '\x1b':  # ESC key (Clean standalone press)
            print("\n--- System: ESC Pressed. Initiating 2s Fade Out and Shutdown ---")
            master_vol_port.value = 0
            time.sleep(2.0)
            break

        # Unified event handling: keyboard emulation or hardware Launchpad
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
                        active_algos[idx] = not active_algos[idx]
                        lp_led_raw(bid, *(ALGO_COLS_BRIGHT[idx] if active_algos[idx] else ALGO_COLS_DIM[idx]))
                        print(f"--- Walker: {ALGO_NAMES[idx]} {'Enabled' if active_algos[idx] else 'Disabled'} ---")
                    elif idx in [4, 5, 6]:
                        speeds = ["Half", "Normal", "Double"]
                        current_speed = [schumann_base / 2, schumann_base, schumann_base * 2][idx - 4]
                        print(f"--- Clock: Speed set to {speeds[idx - 4]} ({current_speed:.2f} Hz) ---")
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

        if not is_fading and time.time() - last_step > (1.0 / current_speed):
            curr_time = time.time()
            occ_count = sum(1 for x in grid_occupancy if x > 0)
            sustain_mod.value = 0.1 + (occ_count / 64.0) * 3.9

            if occ_count >= 64: threading.Thread(target=full_reset_sequence).start()

            for i in range(4):
                if active_algos[i]:
                    move = random.choice([-1, 1, -8, 8])
                    walkers[i] = (walkers[i] + move) % 64
                    grid_occupancy[walkers[i]] = curr_time
                    gx, gy = walkers[i] % 8, walkers[i] // 8
                    lp_led_grid(gx, gy, *ALGO_COLS_BRIGHT[i])

                    time_diff = curr_time - grid_occupancy[walkers[i]]
                    harmonic = 8 + gx + (gy * 8)

                    slope_comp = 1.0 if i == 2 else 1.0 / math.sqrt(harmonic / 8)
                    algo_amp = max(0.05, 1.0 - (time_diff * 0.2)) * slope_comp
                    [fm_f, br_f, fr_f, ge_f][i].value = OTONAL_ROOT * harmonic

                    g_vals = get_quad_gains(gx, gy + 1)
                    for ch in range(4): gen_gains[i][ch].value = g_vals[ch] * algo_amp

            last_step = time.time()
        time.sleep(0.002)

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
    print("--- System Offline ---")