"""
decart_engine.py
================

Thread-safe bridge between a Tkinter GUI (main thread) and the async Decart
Realtime SDK + LiveKit WebRTC stack.

Design
------
* A dedicated background thread owns an asyncio event loop.  All Decart /
  LiveKit coroutines run there.
* The GUI never blocks: it calls small thread-safe methods (``connect``,
  ``disconnect``, ``update_state`` …) which schedule coroutines on the loop.
* Incoming transformed frames are converted to ``PIL.Image`` objects and stored
  in a single "latest frame" slot guarded by a lock (frames are dropped rather
  than queued, which keeps latency low and memory flat).
* Status / error / billing events are pushed to a callback which the GUI turns
  into a thread-safe queue.

The module imports the heavy third-party stack lazily so the GUI can start and
show a friendly error if a dependency is missing.
"""
from __future__ import annotations

import asyncio
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

from PIL import Image

from config import (
    DEFAULT_BASE_URL,
    SOURCE_PICTURE,
    SOURCE_WEBCAM,
    VIEW_MOBILE,
)

# --------------------------------------------------------------------------- #
# Event kinds emitted from the worker thread to the GUI
# --------------------------------------------------------------------------- #
EVT_STATE = "state"        # payload: connection-state string
EVT_STATUS = "status"      # payload: short human readable status line
EVT_ERROR = "error"        # payload: error message string
EVT_TICK = "tick"          # payload: int seconds of generation (billing)
EVT_SESSION = "session"    # payload: dict(session_id=..., subscribe_token=...)
EVT_LOG = "log"            # payload: verbose log line


# --------------------------------------------------------------------------- #
# Session configuration passed from the GUI to the engine
# --------------------------------------------------------------------------- #
@dataclass
class SessionConfig:
    api_key: str
    model_name: str
    prompt: str
    image_path: Optional[str]
    resolution: str
    view_mode: str
    source_type: str
    camera_index: int = 0
    base_url: str = DEFAULT_BASE_URL
    enhance: bool = True


# --------------------------------------------------------------------------- #
# Frame grabbers -- turn an input (camera or picture) into RGB24 byte buffers
# --------------------------------------------------------------------------- #
def _crop_box(src_w: int, src_h: int, dst_w: int, dst_h: int):
    """Return a centered crop box that matches the destination aspect ratio."""
    dst_ar = dst_w / dst_h
    src_ar = src_w / src_h
    if src_ar > dst_ar:
        new_w = int(round(src_h * dst_ar))
        x0 = (src_w - new_w) // 2
        return x0, 0, x0 + new_w, src_h
    new_h = int(round(src_w / dst_ar))
    y0 = (src_h - new_h) // 2
    return 0, y0, src_w, y0 + new_h


