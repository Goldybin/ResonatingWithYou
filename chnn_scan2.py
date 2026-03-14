import os
import sys
import time
import argparse
import wx
from PIL import Image
from pyo import *

"""
ChNN sonic image
================================================================
This script is a quadraphonic image-to-sound sonifier. It scans
a digital image pixel-by-pixel and shows the position on GUI, while
allowing to control the speed, reverb and compression for a better
listening experience.

================================================================
Auditory display: 
- Pitch depends on brightness (grayscale) which maps the frequency.
- Timbre depends on RGB values which controls the number of 
  harmonics in the waveform.
- Spatialization depends on pixel's Y-coordinate for front and rear 
  speakers, X-coordinate for left and right.

============================================================
- Auto detection 2 or 4 channel sounds
- Cross-platform support (macOS & Windows)
- Global ESC key to exit
"""

# --- CLI Arguments ---
parser = argparse.ArgumentParser(description="ChNN Sonic Image - Quadraphonic Image Sonifier")
parser.add_argument('-c', '--channels', type=int, choices=[2, 4], help='Force number of audio channels (2 or 4)')
parser.add_argument('-d', '--device', type=int, help='Set audio output device ID')
parser.add_argument('-f', '--file', type=str, help='Path to image file (jpg/png)')
args, _ = parser.parse_known_args()

AUDIO_DEVICE = 10 if sys.platform != 'darwin' else -1
if args.device is not None:
    AUDIO_DEVICE = args.device

AUDIO_HOST = 'coreaudio' if sys.platform == 'darwin' else 'asio'
BUFFER_SIZE = 512

# --- Print Audio Devices Debug ---
print("\n" + "=" * 50)
print(" ChNN Sonic Image - Quadraphonic Sonifier")
print("================================================================")
print("This script is a quadraphonic image-to-sound sonifier. It scans")
print("a digital image pixel-by-pixel and shows the position on GUI, while")
print("allowing to control the speed, reverb and compression for a better")
print("listening experience.")
print("================================================================")
print("Auditory display: ")
print("- Pitch depends on brightness (grayscale) which maps the frequency.")
print("- Timbre depends on RGB values which controls the number of ")
print("harmonics in the waveform.")
print("- Spatialization depends on pixel's Y-coordinate for front and rear ")
print("speakers, X-coordinate for left and right.")

print("\n" + "=" * 50)
print(" COMMAND LINE ARGUMENTS:")
print(" '-c <2 or 4>', '--channels <2 or 4>', Force number of audio channels (2 or 4) ")
print(" '-d <id>', '--device <id>', Set audio output device ID ")
print(" '-f <path>', '--file <path>', Path to image file (jpg/png) ")

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

# 1. File Path Configuration
path = './'
file = '201310 ChNN Barcelona by Paolo Fassoli_09_square'
target_file = path + file + '.jpg'

# Override with CLI argument if provided
if args.file:
    target_file = args.file

# 2. Server Setup
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

# 3. Image Processing
def load_image_data(img_path, size=(64, 64)):
    img = Image.open(img_path).convert('RGB')
    img_res = img.resize(size)
    pixels = list(img_res.getdata())
    img_display = img.resize((400, 400))
    return pixels, size[0], size[1], img_display

