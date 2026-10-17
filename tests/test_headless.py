"""Headless smoke test: builds the GUI, exercises controls and the frame
pipeline under a virtual display (Xvfb). Not shipped as part of the app."""
import os
import sys
import time
import tkinter as tk
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as C
import app as A
from decart_engine import PictureGrabber, WebcamGrabber, _crop_box


def make_test_image(path, w=640, h=480):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x % 256, y % 256, (x + y) % 256)
    img.save(path)


def main():
    print("== GUI construction ==")
    root = tk.Tk()
    application = A.DecartLivestreamApp(root)
    for _ in range(5):
        root.update()
    print("GUI built OK; state =", application._state)

    print("== state transitions ==")
    for s in ["connecting", "connected", "generating", "reconnecting", "disconnected", "error"]:
        application._set_state(s)
        root.update()
    print("state transitions OK")

    print("== view toggle ==")
    application._set_view(C.VIEW_MOBILE)
    root.update()
    assert application.view_var.get() == C.VIEW_MOBILE
    application._set_view(C.VIEW_DESKTOP)
    root.update()
    assert application.view_var.get() == C.VIEW_DESKTOP
    print("view toggle OK")

    print("== config collection ==")
    application.api_key_var.set("test-key-123")
    cfg = application._build_session_config()
    assert cfg is not None and cfg.api_key == "test-key-123"
    assert cfg.resolution in C.RESOLUTIONS
    print("SessionConfig:", cfg.model_name, cfg.resolution, cfg.view_mode, cfg.source_type)

    print("== prompt templates (Lucy 2.1 prompting guide) ==")
    assert len(C.PROMPT_TEMPLATES) == 4, len(C.PROMPT_TEMPLATES)
    label = list(C.PROMPT_TEMPLATES.keys())[0]
    application.template_var.set(label)
    application._on_template_selected()
    root.update()
    inserted = application.prompt_text.get("1.0", "end").strip()
    assert inserted == C.PROMPT_TEMPLATES[label], inserted
    assert application.template_combo.current() == 0  # reset to placeholder
    print("prompt template insert OK ->", inserted[:48], "...")

    print("== text-only mode (no reference image) ==")
    application.reference_image_path = None
    application.source_var.set("Webcam (live camera)")
    cfg2 = application._build_session_config()
    assert cfg2 is not None and cfg2.image_path is None
    print("text-only SessionConfig OK (image_path =", cfg2.image_path, ")")

    print("== preview render with a fake frame ==")
    application._last_frame = Image.new("RGB", (1280, 720), (30, 30, 60))
    application._draw_preview()
    root.update()
    print("preview render OK")

    print("== picture grabber ==")
    make_test_image("_test_ref.png", 900, 700)
    g = PictureGrabber("_test_ref.png")
    g.start(1088, 624)
    data = g.get_frame(1088, 624)
    assert data is not None and len(data) == 1088 * 624 * 3, len(data) if data else None
    print("PictureGrabber OK ->", len(data), "bytes (expect", 1088 * 624 * 3, ")")

    print("== crop box aspect ==")
    box = _crop_box(1920, 1080, 624, 1088)  # landscape src -> portrait dst
    bw, bh = box[2] - box[0], box[3] - box[1]
    assert abs((bw / bh) - (624 / 1088)) < 0.01, (bw, bh)
    print("crop box OK:", box)

    print("== webcam grabber (no camera expected) ==")
    wg = WebcamGrabber(0)
    wg.start(1088, 624)
    time.sleep(0.6)
    wg.stop()
    print("WebcamGrabber handled gracefully; error =", wg.error)

    print("== event queue handling ==")
    application._on_engine_event("status", "hello from engine")
    application._on_engine_event("tick", 42)
    application._on_engine_event("session", {"session_id": "abc", "subscribe_token": "tok"})
    application._drain_events()
    root.update()
    assert application._billing_seconds == 42
    print("event handling OK")

    print("== shutdown ==")
    application._on_close()
    print("ALL HEADLESS TESTS PASSED")
    try:
        os.remove("_test_ref.png")
    except OSError:
        pass


if __name__ == "__main__":
    main()