class BaseGrabber:
    """Interface: produce the newest RGB24 frame at the requested size."""

    def start(self, width: int, height: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def get_frame(self, width: int, height: int) -> Optional[bytes]:  # pragma: no cover
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover
        pass

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        return True


class WebcamGrabber(BaseGrabber):
    """Reads a live camera on a background thread and keeps the latest frame."""

    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self._cap = None
        self._lock = threading.Lock()
        self._latest = None  # numpy RGB array
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._size = (0, 0)
        self._error: Optional[str] = None
        self._frame_ready = threading.Event()
        self._backend_name: Optional[str] = None
        self._frame_size: Optional[tuple[int, int]] = None

    def start(self, width: int, height: int) -> None:
        self._size = (width, height)
        self._error = None
        self._frame_ready.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="webcam", daemon=True)
        self._thread.start()

    def _open_camera(self, cv2):
        # Prefer the Windows default (usually Media Foundation); DSHOW may fail
        # on some cameras even when another backend can read them.
        for backend in (None, getattr(cv2, "CAP_DSHOW", 700)):
            try:
                cap = (
                    cv2.VideoCapture(self.camera_index, backend)
                    if backend is not None
                    else cv2.VideoCapture(self.camera_index)
                )
                if cap is not None and cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                    try:
                        self._backend_name = cap.getBackendName()
                    except Exception:
                        self._backend_name = "unknown"
                    return cap
                if cap is not None:
                    cap.release()
            except Exception:
                continue
        return None

    def _loop(self) -> None:
        try:
            import cv2  # local import keeps module import light

            cap = self._open_camera(cv2)
            if cap is None:
                self._error = f"Could not open camera index {self.camera_index}"
                return
            self._cap = cap
            while self._running:
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.005)
                    continue
                self._frame_size = (frame.shape[1], frame.shape[0])
                w, h = self._size
                if w and h:
                    x0, y0, x1, y1 = _crop_box(frame.shape[1], frame.shape[0], w, h)
                    frame = frame[y0:y1, x0:x1]
                    frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                with self._lock:
                    self._latest = frame
                self._frame_ready.set()
        except Exception as exc:
            self._error = f"Camera index {self.camera_index} capture failed: {exc}"
        finally:
            self._running = False
            self._frame_ready.set()
            cap = self._cap
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        if not self._frame_ready.wait(timeout):
            self._error = (
                f"Camera index {self.camera_index} opened but did not provide a video frame "
                f"within {timeout:g} seconds."
            )
            return False
        return self._latest is not None

    def get_frame(self, width: int, height: int) -> Optional[bytes]:
        with self._lock:
            frame = self._latest
        if frame is None:
            return None
        return frame.tobytes()

    @property
    def error(self) -> Optional[str]:
        return self._error

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)