# If image file not found, open a file picker dialog
if not os.path.isfile(target_file):
    print(f"--- Image not found: {target_file} ---")
    print("--- Opening file picker... ---")
    _app = wx.App(False)
    dlg = wx.FileDialog(None, "Select an image file", wildcard="Image files (*.jpg;*.jpeg;*.png;*.bmp)|*.jpg;*.jpeg;*.png;*.bmp|All files (*.*)|*.*", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
    if dlg.ShowModal() == wx.ID_OK:
        target_file = dlg.GetPath()
        print(f"--- Selected: {target_file} ---")
    else:
        print("--- No file selected. Exiting. ---")
        sys.exit(1)
    dlg.Destroy()
    _app.Destroy()

pixel_data, width, height, display_img = load_image_data(target_file)
num_pixels = len(pixel_data)

# 4. Synth Engine
env = Adsr(attack=0.002, decay=0.03, sustain=0.1, release=0.01, dur=0.05)
freq_ctrl = Sig(440)
harm_ctrl = Sig(10)
wave = Blit(freq=[freq_ctrl, freq_ctrl*1.005], harms=harm_ctrl, mul=env).mix(1)

# 5. Effects (Reverb & Compress)
rev_mix = Sig(0.3)
reverb = Freeverb(wave, size=0.8, damp=0.5, bal=rev_mix)
comp_thresh, comp_ratio = Sig(-20), Sig(4)
comp = Compress(reverb, thresh=comp_thresh, ratio=comp_ratio, risetime=0.01, falltime=0.1)

# 6. Quad Routing & Level Control
db_val = Sig(6)
master_gain = DBToA(db_val)
pan_front, pan_rear = Sig(0.5), Sig(0.5)
pan_left, pan_right = Sig(0.5), Sig(0.5)

# Channel assignment: auto-fold to 2 channels when num_channels == 2
out_fl = (comp * pan_left * pan_front * master_gain).out(0)
out_fr = (comp * pan_right * pan_front * master_gain).out(1)
out_rl = (comp * pan_left * pan_rear * master_gain).out(2 % num_channels)
out_rr = (comp * pan_right * pan_rear * master_gain).out(3 % num_channels)

# 7. Visual Analysis
sc = Scope(comp)
sp = Spectrum(comp)

# 8. wxPython Interface with Compact Sliders
class SonifierFrame(wx.Frame):
    def __init__(self, parent, title, img_obj):
        super(SonifierFrame, self).__init__(parent, title=title, size=(420, 830))
        self.panel = wx.Panel(self)
        
        # Display Image
        wx_img = wx.Image(img_obj.width, img_obj.height)
        wx_img.SetData(img_obj.tobytes())
        self.bmp = wx.Bitmap(wx_img)
        self.canvas = wx.StaticBitmap(self.panel, -1, self.bmp, pos=(0, 0))
        self.cursor = wx.Panel(self.panel, size=(400//width, 400//height), pos=(-10, -10))
        self.cursor.SetBackgroundColour(wx.Colour(255, 255, 255))
        self.scanning = False
        
        # Start Button
        y_pos = 410
        self.start_btn = wx.Button(self.panel, label="START SCAN", pos=(10, y_pos), size=(185, 35))
        self.start_btn.Bind(wx.EVT_BUTTON, self.on_start)

        # Select Image Button
        self.select_btn = wx.Button(self.panel, label="SELECT IMAGE", pos=(205, y_pos), size=(185, 35))
        self.select_btn.Bind(wx.EVT_BUTTON, self.on_select_image)

        # Slider Helper Function for Thinness
        def create_thin_slider(label, val, mini, maxi, y):
            lbl = wx.StaticText(self.panel, label=label, pos=(15, y))
            lbl.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            # Height set to 20 for a thinner look
            slider = wx.Slider(self.panel, value=val, minValue=mini, maxValue=maxi, 
                               pos=(10, y+15), size=(380, 20), style=wx.SL_HORIZONTAL)
            return slider

        y_pos += 50
        self.vol_slider = create_thin_slider("Volume (dB)", 6, -60, 18, y_pos)
        self.vol_slider.Bind(wx.EVT_SLIDER, self.update_vol)
        
        y_pos += 45
        self.speed_slider = create_thin_slider("Scan Speed", 40, 5, 200, y_pos)
        self.speed_slider.Bind(wx.EVT_SLIDER, self.update_speed)
        
        y_pos += 45
        self.rev_slider = create_thin_slider("Reverb Mix", 30, 0, 100, y_pos)
        self.rev_slider.Bind(wx.EVT_SLIDER, self.update_rev)

        y_pos += 45
        self.thresh_slider = create_thin_slider("Comp Threshold (dB)", -20, -60, 0, y_pos)
        self.thresh_slider.Bind(wx.EVT_SLIDER, self.update_thresh)

        y_pos += 45
        self.ratio_slider = create_thin_slider("Comp Ratio", 4, 1, 20, y_pos)
        self.ratio_slider.Bind(wx.EVT_SLIDER, self.update_ratio)

        # ESC key binding to exit
        self.panel.Bind(wx.EVT_KEY_DOWN, self.on_key)
        self.panel.SetFocus()

        # Clean shutdown handler — stop audio BEFORE wx destroys windows
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def on_close(self, event):
        """Stop all audio before wx teardown to prevent CoreAudio crash."""
        self.stop_scan()
        # Delete GUI-bound Pyo objects (Scope/Spectrum) before server stops
        sc.stop(); sp.stop()
        s.stop()
        time.sleep(0.1)
        s.shutdown()
        print("--- System Shutdown: Goodbye ---")
        event.Skip()  # Let wx finish destroying the window

    def on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            print("\n--- System: ESC Pressed. Exiting... ---")
            self.stop_scan()
            self.Close()
        event.Skip()

    def on_start(self, e):
        if not self.scanning:
            self.scanning = True
            self.start_btn.SetLabel("STOP SCAN")
            count.reset()
            met.play()
        else:
            self.stop_scan()

    def stop_scan(self):
        met.stop()
        self.scanning = False
        self.start_btn.SetLabel("START SCAN")

    def scan_finished(self):
        """Called from update_params when scan reaches the end."""
        self.scanning = False
        self.start_btn.SetLabel("START SCAN")

    def on_select_image(self, e):
        global pixel_data, width, height, num_pixels, display_img
        self.stop_scan()
        dlg = wx.FileDialog(self, "Select an image file",
            wildcard="Image files (*.jpg;*.jpeg;*.png;*.bmp)|*.jpg;*.jpeg;*.png;*.bmp|All files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            print(f"--- Loading image: {path} ---")
            pixel_data, width, height, display_img = load_image_data(path)
            num_pixels = len(pixel_data)
            count.max = num_pixels
            # Update displayed image
            wx_img = wx.Image(display_img.width, display_img.height)
            wx_img.SetData(display_img.tobytes())
            self.canvas.SetBitmap(wx.Bitmap(wx_img))
            self.cursor.SetSize((400 // width, 400 // height))
            self.cursor.SetPosition((-10, -10))
        dlg.Destroy()

    def update_vol(self, e): db_val.value = self.vol_slider.GetValue()
    def update_speed(self, e): met.time = self.speed_slider.GetValue() / 1000.0
    def update_rev(self, e): rev_mix.value = self.rev_slider.GetValue() / 100.0
    def update_thresh(self, e): comp_thresh.value = self.thresh_slider.GetValue()
    def update_ratio(self, e): comp_ratio.value = self.ratio_slider.GetValue()
    def update_cursor(self, x, y):
        self.cursor.SetPosition((int((x/width)*400), int((y/height)*400)))

# 9. Logic
met = Metro(time=0.04)
count = Counter(met, min=0, max=num_pixels)

def update_params():
    idx = int(count.get())
    if idx < num_pixels - 1:
        r, g, b = pixel_data[idx]
        x_idx, y_idx = idx % width, idx // width
        f_gain = 1.0 - (y_idx / (height - 1)) if height > 1 else 1.0
        pan_front.value, pan_rear.value = f_gain, 1.0 - f_gain
        r_side = x_idx / (width - 1) if width > 1 else 0.5
        pan_right.value, pan_left.value = r_side, 1.0 - r_side
        gray = (0.299*r + 0.587*g + 0.114*b)
        freq_ctrl.value = midiToHz((gray / 255.0) * 127.0)
        total = r + g + b + 1
        harm_ctrl.value = max(1, (r/total)*45 + (g/total)*20 + (b/total)*5)
        env.mul = (gray / 255.0) * 0.2
        env.play()
        wx.CallAfter(frame.update_cursor, x_idx, y_idx)
    else:
        met.stop()
        wx.CallAfter(frame.scan_finished)

trig = TrigFunc(met, update_params)

# 10. Run
s.start()
app = wx.App(False)
frame = SonifierFrame(None, "Paolo Fassoli - Compact Quad Scan", display_img)
frame.Show()
app.MainLoop()