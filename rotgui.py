#!/usr/bin/env python3
import sys, os, time, threading, math

import board
from adafruit_seesaw.seesaw import Seesaw
from micropython import const

sys.path.insert(0, os.path.expanduser("~/cydk"))
import st7796

from PIL import Image, ImageDraw, ImageFont
from gpiozero import RotaryEncoder, Button, TonalBuzzer

# ── Gamepad button masks ──────────────────────────────────────────
BUTTON_A    = const(5)
BUTTON_B    = const(1)
BUTTON_X    = const(6)
BUTTON_Y    = const(2)
BUTTON_SEL  = const(0)
BUTTON_ST   = const(16)
BTN_MASK    = const(
    (1 << BUTTON_A) | (1 << BUTTON_B) |
    (1 << BUTTON_X) | (1 << BUTTON_Y) |
    (1 << BUTTON_SEL) | (1 << BUTTON_ST)
)

# ── Pins ──────────────────────────────────────────────────────────
ROT_CLK    = 5
ROT_DT     = 6
ROT_SW     = 13
BUZZER_PIN = 20   

# ── Display ───────────────────────────────────────────────────────
DISP_W, DISP_H = 480, 320

# ── Colors ────────────────────────────────────────────────────────
BG          = (10,  10,  15)
BG_BAR      = (17,  17,  24)
GREEN       = (0,   255, 136)
GREEN_DIM   = (0,   140, 80)
GREEN_FAINT = (0,   60,  35)
GRAY        = (110, 110, 110)
GRAY_DIM    = (60,  60,  60)

# ── Menu ──────────────────────────────────────────────────────────
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

# ── Smooth scroll settings ────────────────────────────────────────
# scroll_y tracks the VISUAL position of the highlight bar in item-units
# (0.0 = first item, 1.0 = second item, etc.)
# It lerps toward the integer target each frame.
LERP_SPEED = 0.90   # fraction of remaining distance per frame (0–1)
                    # increase for snappier, decrease for floatier

# ── Thread-safe input state ───────────────────────────────────────
class InputState:
    def __init__(self):
        self._lock   = threading.Lock()
        self._delta  = 0
        self._select = False

    def rotate(self, d):
        with self._lock:
            self._delta += d

    def select(self):
        with self._lock:
            self._select = True

    def consume(self):
        with self._lock:
            d, s = self._delta, self._select
            self._delta  = 0
            self._select = False
        return d, s


# ── Buzzer helpers ────────────────────────────────────────────────
def beep_scroll(bz):
    """Short blip — 80 Hz for 40 ms."""
    def _run():
        bz.play(80)
        time.sleep(0.04)
        bz.stop()
    threading.Thread(target=_run, daemon=True).start()

def beep_select(bz):
    """chirp: 440 Hz → 880 Hz."""
    def _run():
        bz.play(440)
        time.sleep(0.06)
        bz.stop()
    threading.Thread(target=_run, daemon=True).start()


# ── Drawing ───────────────────────────────────────────────────────
def lerp(a, b, t):
    return a + (b - a) * t

def ease_out(t):
    """Quadratic ease-out: fast start, gentle stop."""
    return 1 - (1 - t) * (1 - t)

