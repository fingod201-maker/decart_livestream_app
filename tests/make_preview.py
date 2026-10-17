"""Render a realistic app_preview.png under a virtual display (Xvfb).

Builds the real Tkinter app, loads the sample reference portrait, injects a
fake transformed frame into the preview, flips the UI into the 'connected'
state, then screen-grabs the window. Run with:

    xvfb-run -a python tests/make_preview.py
"""
import os
import sys
import time
import tkinter as tk
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as C
import app as A

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF = os.path.join(ROOT, "sample_images", "reference_portrait.png")
OUT = os.path.join(ROOT, "app_preview.png")


def main():
    root = tk.Tk()
    root.geometry("1280x860+0+0")
    application = A.DecartLivestreamApp(root)

    # Populate a realistic session.
    application.api_key_var.set("your_stripe_api_key_placeholder")
    application.reference_image_path = REF
    application._load_reference_thumbnail()
    application.prompt_text.delete("1.0", "end")
    application.prompt_text.insert(
        "1.0",
        "Substitute the character in the video with the young woman in the "
        "reference image, keep the studio lighting and soft gray background.",
    )

    # Fake transformed frame in the preview.
    frame = Image.open(REF).convert("RGB").resize((1088, 624))
    application._last_frame = frame
    application._set_state("connected")
    application._billing_seconds = 74
    application._draw_preview()

    # Seed the log with a realistic trace.
    application._log("Connected - streaming live")
    application._log("Model lucy-2.1 | native 1088x624 @ 30fps | input 1088x624 "
                     "| output 1080p | view desktop")
    application._log("Session id: sess_9f2c1a7b | subscribe token issued")

    for _ in range(30):
        root.update()
        time.sleep(0.02)

    import mss
    with mss.mss() as sct:
        monitor = {"left": 0, "top": 0, "width": 1280, "height": 860}
        shot = sct.grab(monitor)
        Image.frombytes("RGB", shot.size, shot.rgb).save(OUT)
    print("wrote", OUT)

    root.destroy()


if __name__ == "__main__":
    main()
