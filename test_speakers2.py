import sys, time, argparse
from pyo import *
import mido

# --- Cross-Platform Keyboard Module ---
try:
    import msvcrt
    WINDOWS = True
except ImportError:
    import select, termios, tty
    WINDOWS = False

try:
    import launchpad_py as launchpad_old
    HAS_LAUNCHPAD_PY = True
except ImportError:
    HAS_LAUNCHPAD_PY = False

"""
============================================================
4-Channel Audio & Grid Test (Powered by Mido & RtMidi)
============================================================

- Universal Launchpad Support (Mk1, Mk2, Pro, MK3 Pro)
- Auto detection 2 or 4 channel sounds
- Cross-platform Keyboard Emulation (Windows & macOS)
- 64-Key Full Grid Mapping
- Global ESC key to exit with ANSI-sequence filtering

- Top Buttons 0-3: Momentary Channel Solo (Sine Wave, Red on press)
- Top Button 4: Toggles Auto-Scan (Pink Noise, Green/Red)
- Top Button 5: Toggles Manual Mode (Sine Wave, Green/Red)
- Top Buttons 6-7: Main Volume (Amber 60%)
- Side Button 6: EXIT / POWER OFF (Blue/Cyan)

============================================================
The soundstage is arranged in quadraphonic fashion, ideally 
using four identical speakers: 
Ch0 --> Spk1, Ch1 --> Spk2, Ch2 --> Spk3, Ch3 --> Spk4; 
interpolation takes place between cells, for intermediate values.
```
    1          FRONT Speakers             2     
     +-----------------------------------+ 
     |  (0,0)                     (7,0)  |
     |          <-------------->         |
     |      ^                       ^    |
     |      |                       |    |
     |      |        8x8 GRID       |    |
     |      |                       |    |
     |      v                       v    |
     |          <-------------->         |
     |  (0,7)                     (7,7)  |
     +-----------------------------------+  
    3          REAR speakers              4

============================================================
get_quad_gains(x, y)

       (0,0)  nx = x / 7.0  (1,0)
         TL ----------------- TR
          |        |          |
          |     (nx, ny)      |  ny = (y - 1) / 7.0
          |        |          |
         BL ----------------- BR
       (0,1)                (1,1)

============================================================
RAW MODE MK1
+---+---+---+---+---+---+---+---+ 
|200|201|202|203|204|205|206|207| < or 0..7 with LedCtrlAutomap()
+---+---+---+---+---+---+---+---+   

+---+---+---+---+---+---+---+---+  +---+
|  0|...|   |   |   |   |   |  7|  |  8|
+---+---+---+---+---+---+---+---+  +---+
| 16|...|   |   |   |   |   | 23|  | 24|
+---+---+---+---+---+---+---+---+  +---+
| 32|...|   |   |   |   |   | 39|  | 40|
+---+---+---+---+---+---+---+---+  +---+
| 48|...|   |   |   |   |   | 55|  | 56|
+---+---+---+---+---+---+---+---+  +---+
| 64|...|   |   |   |   |   | 71|  | 72|
+---+---+---+---+---+---+---+---+  +---+
| 80|...|   |   |   |   |   | 87|  | 88|
+---+---+---+---+---+---+---+---+  +---+
| 96|...|   |   |   |   |   |103|  |104|
+---+---+---+---+---+---+---+---+  +---+
|112|...|   |   |   |   |   |119|  |120|
+---+---+---+---+---+---+---+---+  +---+

============================================================
RAW MODE MK2
+---+---+---+---+---+---+---+---+ 
|104|   |106|   |   |   |   |111|
+---+---+---+---+---+---+---+---+ 

+---+---+---+---+---+---+---+---+  +---+
| 81|   |   |   |   |   |   |   |  | 89|
+---+---+---+---+---+---+---+---+  +---+
| 71|   |   |   |   |   |   |   |  | 79|
+---+---+---+---+---+---+---+---+  +---+
| 61|   |   |   |   |   | 67|   |  | 69|
+---+---+---+---+---+---+---+---+  +---+
| 51|   |   |   |   |   |   |   |  | 59|
+---+---+---+---+---+---+---+---+  +---+
| 41|   |   |   |   |   |   |   |  | 49|
+---+---+---+---+---+---+---+---+  +---+
| 31|   |   |   |   |   |   |   |  | 39|
+---+---+---+---+---+---+---+---+  +---+
| 21|   | 23|   |   |   |   |   |  | 29|
+---+---+---+---+---+---+---+---+  +---+
| 11|   |   |   |   |   |   |   |  | 19|
+---+---+---+---+---+---+---+---+  +---+

============================================================
X/Y MODE
  0   1   2   3   4   5   6   7      8   
+---+---+---+---+---+---+---+---+ 
|0/0|1/0|   |   |   |   |   |   |         0
+---+---+---+---+---+---+---+---+ 

+---+---+---+---+---+---+---+---+  +---+
|0/1|   |   |   |   |   |   |   |  |   |  1
+---+---+---+---+---+---+---+---+  +---+
|   |   |   |   |   |   |   |   |  |   |  2
+---+---+---+---+---+---+---+---+  +---+
|   |   |   |   |   |5/3|   |   |  |   |  3
+---+---+---+---+---+---+---+---+  +---+
|   |   |   |   |   |   |   |   |  |   |  4
+---+---+---+---+---+---+---+---+  +---+
|   |   |   |   |   |   |   |   |  |   |  5
+---+---+---+---+---+---+---+---+  +---+
|   |   |   |   |4/6|   |   |   |  |   |  6
+---+---+---+---+---+---+---+---+  +---+
|   |   |   |   |   |   |   |   |  |   |  7
+---+---+---+---+---+---+---+---+  +---+
|   |   |   |   |   |   |   |   |  |8/8|  8
+---+---+---+---+---+---+---+---+  +---+

============================================================

"""

