"""Verify the LiveKit frame-push path, frame conversion and Decart option/state
construction without making a network connection."""
import asyncio
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decart import models
from decart.realtime import RealtimeConnectOptions, SetInput
from decart.types import ModelState, Prompt
from livekit import rtc

from decart_engine import DecartEngine


async def main():
    model = models.realtime("lucy-2.1")
    print("model:", model.name, model.width, model.height, model.fps)

    # --- Build a LiveKit source + track exactly like the engine does --------
    w, h = model.width, model.height
    source = rtc.VideoSource(w, h)
    track = rtc.LocalVideoTrack.create_video_track("input", source)
    print("created VideoSource + LocalVideoTrack:", track.name)

    # --- Push an RGB24 frame ------------------------------------------------
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 0] = 128
    frame = rtc.VideoFrame(width=w, height=h, type=rtc.VideoBufferType.RGB24, data=img.tobytes())
    source.capture_frame(frame)
    print("capture_frame OK")

    # --- Portrait dims (mobile view) ---------------------------------------
    pw, ph = model.height, model.width
    p_source = rtc.VideoSource(pw, ph)
    p_img = np.zeros((ph, pw, 3), dtype=np.uint8)
    p_source.capture_frame(rtc.VideoFrame(width=pw, height=ph, type=rtc.VideoBufferType.RGB24, data=p_img.tobytes()))
    print("portrait capture OK:", pw, "x", ph)

    # --- Decart options / state construction -------------------------------
    opts = RealtimeConnectOptions(
        model=model,
        on_remote_stream=lambda t: None,
        initial_state=ModelState(prompt=Prompt(text="Substitute the character", enhance=True), image=b"\x00\x01"),
        resolution="1080p",
    )
    print("RealtimeConnectOptions OK:", opts.resolution, opts.model.name, opts.preferred_video_codec)

    si3 = SetInput(prompt="Transform", image=b"abc", enhance=True)
    print("SetInput OK:", si3.prompt, bool(si3.image))

    # --- Engine frame conversion helper (RGB24 direct) ----------------------
    fresh = rtc.VideoFrame(width=w, height=h, type=rtc.VideoBufferType.RGB24, data=img.tobytes())
    pil_rgb = DecartEngine._frame_to_image(fresh, rtc)
    assert pil_rgb is not None and pil_rgb.size == (w, h)
    print("engine RGB24 -> PIL OK:", pil_rgb.size)

    # --- Engine frame conversion helper (I420 -> RGB24) ---------------------
    fresh2 = rtc.VideoFrame(width=w, height=h, type=rtc.VideoBufferType.RGB24, data=img.tobytes())
    i420 = fresh2.convert(rtc.VideoBufferType.I420)
    pil_i420 = DecartEngine._frame_to_image(i420, rtc)
    assert pil_i420 is not None and pil_i420.size == (w, h)
    print("engine I420 -> PIL OK:", pil_i420.size)

    await source.aclose()
    await p_source.aclose()
    print("ALL ENGINE PATH TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
