#!/usr/bin/env python3

import sys
import os
import time
import threading

# ── Waveshare driver ──────────────────────────────────────────────
DRIVER_PATH = os.path.expanduser("~/cydk")
sys.path.insert(0, DRIVER_PATH)
import st7796

from PIL import Image, ImageDraw, ImageFont
from gpiozero import RotaryEncoder, Button

# ── Rotary encoder pins (BCM) ─────────────────────────────────────
ROT_CLK = 5    # physical pin 29
ROT_DT  = 6    # physical pin 31
ROT_SW  = 13   # physical pin 33

# ── Display ───────────────────────────────────────────────────────
DISP_W = 480
DISP_H = 320

# ── Colors ────────────────────────────────────────────────────────
BG          = (0,  0,  0) #10,10,15
BG_BAR      = (17,  17,  24)
GREEN       = (0,   255, 136)
GREEN_DIM   = (0,   140, 80)
GREEN_FAINT = (0,   60,  35)
GRAY        = (110, 110, 110)
GRAY_DIM    = (60,  60,  60)

# ── Menu items ────────────────────────────────────────────────────
MENU = [
    {"label": "UTILS",    "subtitle": "   apps · tools"},
    {"label": "GAMES",    "subtitle": "   pygame"},
    {"label": "FILES",    "subtitle": "   /pihost/home"},
    {"label": "SETTINGS", "subtitle": "   sys config"},
    {"label": "NETWORK",  "subtitle": "   connections"},
    {"label": "SHUTDOWN", "subtitle": "   shutdown options"},
]

# ── Layout ────────────────────────────────────────────────────────
BAR_H    = 26
NAV_H    = 18
MENU_TOP = BAR_H + 24
ITEM_H   = 38
PAD_L    = 20

# ── Fonts ─────────────────────────────────────────────────────────
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
try:
    f_label    = ImageFont.truetype(BOLD, 14)
    f_subtitle = ImageFont.truetype(MONO,  9)
    f_small    = ImageFont.truetype(MONO,  9)
    f_section  = ImageFont.truetype(MONO, 11)
except Exception:
    f_label = f_subtitle = f_small = f_section = ImageFont.load_default()


# ── Input state (thread-safe) ─────────────────────────────────────
class InputState:
    def __init__(self):
        self._lock   = threading.Lock()
        self._delta  = 0      # accumulated scroll steps
        self._select = False  # button press pending

    def rotate(self, steps):
        with self._lock:
            self._delta += steps

    def press(self):
        with self._lock:
            self._select = True

    def consume(self):
        """Return (delta, select_pressed) and reset."""
        with self._lock:
            d, s = self._delta, self._select
            self._delta  = 0
            self._select = False
        return d, s


# ── Drawing ───────────────────────────────────────────────────────
def draw_frame(selected: int) -> Image.Image:
    img = Image.new("RGB", (DISP_W, DISP_H), BG)
    d   = ImageDraw.Draw(img)

    # Top bar
    d.rectangle([0, 0, DISP_W, BAR_H], fill=BG_BAR)
    d.line([(0, BAR_H), (DISP_W, BAR_H)], fill=GREEN_FAINT, width=1)
    d.text((DISP_W - 52, 7), time.strftime("%H:%M"), font=f_small, fill=GREEN)

    # Section label
    d.text((PAD_L, BAR_H + 6), "// MENU", font=f_section, fill=GREEN_DIM)
    d.line([(0, MENU_TOP - 2), (DISP_W, MENU_TOP - 2)], fill=GREEN_FAINT, width=1)

    # Menu items
    for i, item in enumerate(MENU):
        y = MENU_TOP + i * ITEM_H
        if i == selected:
            d.rectangle([0, y, DISP_W, y + ITEM_H - 1],
                        fill=(BG[0]+18, BG[1]+40, BG[2]+25))
            d.rectangle([0, y, 3, y + ITEM_H - 1], fill=GREEN)
            d.text((PAD_L, y + 4),  f" {item['label']}", font=f_label,    fill=GREEN)
            if item.get("subtitle"):
                d.text((PAD_L, y + 21), item["subtitle"], font=f_subtitle, fill=GREEN_DIM)
        else:
            d.text((PAD_L, y + 4),  f"  {item['label']}", font=f_label,    fill=GRAY)
            if item.get("subtitle"):
                d.text((PAD_L, y + 21), item["subtitle"],  font=f_subtitle, fill=GRAY_DIM)
        d.line([(0, y + ITEM_H), (DISP_W, y + ITEM_H)], fill=GREEN_FAINT, width=1)

    # Bottom nav bar
    nav_y = DISP_H - NAV_H
    d.line([(0, nav_y), (DISP_W, nav_y)], fill=GREEN_FAINT, width=1)
    d.rectangle([0, nav_y, DISP_W, DISP_H], fill=BG_BAR)
    d.text((16,  nav_y + 4), "↑↓ rotate",  font=f_small, fill=GREEN_DIM)
    d.text((130, nav_y + 4), "● select",   font=f_small, fill=GREEN_DIM)
    d.text((210, nav_y + 4), "^C quit",    font=f_small, fill=GREEN_DIM)

    return img


# Main ──────────────────────────────────────────────────────────

def main():
    state = InputState()

    # gpiozero RotaryEncoder: a=CLK, b=DT, max_steps=0 → unbounded
    # wrap=False since we handle wrapping ourselves
    enc = RotaryEncoder(ROT_CLK, ROT_DT, max_steps=0, bounce_time=0.005)
    btn = Button(ROT_SW, pull_up=True, bounce_time=0.2)

    # Callbacks fire in gpiozero's background thread — safe to update InputState
    
    #scroll direction 
    
    enc.when_rotated_clockwise        = lambda: state.rotate(-1)
    enc.when_rotated_counter_clockwise = lambda: state.rotate(+1)
    btn.when_pressed                  = lambda: state.press()

    print("Initialising display...")
    disp = st7796.st7796()
    disp.clear()
    print("Ready. Rotate to navigate, press to select. Ctrl-C to quit.")

    selected = 0
    n        = len(MENU)
    interval = 1.0 / 30

    try:
        while True:
            t0 = time.time()

            delta, pressed = state.consume()
            if delta:
                selected = (selected + delta) % n
            if pressed:
                print(f"Selected: {MENU[selected]['label']}")

            img = draw_frame(selected)
            disp.show_image(img.transpose(Image.FLIP_LEFT_RIGHT))

            elapsed = time.time() - t0
            rem = interval - elapsed
            if rem > 0:
                time.sleep(rem)

    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        disp.clear()
        enc.close()
        btn.close()


if __name__ == "__main__":
    main()