# --- CLI Arguments ---
parser = argparse.ArgumentParser(description="4-Channel Audio & Grid Test")
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
                if char in (b'\x00', b'\xe0'): # Handle special keys
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
                        return char + seq # Return the full sequence (won't trigger ESC)
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
        print("\n" + "="*60)
        print(" EMULATION MODE STARTED (Keyboard Control)")
        print(" [9] - Auto-Scan (On/Off)    [0] - Manual Mode (On/Off)")
        print(" [-] - Vol Down              [=] - Vol Up")
        print("\n 64-KEY GRID MAPPING (For Manual Mode):")
        print(" Row 1 (Top)   :  1 2 3 4 5 6 7 8")
        print(" Row 2         :  q w e r t y u i")
        print(" Row 3         :  a s d f g h j k")
        print(" Row 4         :  z x c v b n m ,")
        print(" Row 5 (Shift) :  ! @ # $ % ^ & *")
        print(" Row 6 (Shift) :  Q W E R T Y U I")
        print(" Row 7 (Shift) :  A S D F G H J K")
        print(" Row 8 (Bottom):  Z X C V B N M <")
        print("="*60 + "\n")

    def close(self):
        pass # Handled globally by KeyboardManager
    
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
            
        ctrl_map = {'9': 204, '0': 205, '-': 206, '=': 207}
        grid_map = {
            '1':(0,0), '2':(1,0), '3':(2,0), '4':(3,0), '5':(4,0), '6':(5,0), '7':(6,0), '8':(7,0),
            'q':(0,1), 'w':(1,1), 'e':(2,1), 'r':(3,1), 't':(4,1), 'y':(5,1), 'u':(6,1), 'i':(7,1),
            'a':(0,2), 's':(1,2), 'd':(2,2), 'f':(3,2), 'g':(4,2), 'h':(5,2), 'j':(6,2), 'k':(7,2),
            'z':(0,3), 'x':(1,3), 'c':(2,3), 'v':(3,3), 'b':(4,3), 'n':(5,3), 'm':(6,3), ',':(7,3),
            '!':(0,4), '@':(1,4), '#':(2,4), '$':(3,4), '%':(4,4), '^':(5,4), '&':(6,4), '*':(7,4),
            'Q':(0,5), 'W':(1,5), 'E':(2,5), 'R':(3,5), 'T':(4,5), 'Y':(5,5), 'U':(6,5), 'I':(7,5),
            'A':(0,6), 'S':(1,6), 'D':(2,6), 'F':(3,6), 'G':(4,6), 'H':(5,6), 'J':(6,6), 'K':(7,6),
            'Z':(0,7), 'X':(1,7), 'C':(2,7), 'V':(3,7), 'B':(4,7), 'N':(5,7), 'M':(6,7), '<':(7,7)
        }
        
        if char in ctrl_map:
            bid = ctrl_map[char]
            self.key_states[bid] = True
            return [(bid, 127)]
        elif char in grid_map:
            x, y = grid_map[char]
            bid = y * 16 + x # Using Mk1 layout for internal emulation
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
        r_val, g_val, b_val = int(r * 127), int(g * 127), int(b * 127)
        self.out_port.send(mido.Message('sysex', data=[0x00, 0x20, 0x29, 0x02, 0x0E, 0x03, 0x03, bid, r_val, g_val, b_val]))

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
            if color_index in [5, 72]: r = 3     # Red
            elif color_index in [21, 87]: g = 3  # Green
            elif color_index in [13, 62]: r, g = 3, 3 # Yellow
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
            try: self.lp.LedCtrlRaw(bid, int(r*127), int(g*127), int(b*127))
            except: pass

    def get_events(self):
        ev = self.lp.ButtonStateRaw()
        if ev: return [(ev[0], ev[1])]
        return []

    def close(self):
        self.lp.Reset()
        self.lp.Close()