def draw_frame(scroll_y: float, target: int) -> Image.Image:
    """
    scroll_y  — fractional item position of the highlight bar
    target    — integer index of the selected item (used for colors)
    """
    img = Image.new("RGB", (DISP_W, DISP_H), BG)
    d   = ImageDraw.Draw(img)

    # ── Top bar ───────────────────────────────────────────────────
    d.rectangle([0, 0, DISP_W, BAR_H], fill=BG_BAR)
    d.line([(0, BAR_H), (DISP_W, BAR_H)], fill=GREEN_FAINT, width=1)
    d.text((DISP_W - 52, 7), time.strftime("%H:%M"), font=f_small, fill=GREEN)
    d.text((PAD_L, BAR_H + 6), "// MENU", font=f_section, fill=GREEN_DIM)
    d.line([(0, MENU_TOP - 2), (DISP_W, MENU_TOP - 2)],
           fill=GREEN_FAINT, width=1)

    # ── Animated highlight bar ────────────────────────────────────
    # pixel Y of the bar top, driven by the fractional scroll_y
    bar_y = MENU_TOP + scroll_y * ITEM_H

    # glow rect (slightly taller to look like a raised slab)
    d.rounded_rectangle([0, bar_y, DISP_W, bar_y + ITEM_H - 1],15,outline=GREEN,fill=(BG[0]+18, BG[1]+40, BG[2]+25))
    #d.rectangle([0, bar_y, DISP_W, bar_y + ITEM_H - 1],fill=(BG[0]+18, BG[1]+40, BG[2]+25))
    
    # accent dot
    d.circle([460, bar_y+17, 3, bar_y + ITEM_H - 1],5, fill=GREEN)

    # ── Menu items (drawn at fixed integer positions) ─────────────
    for i, item in enumerate(MENU):
        y         = MENU_TOP + i * ITEM_H
        is_sel    = (i == target)
        # blend label brightness based on distance from scroll_y
        dist      = abs(scroll_y - i)
        t         = max(0.0, 1.0 - dist)          # 1 when selected, 0 when far
        fg_r      = int(lerp(GRAY[0], GREEN[0], t))
        fg_g      = int(lerp(GRAY[1], GREEN[1], t))
        fg_b      = int(lerp(GRAY[2], GREEN[2], t))
        sub_r     = int(lerp(GRAY_DIM[0], GREEN_DIM[0], t))
        sub_g     = int(lerp(GRAY_DIM[1], GREEN_DIM[1], t))
        sub_b     = int(lerp(GRAY_DIM[2], GREEN_DIM[2], t))

        indent = " " if is_sel else "  "
        d.text((PAD_L, y + 4),  f"{indent}{item['label']}",
               font=f_label, fill=(fg_r, fg_g, fg_b))
        if item.get("subtitle"):
            d.text((PAD_L, y + 21), item["subtitle"],
                   font=f_subtitle, fill=(sub_r, sub_g, sub_b))
        d.line([(0, y + ITEM_H), (DISP_W, y + ITEM_H)],
               fill=GREEN_FAINT, width=1)

    # ── Bottom nav bar ────────────────────────────────────────────
    nav_y = DISP_H - NAV_H
    d.line([(0, nav_y), (DISP_W, nav_y)], fill=GREEN_FAINT, width=1)
    d.rectangle([0, nav_y, DISP_W, DISP_H], fill=BG_BAR)
    #d.text((16,  nav_y + 4), "↑↓ rotate",  font=f_small, fill=GREEN_DIM)
    d.text((130, nav_y + 4), "A select",   font=f_small, fill=GREEN_DIM)
    d.text((220, nav_y + 4), "^C quit",    font=f_small, fill=GREEN_DIM)

    return img


# ── Main ──────────────────────────────────────────────────────────
def main():
    state = InputState()

    # Rotary encoder (gpiozero — same lib as st7796, no conflict)
    enc = RotaryEncoder(ROT_CLK, ROT_DT, max_steps=0, bounce_time=0.005)
    btn = Button(ROT_SW, pull_up=True, bounce_time=0.2)
    enc.when_rotated_clockwise         = lambda: state.rotate(+1)
    enc.when_rotated_counter_clockwise = lambda: state.rotate(-1)
    # encoder SW kept wired but unused for select now — still handy to keep

    # Buzzer
    bz = TonalBuzzer(BUZZER_PIN)

    # Gamepad
    i2c    = board.I2C()
    gp     = Seesaw(i2c, addr=0x50)
    gp.pin_mode_bulk(BTN_MASK, gp.INPUT_PULLUP)
    prev_btn_state = BTN_MASK   # all released (active-low pullup)

    print("Initialising display...")
    disp = st7796.st7796()
    disp.clear()
    print("Ready. Rotate to navigate, A to select. Ctrl-C to quit.")

    n        = len(MENU)
    target   = 0          # integer destination item
    scroll_y = 0.0        # fractional visual position (lerps toward target)
    interval = 1.0 / 30

    try:
        while True:
            t0 = time.time()

            # ── Encoder input ─────────────────────────────────────
            delta, _ = state.consume()
            if delta:
                new_target = (target + delta) % n
                if new_target != target:
                    target = new_target
                    beep_scroll(bz)

            # ── Gamepad A button (polled) ─────────────────────────
            btn_state = gp.digital_read_bulk(BTN_MASK)
            a_pressed_now  = not (btn_state  & (1 << BUTTON_A))
            a_pressed_prev = not (prev_btn_state & (1 << BUTTON_A))
            if a_pressed_now and not a_pressed_prev:   # rising edge
                print(f"Selected: {MENU[target]['label']}")
                beep_select(bz)
            prev_btn_state = btn_state

            # ── Smooth scroll (lerp scroll_y → target) ────────────
            diff = target - scroll_y
            if abs(diff) > 0.01:
                scroll_y += diff * LERP_SPEED
            else:
                scroll_y = float(target)   # snap when close enough

            # ── Draw & push ───────────────────────────────────────
            img = draw_frame(scroll_y, target)
            disp.show_image(img.transpose(Image.FLIP_LEFT_RIGHT))

            elapsed = time.time() - t0
            rem = interval - elapsed
            if rem > 0:
                time.sleep(rem)

    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        disp.clear()
        bz.stop()
        enc.close()
        btn.close()


if __name__ == "__main__":
    main()