class PictureGrabber(BaseGrabber):
    """Streams a static picture (resized to the model size) as the input feed."""

    def __init__(self, path: str):
        self.path = path
        self._bytes: Optional[bytes] = None
        self._size = (0, 0)

    def start(self, width: int, height: int) -> None:
        self._size = (width, height)
        img = Image.open(self.path).convert("RGB")
        x0, y0, x1, y1 = _crop_box(img.width, img.height, width, height)
        img = img.crop((x0, y0, x1, y1)).resize((width, height), Image.LANCZOS)
        self._bytes = img.tobytes()

    def get_frame(self, width: int, height: int) -> Optional[bytes]:
        return self._bytes

    def stop(self) -> None:
        pass


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
class DecartEngine:
    """Owns the asyncio loop + Decart session; safe to call from any thread."""

    def __init__(self, event_callback: Callable[[str, object], None]):
        self._emit = event_callback

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[Image.Image] = None

        self._realtime = None            # decart RealtimeClient
        self._source = None              # livekit VideoSource
        self._grabber: Optional[BaseGrabber] = None
        self._capture_task: Optional[asyncio.Task] = None
        self._remote_stream_tasks: dict[object, asyncio.Task] = {}

        self._stop_requested = threading.Event()
        self._session_active = False
        self._connected = False
        self._last_config: Optional[SessionConfig] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Start the background event-loop thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name="decart-loop", daemon=True)
        self._thread.start()

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            self._loop.close()

    def shutdown(self) -> None:
        """Stop the session and terminate the loop thread."""
        self.disconnect()
        deadline = time.time() + 5
        while self._session_active and time.time() < deadline:
            time.sleep(0.05)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    # ------------------------------------------------------------------ #
    # Public, thread-safe commands
    # ------------------------------------------------------------------ #
    def connect(self, cfg: SessionConfig) -> None:
        self._last_config = cfg
        if self._session_active:
            self._log("A session is already running.")
            return
        self._stop_requested.clear()
        self._submit(self._session_coro(cfg))

    def disconnect(self) -> None:
        self._stop_requested.set()

    def restart(self, cfg: SessionConfig) -> None:
        """Tear down the current session (if any) and start a fresh one."""
        self._last_config = cfg

        def worker():
            if self._session_active:
                self.disconnect()
                deadline = time.time() + 15
                while self._session_active and time.time() < deadline:
                    time.sleep(0.1)
            self._stop_requested.clear()
            self._submit(self._session_coro(cfg))

        threading.Thread(target=worker, name="decart-restart", daemon=True).start()

    def update_state(self, prompt: str, image_path: Optional[str], enhance: bool = True) -> None:
        """Live-update the prompt and/or reference image without reconnecting."""
        self._submit(self._update_state_coro(prompt, image_path, enhance))

    # ------------------------------------------------------------------ #
    # Frame access (called from the GUI thread)
    # ------------------------------------------------------------------ #
    def get_latest_frame(self) -> Optional[Image.Image]:
        with self._frame_lock:
            return self._latest_frame

    def clear_frame(self) -> None:
        with self._frame_lock:
            self._latest_frame = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _submit(self, coro) -> None:
        if self._loop is None:
            self._emit(EVT_ERROR, "Engine not started.")
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _log(self, msg: str) -> None:
        self._emit(EVT_LOG, msg)

    def _build_initial_state(self, cfg: SessionConfig):
        from decart.types import ModelState, Prompt

        image = None
        if cfg.image_path:
            try:
                with open(cfg.image_path, "rb") as fh:
                    image = fh.read()
            except Exception as exc:  # pragma: no cover - surfaced to the UI
                self._emit(EVT_ERROR, f"Could not read reference picture: {exc}")
                image = None

        prompt = Prompt(text=cfg.prompt, enhance=cfg.enhance) if cfg.prompt else None
        if prompt is None and image is None:
            return None
        return ModelState(prompt=prompt, image=image)

    @staticmethod
    def _source_dims(model, view_mode: str):
        if view_mode == VIEW_MOBILE:
            return model.height, model.width  # portrait (swap w/h)
        return model.width, model.height

    def _make_grabber(self, cfg: SessionConfig) -> BaseGrabber:
        if cfg.source_type == SOURCE_PICTURE:
            if not cfg.image_path:
                raise ValueError("Picture source selected but no reference picture was provided.")
            return PictureGrabber(cfg.image_path)
        if cfg.source_type == SOURCE_WEBCAM:
            return WebcamGrabber(cfg.camera_index)
        raise ValueError(f"Unknown source type: {cfg.source_type}")

    # ------------------------------------------------------------------ #
    # Coroutines (run on the worker loop)
    # ------------------------------------------------------------------ #
    async def _session_coro(self, cfg: SessionConfig) -> None:
        self._session_active = True
        self._emit(EVT_STATE, "connecting")
        self._emit(EVT_STATUS, "Connecting to Decart…")

        grabber: Optional[BaseGrabber] = None
        realtime = None
        try:
            # Lazy imports so a missing dependency surfaces as a clean error.
            from decart import DecartClient, models
            from decart.realtime import RealtimeClient, RealtimeConnectOptions
            from livekit import rtc

            grabber = self._make_grabber(cfg)
            self._grabber = grabber

            async with DecartClient(api_key=cfg.api_key, base_url=cfg.base_url or DEFAULT_BASE_URL) as client:
                model = models.realtime(cfg.model_name)
                width, height = self._source_dims(model, cfg.view_mode)
                self._log(
                    f"Model {model.name}: native {model.width}x{model.height} @ {model.fps}fps "
                    f"| input {width}x{height} | output {cfg.resolution} | view {cfg.view_mode}"
                )

                grabber.start(width, height)
                if not await asyncio.to_thread(grabber.wait_until_ready, 10.0):
                    raise RuntimeError(
                        getattr(grabber, "error", None)
                        or "The selected camera did not provide a live video frame."
                    )
                if isinstance(grabber, WebcamGrabber):
                    frame_width, frame_height = grabber._frame_size or (width, height)
                    self._log(
                        f"Live camera {grabber.camera_index}: {frame_width}x{frame_height} "
                        f"via {grabber._backend_name}; sending frames at {model.fps} fps"
                    )

                source = rtc.VideoSource(width, height)
                local_track = rtc.LocalVideoTrack.create_video_track("input", source)
                self._source = source

                initial_state = self._build_initial_state(cfg)
                options = RealtimeConnectOptions(
                    model=model,
                    on_remote_stream=self._on_remote_stream,
                    initial_state=initial_state,
                    resolution=cfg.resolution,
                )

                self._capture_task = asyncio.create_task(
                    self._capture_loop(source, grabber, width, height, model.fps)
                )

                realtime = await RealtimeClient.connect(
                    base_url=client.realtime_base_url,
                    api_key=client.api_key,
                    local_track=local_track,
                    options=options,
                )
                self._realtime = realtime
                realtime.on("connection_change", self._on_connection_change)
                realtime.on("error", self._on_error)
                realtime.on("generation_tick", self._on_generation_tick)

                self._connected = True
                self._emit(EVT_STATE, "connected")
                self._emit(EVT_STATUS, "Connected - streaming live")
                self._emit(
                    EVT_SESSION,
                    {
                        "session_id": getattr(realtime, "session_id", None),
                        "subscribe_token": getattr(realtime, "subscribe_token", None),
                    },
                )

                # Block until the GUI requests a disconnect.
                while not self._stop_requested.is_set():
                    await asyncio.sleep(0.1)

                self._emit(EVT_STATUS, "Disconnecting…")
                try:
                    await realtime.disconnect()
                except Exception:
                    pass

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._emit(EVT_ERROR, f"{type(exc).__name__}: {exc}")
            self._emit(EVT_LOG, traceback.format_exc())
        finally:
            # Stop capture + grabber
            if self._capture_task is not None:
                self._capture_task.cancel()
                try:
                    await self._capture_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._capture_task = None
            await self._stop_remote_streams()
            if grabber is not None:
                try:
                    grabber.stop()
                except Exception:
                    pass
            if self._source is not None:
                try:
                    await self._source.aclose()
                except Exception:
                    pass
            self._source = None
            self._grabber = None
            self._realtime = None
            self._connected = False
            self._session_active = False
            self.clear_frame()
            self._emit(EVT_STATE, "disconnected")
            self._emit(EVT_STATUS, "Disconnected")

    async def _capture_loop(self, source, grabber: BaseGrabber, width: int, height: int, fps: int) -> None:
        from livekit import rtc

        interval = 1.0 / float(fps)
        next_t = time.perf_counter()
        warned = False
        while not self._stop_requested.is_set():
            frame_bytes = grabber.get_frame(width, height)
            if frame_bytes is not None:
                try:
                    source.capture_frame(
                        rtc.VideoFrame(
                            width=width,
                            height=height,
                            type=rtc.VideoBufferType.RGB24,
                            data=frame_bytes,
                        )
                    )
                except Exception as exc:  # pragma: no cover
                    if not warned:
                        self._log(f"capture_frame warning: {exc}")
                        warned = True
            else:
                # Camera may still be warming up.
                err = getattr(grabber, "error", None)
                if err and not warned:
                    self._emit(EVT_ERROR, err)
                    warned = True

            next_t += interval
            delay = next_t - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                next_t = time.perf_counter()
                await asyncio.sleep(0)

    async def _update_state_coro(self, prompt: str, image_path: Optional[str], enhance: bool) -> None:
        realtime = self._realtime
        if realtime is None:
            self._emit(EVT_STATUS, "Not connected - change will apply on next connect.")
            return
        try:
            from decart.realtime import SetInput

            image_bytes = None
            if image_path:
                with open(image_path, "rb") as fh:
                    image_bytes = fh.read()

            if prompt and image_bytes:
                payload = SetInput(prompt=prompt, image=image_bytes, enhance=enhance)
            elif image_bytes:
                payload = SetInput(image=image_bytes)
            elif prompt:
                payload = SetInput(prompt=prompt, enhance=enhance)
            else:
                self._emit(EVT_STATUS, "Nothing to update (empty prompt and picture).")
                return

            await realtime.set(payload)
            self._emit(EVT_STATUS, "Applied prompt / reference picture update")
            self._log("Live state updated via set().")
        except Exception as exc:
            self._emit(EVT_ERROR, f"Update failed: {exc}")

    # ------------------------------------------------------------------ #
    # SDK callbacks (invoked on the worker loop)
    # ------------------------------------------------------------------ #
    def _on_remote_stream(self, track) -> None:
        from livekit import rtc

        track_id = getattr(track, "sid", None) or id(track)
        existing_task = self._remote_stream_tasks.get(track_id)
        if existing_task is not None and not existing_task.done():
            return

        async def consume():
            stream = rtc.VideoStream(track)
            try:
                async for event in stream:
                    img = self._frame_to_image(event.frame, rtc)
                    if img is None:
                        continue
                    with self._frame_lock:
                        self._latest_frame = img
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover
                self._emit(EVT_LOG, f"remote stream ended: {exc}")
            finally:
                try:
                    await stream.aclose()
                except Exception:
                    pass

        task = asyncio.create_task(consume(), name=f"remote-video-{track_id}")
        self._remote_stream_tasks[track_id] = task

        def forget_task(done_task: asyncio.Task) -> None:
            if self._remote_stream_tasks.get(track_id) is done_task:
                self._remote_stream_tasks.pop(track_id, None)

        task.add_done_callback(forget_task)

    async def _stop_remote_streams(self) -> None:
        """Cancel and await every output-track consumer before the loop exits."""
        tasks = list(self._remote_stream_tasks.values())
        self._remote_stream_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _frame_to_image(frame, rtc) -> Optional[Image.Image]:
        """Convert a LiveKit video frame to a PIL image, whatever its format."""
        try:
            # Already RGB24 -> use the buffer directly (convert() rejects a
            # same-format conversion).
            if frame.type == rtc.VideoBufferType.RGB24:
                return Image.frombytes("RGB", (frame.width, frame.height), bytes(frame.data))
            rgb = frame.convert(rtc.VideoBufferType.RGB24)
            return Image.frombytes("RGB", (rgb.width, rgb.height), bytes(rgb.data))
        except Exception:
            return DecartEngine._fallback_frame_to_image(frame)

    @staticmethod
    def _fallback_frame_to_image(frame) -> Optional[Image.Image]:
        """Best-effort conversion for I420 frames if convert() is unavailable."""
        try:
            width, height = frame.width, frame.height
            data = bytes(frame.data)
            # Assume I420: Y (w*h) + U (w*h/4) + V (w*h/4)
            expected = width * height * 3 // 2
            if len(data) < expected:
                return None
            import numpy as np

            y = np.frombuffer(data[: width * height], dtype=np.uint8).reshape((height, width))
            u = np.frombuffer(data[width * height: width * height + (width * height) // 4], dtype=np.uint8).reshape((height // 2, width // 2))
            v = np.frombuffer(data[width * height + (width * height) // 4: expected], dtype=np.uint8).reshape((height // 2, width // 2))
            import cv2

            u = cv2.resize(u, (width, height), interpolation=cv2.INTER_LINEAR)
            v = cv2.resize(v, (width, height), interpolation=cv2.INTER_LINEAR)
            yuv = cv2.merge([y, u, v])
            rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)
            return Image.fromarray(rgb, "RGB")
        except Exception:
            return None

    def _on_connection_change(self, state) -> None:
        self._emit(EVT_STATE, str(state))
        self._log(f"connection_change: {state}")

    def _on_error(self, error) -> None:
        code = getattr(error, "code", None)
        message = getattr(error, "message", None) or str(error)
        label = f"{code}: {message}" if code else message
        self._emit(EVT_ERROR, label)

    def _on_generation_tick(self, message) -> None:
        seconds = getattr(message, "seconds", None)
        if seconds is None and isinstance(message, dict):
            seconds = message.get("seconds")
        if seconds is not None:
            self._emit(EVT_TICK, int(seconds))