print("\n" + "="*50)
print(" 4-Channel Audio & Grid Test")
print("============================================================")
print("- Universal Launchpad Support (Mk1, Mk2, Pro, MK3 Pro)")
print("- Auto detection 2 or 4 channel sounds")
print("- Cross-platform Keyboard Emulation (Windows & macOS)")
print("- 64-Key Full Grid Mapping")
print("- Global ESC key to exit with ANSI-sequence filtering")
print("- Top Buttons 0-3: Momentary Channel Solo (Sine Wave, Red on press)")
print("- Top Button 4: Toggles Auto-Scan (Pink Noise, Green/Red)")
print("- Top Button 5: Toggles Manual Mode (Sine Wave, Green/Red)")
print("- Top Buttons 6-7: Main Volume (Amber 60%)")
print("- Side Button 6: EXIT / POWER OFF (Blue/Cyan)")

print("\n" + "="*50)
print(" COMMAND LINE ARGUMENTS:")
print(" '-e', '--emulate', Force Launchpad emulation mode ")
print(" '-c <2 or 4>', '--channels <2 or 4>', Force number of audio channels (2 or 4) ")
print(" '-d <id>', '--device <id>', Set audio output device ID ")

# --- Print Audio Devices Debug ---
print("\n" + "="*50)
print(" AVAILABLE AUDIO DEVICES:")
pa_list_devices()
print("="*50 + "\n")

# --- Audio Channel Auto-Detection ---
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

# --- Find Launchpad Ports & Assign Mode ---
lp = None
mode = None
EMULATE_MODE = args.emulate

# 1. Try Mido for MK3 Pro First
if not EMULATE_MODE:
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
        lp_check = launchpad_old.Launchpad()
        if lp_check.Check(0, "Mini"):
            lp_check.Open()
            lp = LaunchpadPyWrapper(lp_check, "Mk1")
            mode = "Mk1"
            print("--- System: Launchpad Mk1/S/Mini detected ---")
        elif lp_check.Check(0, "Mk2"):
            lp_check = launchpad_old.LaunchpadMk2()
            lp_check.Open()
            lp = LaunchpadPyWrapper(lp_check, "Mk2")
            mode = "Mk2"
            print("--- System: Launchpad Mk2 detected ---")
        elif lp_check.Check(0, "pro"):
            lp_check = launchpad_old.LaunchpadPro()
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
    TOP_BTNS = [200, 201, 202, 203] 
    SCAN_CTRL_BTNS = [204, 205] 
    VOL_BTNS = [206, 207] 
    SIDE_BTNS = [8, 24, 40, 56, 72, 88, 104, 120] 
    EXIT_PWR_BTN = 104
