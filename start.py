#!/usr/bin/env python3
"""
Resonating With You — Script Launcher
======================================
Launch any of the quadraphonic generative audio scripts.
After a script finishes, the menu reappears. Press ESC or 0 to exit.
"""

import os
import sys
import subprocess

SCRIPTS = [
    ("beings_field2.py",     "Living Beings Field"),
    ("entropic_field2.py",   "Entropic Field — Generative Audio"),
    ("formalized_m2.py",     "Formalized Music — Stochastic Audio"),
    ("gen_field2.py",        "Generative Field — Walker Audio"),
    ("psychoa_test2.py",     "Psychoacoustic Tests"),
    ("stochastic_field2.py", "Stochastic Field — Rhythmic Cells"),
    ("synth_harms2.py",      "Quadraphonic Harmonic Synth"),
    ("chnn_scan2.py",        "ChNN Sonic Image — Image Sonifier"),
    ("test_speakers2.py",    "4-Channel Audio & Grid Test"),
]

# Resolve script directory (same folder as start.py)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Auto-detect virtual environment Python interpreter
# (no need to "source activate" — we just use the venv's python directly)
def find_venv_python():
    """Find the Python interpreter inside .venv (macOS/Linux + Windows)."""
    venv_dir = os.path.join(SCRIPT_DIR, '.venv')
    if not os.path.isdir(venv_dir):
        return sys.executable  # No venv found, use system Python

    # Windows: .venv\Scripts\python.exe
    win_python = os.path.join(venv_dir, 'Scripts', 'python.exe')
    if os.path.isfile(win_python):
        return win_python

    # macOS/Linux: .venv/bin/python
    unix_python = os.path.join(venv_dir, 'bin', 'python')
    if os.path.isfile(unix_python):
        return unix_python

    return sys.executable  # Fallback

VENV_PYTHON = find_venv_python()
if VENV_PYTHON != sys.executable:
    print(f"  Using venv: {VENV_PYTHON}")

HEADER = """
╔══════════════════════════════════════════════════╗
║         Resonating With You                      ║
║         Quadraphonic Audio Suite                  ║
╚══════════════════════════════════════════════════╝
"""

def print_menu():
    print(HEADER)
    for i, (_, name) in enumerate(SCRIPTS, 1):
        print(f"  {i}. {name}")
    print(f"\n  0. Exit")
    print(f"  ─────────────────────────────────────────")

def get_choice():
    """Cross-platform single-key input with ESC support."""
    try:
        # Try Windows first
        import msvcrt
        while True:
            print("\n  Select [1-9] or [0/ESC] to exit: ", end='', flush=True)
            while True:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch == b'\x1b':  # ESC
                        print("ESC")
                        return None
                    try:
                        val = int(ch.decode('utf-8', 'ignore'))
                        print(str(val))
                        return val
                    except (ValueError, UnicodeDecodeError):
                        pass
    except ImportError:
        # macOS / Linux: use simple input() — ESC handled as fallback
        while True:
            try:
                raw = input("\n  Select [1-9] or [0/ESC] to exit: ").strip()
                if not raw or raw == '\x1b':
                    return None
                val = int(raw)
                return val
            except (ValueError, EOFError, KeyboardInterrupt):
                return None

def run_script(filename, extra_args=None):
    """Run a script as a subprocess, forwarding all CLI arguments."""
    script_path = os.path.join(SCRIPT_DIR, filename)
    if not os.path.isfile(script_path):
        print(f"\n  [ERROR] Script not found: {script_path}")
        return

    cmd = [VENV_PYTHON, script_path]
    if extra_args:
        cmd.extend(extra_args)

    print(f"\n  Launching: {filename}")
    print(f"  {'─' * 48}\n")

    try:
        subprocess.run(cmd, cwd=SCRIPT_DIR)
    except KeyboardInterrupt:
        pass

    print(f"\n  {'─' * 48}")
    print(f"  Script finished: {filename}")

def main():
    # Collect any extra args (like -d 5, -c 4, -e) to forward to scripts
    extra_args = sys.argv[1:]

    while True:
        print_menu()
        choice = get_choice()

        if choice is None or choice == 0:
            print("\n  Goodbye.\n")
            break

        if 1 <= choice <= len(SCRIPTS):
            filename, name = SCRIPTS[choice - 1]
            run_script(filename, extra_args)
        else:
            print(f"\n  Invalid choice: {choice}")

if __name__ == "__main__":
    main()