elif mode == "Mk2":
    TOP_BTNS = [104, 105, 106, 107] 
    SCAN_CTRL_BTNS = [108, 109] 
    VOL_BTNS = [110, 111] 
    SIDE_BTNS = [89, 79, 69, 59, 49, 39, 29, 19] 
    EXIT_PWR_BTN = 29
elif mode in ["Pro", "ProMk3"]:
    TOP_BTNS = [91, 92, 93, 94]
    SCAN_CTRL_BTNS = [95, 96]
    VOL_BTNS = [97, 98]
    SIDE_BTNS = [89, 79, 69, 59, 49, 39, 29, 19]
    EXIT_PWR_BTN = 29

# --- Audio Server ---
s = Server(sr=48000, nchnls=num_channels, duplex=0, buffersize=BUFFER_SIZE, winhost=AUDIO_HOST)
if AUDIO_DEVICE != -1:
    s.setOutputDevice(AUDIO_DEVICE)
s.deactivateMidi()
s.boot().start()

# --- Audio Engine ---
noise = PinkNoise(mul=0.2)
sine = Sine(freq=440, mul=0.2)

noise_gains = [Sig(0) for _ in range(4)]
noise_ports = [Port(sig, 0.05, 0.05) for sig in noise_gains]
sine_gains = [Sig(0) for _ in range(4)]
sine_ports = [Port(sig, 0.05, 0.05) for sig in sine_gains]

master_vol = Sig(0.6)
master_vol_port = Port(master_vol, 0.1, 0.1)

for i in range(4):
    out = ((noise * noise_ports[i]) + (sine * sine_ports[i])) * master_vol_port
    out.out(i % num_channels)

print("--- Audio Engine Started ---")
print("\n***************************************************")
print("    >>> PRESS [ESC] AT ANY TIME TO EXIT <<<")
print("***************************************************\n")

# --- Initialize Global Keyboard Manager SAFELY ---
# (Done AFTER audio boots to prevent termios from crashing CoreAudio)
kb_mgr = KeyboardManager()

# --- Helper Functions ---
def get_quad_gains(x, y):
    nx = x / 7.0
    ny = (y - 1) / 7.0
    return [(1.-nx)*(1.-ny), nx*(1.-ny), (1.-nx)*ny, nx*ny]

def lp_led_raw(bid, r, g, b=0):
    if EMULATE_MODE: return
    if r > 0 and g == 0 and b == 0: lp.set_led(bid, 5)     # Red
    elif r == 0 and g > 0 and b == 0: lp.set_led(bid, 21)  # Green
    elif r > 0 and g > 0 and b == 0: lp.set_led(bid, 13)   # Yellow
    elif b > 0 and r == 0 and g == 0: lp.set_led(bid, 45)  # Blue
    elif r == 0 and g == 0 and b == 0: lp.set_led(bid, 0)  # Off
    else: lp.set_led_rgb(bid, r, g, b)                     # Custom RGB

def get_xy_from_raw(bid):
    global mode
    if mode == "Mk1":
        x, y = bid % 16, bid // 16
        if x < 8 and y < 8: return x, y
    else:
        r, c = bid // 10, bid % 10
        if 1 <= r <= 8 and 1 <= c <= 8: return c - 1, 8 - r
    return None

def lp_led_grid(x, y, r, g, b=0):
    global mode
    if mode == "Mk1":
        bid = y * 16 + x
    else:
        bid = (8 - y) * 10 + x + 1
    lp_led_raw(bid, r, g, b)

def update_vol_leds():
    vol = master_vol.value
    if not EMULATE_MODE: print(f"--- Volume: {vol:.2f} ---")
    v_col = (0, 3) if vol < 0.4 else (3, 3) if vol < 0.7 else (2, 0) if vol < 0.9 else (3, 0)
    for btn in VOL_BTNS: lp_led_raw(btn, *v_col)

# --- State Management ---
scan_active = manual_active = False
pressed_top_btns = set()
pressed_grid_cells = set() 

for btn in TOP_BTNS: lp_led_raw(btn, 0, 3)
for btn in SCAN_CTRL_BTNS: lp_led_raw(btn, 0, 3)
update_vol_leds()
lp_led_raw(EXIT_PWR_BTN, 0, 0, 1) # Blue exit

# --- Main Loop ---
try:
    print("--- Starting Main Loop ---")
    step_interval = 4.0 / 64.0
    last_step_time = time.time()
    grid_idx = -1
    scan_gains = manual_gains = [0.0] * 4
    last_top_states = {btn: 0 for btn in SCAN_CTRL_BTNS}

    while True:
        current_time = time.time()
        
        # Cross-platform ESC exit check
        key = kb_mgr.get_key()
        if key == '\x1b': # ESC key (Clean standalone press)
            print("\n--- System: ESC (Escape) Pressed. Exiting... ---")
            raise KeyboardInterrupt
            
        if EMULATE_MODE:
            events = lp.process_key(key)
        else:
            events = lp.get_events()
            
        for bid, state in events:
            # Physical Launchpad Exit Button
            if bid == EXIT_PWR_BTN and state > 0: 
                print("\n--- System: Exit Triggered from Hardware ---")
                raise KeyboardInterrupt
            
            if bid in SCAN_CTRL_BTNS:
                idx = SCAN_CTRL_BTNS.index(bid)
                if state > 0 and last_top_states[bid] == 0:
                    if idx == 0:
                        scan_active = not scan_active
                        print(f"--- Auto-Scan: {scan_active} ---")
                        if not scan_active and grid_idx >= 0:
                            px, py = grid_idx % 8, grid_idx // 8
                            lp_led_grid(px, py, 0, 0)
                            grid_idx = -1
                    elif idx == 1:
                        manual_active = not manual_active
                        print(f"--- Manual Mode: {manual_active} ---")
                        if not manual_active:
                            for (gx, gy) in pressed_grid_cells: lp_led_grid(gx, gy, 0, 0)
                            pressed_grid_cells.clear()
                    for i, b in enumerate(SCAN_CTRL_BTNS):
                        act = scan_active if i == 0 else manual_active
                        lp_led_raw(b, *( (3, 0) if act else (0, 3) ))
                last_top_states[bid] = state

            elif bid in TOP_BTNS:
                idx = TOP_BTNS.index(bid)
                if state > 0:
                    print(f"--- Solo Button {idx} Pressed ---")
                    pressed_top_btns.add(bid); lp_led_raw(bid, 3, 0)
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
                        print(f"--- Grid Pressed: ({gx}, {gy}) ---")
                        pressed_grid_cells.add((gx, gy)); lp_led_grid(gx, gy, 0, 3)
                    else:
                        if (gx, gy) in pressed_grid_cells:
                            pressed_grid_cells.remove((gx, gy)); lp_led_grid(gx, gy, 0, 0)

        is_paused = len(pressed_top_btns) > 0
        if scan_active and not is_paused:
            if current_time - last_step_time >= step_interval:
                if grid_idx >= 0:
                    px, py = grid_idx % 8, grid_idx // 8
                    if (px, py) not in pressed_grid_cells: lp_led_grid(px, py, 0, 0)
                grid_idx = (grid_idx + 1) % 64
                sx, sy = grid_idx % 8, grid_idx // 8
                scan_gains = get_quad_gains(sx, sy + 1)
                lp_led_grid(sx, sy, 0, 3)
                last_step_time = current_time
        elif not scan_active or is_paused:
            scan_gains = [0.0] * 4
            if is_paused: last_step_time = current_time 

        manual_gains = [0.0] * 4
        if manual_active and pressed_grid_cells:
            for (mx, my) in pressed_grid_cells:
                gains = get_quad_gains(mx, my + 1)
                for i in range(4): manual_gains[i] = max(manual_gains[i], gains[i])

        for i in range(4):
            noise_gains[i].value = scan_gains[i]
            target_sine = manual_gains[i]
            if TOP_BTNS[i] in pressed_top_btns: target_sine = 1.0
            sine_gains[i].value = target_sine
            
        time.sleep(0.005)

except KeyboardInterrupt: pass
finally:
    s.stop()
    s.shutdown()
    if lp:
        lp.close()
    if 'kb_mgr' in locals():
        kb_mgr.close()
    print("--- Goodbye ---")