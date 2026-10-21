"""
app.py
======

Decart Livestream Studio - a Windows desktop app (Tkinter) that starts and
stops a Decart Lucy realtime livestream from an uploaded reference picture, an
API key and a streaming description, with a Mobile/Desktop view toggle that
resizes the output stream and a single Connect/Disconnect button.

Run with:  python app.py
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import config as C
from decart_engine import (
    EVT_ERROR,
    EVT_LOG,
    EVT_SESSION,
    EVT_STATE,
    EVT_STATUS,
    EVT_TICK,
    DecartEngine,
    SessionConfig,
)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def settings_path() -> Path:
    return Path.home() / C.SETTINGS_FILENAME


def load_settings() -> dict:
    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    try:
        with open(settings_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass


def check_dependencies() -> list[str]:
    missing = []
    for mod, pip_name in (("decart", "decart[realtime]"), ("livekit", "decart[realtime]"), ("cv2", "opencv-python"), ("PIL", "Pillow"), ("numpy", "numpy")):
        try:
            __import__(mod)
        except Exception:
            missing.append(pip_name)
    return missing


# --------------------------------------------------------------------------- #
# The application
# --------------------------------------------------------------------------- #
class DecartLivestreamApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()

        self.event_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.engine = DecartEngine(self._on_engine_event)

        self.reference_image_path: str | None = self.settings.get("image_path") or None
        self._ref_thumb: ImageTk.PhotoImage | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._last_frame: Image.Image | None = None

        self._state = "disconnected"
        self._connect_started_at: float | None = None
        self._billing_seconds = 0

        self._build_style()
        self._build_ui()
        self._apply_settings_to_ui()

        self.engine.start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(C.PREVIEW_INTERVAL_MS, self._poll)

    # ------------------------------------------------------------------ #
    # Styling
    # ------------------------------------------------------------------ #
    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=C.COLOR_BG, foreground=C.COLOR_TEXT,
                        fieldbackground=C.COLOR_PANEL_ALT, font=("Segoe UI", 10))
        style.configure("TFrame", background=C.COLOR_BG)
        style.configure("Panel.TFrame", background=C.COLOR_PANEL)
        style.configure("TLabel", background=C.COLOR_BG, foreground=C.COLOR_TEXT)
        style.configure("Panel.TLabel", background=C.COLOR_PANEL, foreground=C.COLOR_TEXT)
        style.configure("Dim.TLabel", background=C.COLOR_PANEL, foreground=C.COLOR_TEXT_DIM)
        style.configure("Hint.TLabel", background=C.COLOR_PANEL, foreground=C.COLOR_WARN, font=("Segoe UI", 8))
        style.configure("Section.TLabel", background=C.COLOR_PANEL, foreground=C.COLOR_ACCENT,
                        font=("Segoe UI Semibold", 10))
        style.configure("Title.TLabel", background=C.COLOR_BG, foreground=C.COLOR_TEXT,
                        font=("Segoe UI Semibold", 18))
        style.configure("Sub.TLabel", background=C.COLOR_BG, foreground=C.COLOR_TEXT_DIM,
                        font=("Segoe UI", 9))

        style.configure("TEntry", fieldbackground=C.COLOR_PANEL_ALT, foreground=C.COLOR_TEXT,
                        insertcolor=C.COLOR_TEXT, bordercolor=C.COLOR_BORDER, relief="flat")
        style.configure("TCombobox", fieldbackground=C.COLOR_PANEL_ALT, background=C.COLOR_PANEL_ALT,
                        foreground=C.COLOR_TEXT, arrowcolor=C.COLOR_TEXT, bordercolor=C.COLOR_BORDER)
        style.map("TCombobox",
                  fieldbackground=[("readonly", C.COLOR_PANEL_ALT)],
                  foreground=[("readonly", C.COLOR_TEXT)])
        style.configure("TCheckbutton", background=C.COLOR_PANEL, foreground=C.COLOR_TEXT)
        style.map("TCheckbutton", background=[("active", C.COLOR_PANEL)])
        style.configure("TButton", background=C.COLOR_PANEL_ALT, foreground=C.COLOR_TEXT,
                        bordercolor=C.COLOR_BORDER, focuscolor=C.COLOR_PANEL_ALT, padding=6)
        style.map("TButton", background=[("active", C.COLOR_BORDER)])
        style.configure("TSpinbox", fieldbackground=C.COLOR_PANEL_ALT, foreground=C.COLOR_TEXT,
                        arrowcolor=C.COLOR_TEXT, background=C.COLOR_PANEL_ALT)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        self.root.title(f"{C.APP_NAME} v{C.APP_VERSION}")
        self.root.configure(bg=C.COLOR_BG)
        self.root.geometry("1280x860")
        self.root.minsize(1080, 700)

        # ---- Header -----------------------------------------------------
        header = ttk.Frame(self.root, padding=(18, 14, 18, 6))
        header.pack(fill="x")
        ttk.Label(header, text=C.APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text=C.APP_TAGLINE + "  •  maximum quality: 1080p (Decart realtime API limit)",
                  style="Sub.TLabel").pack(anchor="w")

        body = ttk.Frame(self.root, padding=(14, 6, 14, 14))
        body.pack(fill="both", expand=True)

        # Left = scrollable controls + fixed footer, Right = live preview
        left_outer = ttk.Frame(body, style="Panel.TFrame", width=416)
        left_outer.pack(side="left", fill="y")
        left_outer.pack_propagate(False)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        # Fixed footer holds the always-visible view toggle + stream controls.
        self._build_footer(left_outer)

        # Scrollable upper controls (sections 1-6).
        scroll_container = ttk.Frame(left_outer, style="Panel.TFrame")
        scroll_container.pack(side="top", fill="both", expand=True)
        self._scroll_canvas = tk.Canvas(scroll_container, bg=C.COLOR_PANEL, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical", command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._scroll_canvas.pack(side="left", fill="both", expand=True)

        controls = ttk.Frame(self._scroll_canvas, style="Panel.TFrame", padding=(16, 12, 12, 12))
        win = self._scroll_canvas.create_window((0, 0), window=controls, anchor="nw")
        controls.bind("<Configure>",
                      lambda e: self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all")))
        self._scroll_canvas.bind("<Configure>",
                                 lambda e: self._scroll_canvas.itemconfigure(win, width=e.width))

        self._build_controls(controls)
        self._bind_wheel(controls, self._scroll_canvas)
        self._bind_wheel(self._scroll_canvas, self._scroll_canvas)

        self._build_preview(right)

    # ------------------------------------------------------------------ #
    def _section(self, parent, text: str):
        ttk.Label(parent, text=text, style="Section.TLabel").pack(anchor="w", pady=(12, 4))

    def _build_controls(self, parent) -> None:
        # 1. API key ------------------------------------------------------
        self._section(parent, "1 · Decart API key")
        key_row = ttk.Frame(parent, style="Panel.TFrame")
        key_row.pack(fill="x")
        self.api_key_var = tk.StringVar(value=self.settings.get("api_key", ""))
        self.api_entry = ttk.Entry(key_row, textvariable=self.api_key_var, show="•")
        self.api_entry.pack(side="left", fill="x", expand=True)
        self.show_key_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(key_row, text="Show", variable=self.show_key_var,
                        command=self._toggle_key, style="TCheckbutton").pack(side="left", padx=(6, 0))

        self.remember_var = tk.BooleanVar(value=bool(self.settings.get("remember_key", False)))
        ttk.Checkbutton(parent, text="Remember API key on this device",
                        variable=self.remember_var, style="TCheckbutton").pack(anchor="w", pady=(2, 0))

        # 2. Model --------------------------------------------------------
        self._section(parent, "2 · Realtime model")
        self.model_var = tk.StringVar()
        model_labels = list(C.REALTIME_MODELS.values())
        self.model_combo = ttk.Combobox(parent, textvariable=self.model_var, values=model_labels,
                                        state="readonly")
        self.model_combo.pack(fill="x")
        self.model_combo.bind("<<ComboboxSelected>>", lambda e: self._on_option_changed())

        # 3. Resolution ---------------------------------------------------
        self._section(parent, "3 · Output quality")
        self.resolution_var = tk.StringVar()
        self.res_combo = ttk.Combobox(parent, textvariable=self.resolution_var,
                                      values=C.RESOLUTIONS, state="readonly")
        self.res_combo.pack(fill="x")
        self.res_combo.bind("<<ComboboxSelected>>", lambda e: self._on_option_changed())
        ttk.Label(parent, text="Note: the Decart realtime API supports up to 1080p. "
                               "4K is not offered by the realtime endpoint.",
                  style="Hint.TLabel", wraplength=360, justify="left").pack(anchor="w", pady=(2, 0))

        # 4. Reference picture -------------------------------------------
        self._section(parent, "4 · Reference picture")
        pic_row = ttk.Frame(parent, style="Panel.TFrame")
        pic_row.pack(fill="x")
        ttk.Button(pic_row, text="Choose picture…", command=self._choose_picture).pack(side="left")
        ttk.Button(pic_row, text="Clear", command=self._clear_picture).pack(side="left", padx=(6, 0))
        self.ref_thumb_label = ttk.Label(parent, style="Panel.TLabel")
        self.ref_thumb_label.pack(anchor="w", pady=(6, 0))
        self.ref_path_label = ttk.Label(parent, text="No picture selected", style="Dim.TLabel",
                                        wraplength=360, justify="left")
        self.ref_path_label.pack(anchor="w")
        ttk.Label(parent, text=C.REFERENCE_HINT, style="Hint.TLabel",
                  wraplength=360, justify="left").pack(anchor="w", pady=(2, 0))

        # 5. Streaming description ---------------------------------------
        self._section(parent, "5 · Streaming description")
        tpl_row = ttk.Frame(parent, style="Panel.TFrame")
        tpl_row.pack(fill="x", pady=(0, 4))
        ttk.Label(tpl_row, text="Template:", style="Panel.TLabel").pack(side="left")
        self.template_var = tk.StringVar()
        self.template_combo = ttk.Combobox(tpl_row, textvariable=self.template_var,
                                           values=["Insert a prompt template\u2026"] + list(C.PROMPT_TEMPLATES.keys()),
                                           state="readonly")
        self.template_combo.current(0)
        self.template_combo.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.template_combo.bind("<<ComboboxSelected>>", self._on_template_selected)
        self.prompt_text = tk.Text(parent, height=4, wrap="word", bg=C.COLOR_PANEL_ALT,
                                   fg=C.COLOR_TEXT, insertbackground=C.COLOR_TEXT,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=C.COLOR_BORDER, font=("Segoe UI", 10))
        self.prompt_text.pack(fill="x")
        self.enhance_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Auto-enhance prompt", variable=self.enhance_var,
                        style="TCheckbutton").pack(anchor="w", pady=(2, 0))
        ttk.Label(parent, text="One edit per prompt for predictable results. "
                               "Describe the reference image in detail for character transforms.",
                  style="Hint.TLabel", wraplength=360, justify="left").pack(anchor="w", pady=(2, 0))

        # 6. Video source ------------------------------------------------
        self._section(parent, "6 · Video source")
        self.source_var = tk.StringVar()
        self.source_combo = ttk.Combobox(parent, textvariable=self.source_var,
                                         values=["Webcam (live camera)", "Reference picture (static)"],
                                         state="readonly")
        self.source_combo.pack(fill="x")
        self.source_combo.bind("<<ComboboxSelected>>", lambda e: self._on_option_changed())
        cam_row = ttk.Frame(parent, style="Panel.TFrame")
        cam_row.pack(fill="x", pady=(4, 0))
        ttk.Label(cam_row, text="Color camera index (not IR):", style="Panel.TLabel").pack(side="left")
        self.camera_var = tk.IntVar(value=int(self.settings.get("camera_index", 0)))
        ttk.Spinbox(cam_row, from_=0, to=10, width=4, textvariable=self.camera_var).pack(side="left", padx=(6, 0))

    def _build_footer(self, parent) -> None:
        """Always-visible footer: output-view toggle + stream control button."""
        footer = ttk.Frame(parent, style="Panel.TFrame", padding=(16, 10, 12, 14))
        footer.pack(side="bottom", fill="x")

        # 7. Output view -------------------------------------------------
        ttk.Label(footer, text="7 · Output view", style="Section.TLabel").pack(anchor="w", pady=(0, 4))
        view_row = ttk.Frame(footer, style="Panel.TFrame")
        view_row.pack(fill="x")
        self.desktop_btn = tk.Button(view_row, text="🖥  Desktop  16:9", command=lambda: self._set_view(C.VIEW_DESKTOP),
                                     relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 10), pady=8)
        self.desktop_btn.pack(side="left", fill="x", expand=True)
        self.mobile_btn = tk.Button(view_row, text="📱  Mobile  9:16", command=lambda: self._set_view(C.VIEW_MOBILE),
                                    relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 10), pady=8)
        self.mobile_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.view_var = tk.StringVar(value=self.settings.get("view_mode", C.DEFAULT_VIEW))

        # 8. Stream control ----------------------------------------------
        ttk.Label(footer, text="8 · Stream control", style="Section.TLabel").pack(anchor="w", pady=(10, 4))
        self.connect_btn = tk.Button(footer, text="●  Connect & Start Stream", command=self._on_connect_clicked,
                                     relief="flat", bd=0, cursor="hand2",
                                     font=("Segoe UI Semibold", 12), pady=12)
        self.connect_btn.pack(fill="x", pady=(0, 6))
        self.apply_btn = tk.Button(footer, text="Apply prompt / picture update", command=self._apply_live,
                                   relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 10), pady=7,
                                   bg=C.COLOR_PANEL_ALT, fg=C.COLOR_TEXT, activebackground=C.COLOR_BORDER,
                                   activeforeground=C.COLOR_TEXT, state="disabled")
        self.apply_btn.pack(fill="x")

        self._update_view_buttons()

    def _bind_wheel(self, widget, canvas) -> None:
        """Recursively bind mouse-wheel scrolling to a widget subtree."""
        widget.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        widget.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        widget.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
        for child in widget.winfo_children():
            self._bind_wheel(child, canvas)

    # ------------------------------------------------------------------ #
    def _build_preview(self, parent) -> None:
        # Preview canvas
        canvas_wrap = tk.Frame(parent, bg=C.COLOR_PANEL, highlightthickness=1,
                               highlightbackground=C.COLOR_BORDER)
        canvas_wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_wrap, bg="#05060a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=1, pady=1)
        self.canvas.bind("<Configure>", lambda e: self._draw_preview())

        # Status bar
        status = tk.Frame(parent, bg=C.COLOR_PANEL, highlightthickness=1,
                          highlightbackground=C.COLOR_BORDER)
        status.pack(fill="x", pady=(10, 0))
        inner = tk.Frame(status, bg=C.COLOR_PANEL)
        inner.pack(fill="x", padx=12, pady=8)

        self.state_dot = tk.Label(inner, text="●", bg=C.COLOR_PANEL, fg=C.COLOR_TEXT_DIM,
                                  font=("Segoe UI", 12))
        self.state_dot.pack(side="left")
        self.state_label = tk.Label(inner, text="Disconnected", bg=C.COLOR_PANEL, fg=C.COLOR_TEXT,
                                    font=("Segoe UI Semibold", 10))
        self.state_label.pack(side="left", padx=(4, 18))

        self.timer_label = tk.Label(inner, text="00:00", bg=C.COLOR_PANEL, fg=C.COLOR_TEXT_DIM,
                                    font=("Consolas", 10))
        self.timer_label.pack(side="left", padx=(0, 18))

        self.info_label = tk.Label(inner, text="—", bg=C.COLOR_PANEL, fg=C.COLOR_TEXT_DIM,
                                   font=("Segoe UI", 9))
        self.info_label.pack(side="left")

        self.session_label = tk.Label(inner, text="", bg=C.COLOR_PANEL, fg=C.COLOR_TEXT_DIM,
                                      font=("Consolas", 8))
        self.session_label.pack(side="right")

        # Log
        log_wrap = tk.Frame(parent, bg=C.COLOR_PANEL, highlightthickness=1,
                            highlightbackground=C.COLOR_BORDER)
        log_wrap.pack(fill="x", pady=(10, 0))
        self.log_text = tk.Text(log_wrap, height=7, wrap="word", bg="#0b0d13", fg=C.COLOR_TEXT_DIM,
                                relief="flat", insertbackground=C.COLOR_TEXT, font=("Consolas", 8))
        self.log_text.pack(fill="x", padx=8, pady=6)
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # Settings <-> UI
    # ------------------------------------------------------------------ #
    def _apply_settings_to_ui(self) -> None:
        model_key = self.settings.get("model", C.DEFAULT_MODEL)
        self.model_var.set(C.REALTIME_MODELS.get(model_key, C.REALTIME_MODELS[C.DEFAULT_MODEL]))
        self.resolution_var.set(self.settings.get("resolution", C.DEFAULT_RESOLUTION))

        source = self.settings.get("source", C.DEFAULT_SOURCE)
        self.source_var.set("Reference picture (static)" if source == C.SOURCE_PICTURE else "Webcam (live camera)")

        self.prompt_text.insert("1.0", self.settings.get("prompt", C.DEFAULT_PROMPT))
        self.enhance_var.set(bool(self.settings.get("enhance", True)))

        if self.reference_image_path and os.path.exists(self.reference_image_path):
            self._load_reference_thumbnail()
        else:
            self.reference_image_path = None

    def _current_model_key(self) -> str:
        label = self.model_var.get()
        for key, value in C.REALTIME_MODELS.items():
            if value == label:
                return key
        return C.DEFAULT_MODEL

    def _current_source(self) -> str:
        return C.SOURCE_PICTURE if self.source_var.get().startswith("Reference") else C.SOURCE_WEBCAM

    def _collect_settings(self) -> dict:
        data = {
            "model": self._current_model_key(),
            "resolution": self.resolution_var.get(),
            "view_mode": self.view_var.get(),
            "source": self._current_source(),
            "camera_index": int(self.camera_var.get()),
            "prompt": self.prompt_text.get("1.0", "end").strip(),
            "enhance": bool(self.enhance_var.get()),
            "image_path": self.reference_image_path,
            "remember_key": bool(self.remember_var.get()),
        }
        if self.remember_var.get():
            data["api_key"] = self.api_key_var.get().strip()
        return data

    # ------------------------------------------------------------------ #
    # Control callbacks
    # ------------------------------------------------------------------ #
    def _toggle_key(self) -> None:
        self.api_entry.configure(show="" if self.show_key_var.get() else "•")

    def _on_template_selected(self, _event=None) -> None:
        label = self.template_var.get()
        template = C.PROMPT_TEMPLATES.get(label)
        if not template:
            return
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", template)
        self.template_combo.current(0)  # reset to the placeholder
        self._log("Inserted prompt template: " + label.split(" \u2014 ")[0])

    def _choose_picture(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose reference picture",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp"), ("All files", "*.*")],
        )
        if not path:
            return
        # Best-practice validation from the Lucy 2.1 reference-image guide.
        ext = os.path.splitext(path)[1].lower()
        if ext not in C.REFERENCE_FORMATS:
            messagebox.showwarning(
                "Unsupported format",
                "Decart supports JPEG, PNG and WebP reference images.\n"
                f"You selected a {ext or 'unknown'} file.",
            )
        try:
            with Image.open(path) as probe:
                w, h = probe.size
            if min(w, h) < C.REFERENCE_MIN_SIZE:
                messagebox.showwarning(
                    "Low-resolution reference",
                    f"This image is {w}\u00d7{h} px. Decart recommends at least "
                    f"{C.REFERENCE_MIN_SIZE}\u00d7{C.REFERENCE_MIN_SIZE} px for a "
                    "consistent character transformation.",
                )
        except Exception:
            pass
        self.reference_image_path = path
        self._load_reference_thumbnail()
        self._log(f"Reference picture: {path}")

    def _clear_picture(self) -> None:
        self.reference_image_path = None
        self.ref_thumb_label.configure(image="")
        self._ref_thumb = None
        self.ref_path_label.configure(text="No picture selected")

    def _load_reference_thumbnail(self) -> None:
        try:
            img = Image.open(self.reference_image_path).convert("RGB")
            img.thumbnail((132, 98))
            self._ref_thumb = ImageTk.PhotoImage(img)
            self.ref_thumb_label.configure(image=self._ref_thumb)
            self.ref_path_label.configure(text=os.path.basename(self.reference_image_path))
        except Exception as exc:
            self._clear_picture()
            messagebox.showerror("Invalid picture", f"Could not open picture:\n{exc}")

    def _set_view(self, mode: str) -> None:
        if mode == self.view_var.get():
            return
        self.view_var.set(mode)
        self._update_view_buttons()
        if self.engine.is_connected:
            self._log(f"View changed to {mode} - reconnecting to resize the output stream…")
            self._restart_if_connected()

    def _update_view_buttons(self) -> None:
        active = {"bg": C.COLOR_ACCENT, "fg": "#ffffff", "activebackground": C.COLOR_ACCENT_HOVER,
                  "activeforeground": "#ffffff"}
        idle = {"bg": C.COLOR_PANEL_ALT, "fg": C.COLOR_TEXT, "activebackground": C.COLOR_BORDER,
                "activeforeground": C.COLOR_TEXT}
        self.desktop_btn.configure(**(active if self.view_var.get() == C.VIEW_DESKTOP else idle))
        self.mobile_btn.configure(**(active if self.view_var.get() == C.VIEW_MOBILE else idle))

    def _on_option_changed(self) -> None:
        if self.engine.is_connected:
            self._log("Option changed - reconnecting to apply…")
            self._restart_if_connected()

    def _restart_if_connected(self) -> None:
        cfg = self._build_session_config()
        if cfg is None:
            return
        self.engine.restart(cfg)

    def _build_session_config(self) -> SessionConfig | None:
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("API key required", "Please enter your Decart API key.")
            return None
        source = self._current_source()
        if source == C.SOURCE_PICTURE and not self.reference_image_path:
            messagebox.showwarning("Picture required", "Picture source is selected but no reference picture was chosen.")
            return None
        return SessionConfig(
            api_key=api_key,
            model_name=self._current_model_key(),
            prompt=self.prompt_text.get("1.0", "end").strip(),
            image_path=self.reference_image_path,
            resolution=self.resolution_var.get(),
            view_mode=self.view_var.get(),
            source_type=source,
            camera_index=int(self.camera_var.get()),
            enhance=bool(self.enhance_var.get()),
        )

    def _on_connect_clicked(self) -> None:
        if self._state in ("connected", "generating", "connecting", "reconnecting"):
            self._log("Disconnect requested.")
            self.engine.disconnect()
            return

        cfg = self._build_session_config()
        if cfg is None:
            return

        # persist settings
        save_settings(self._collect_settings())

        self.engine.clear_frame()
        self._last_frame = None
        self._billing_seconds = 0
        self._connect_started_at = None
        self._log(f"Connecting — model={cfg.model_name}, resolution={cfg.resolution}, "
                  f"view={cfg.view_mode}, source={cfg.source_type}")
        self.engine.connect(cfg)

    def _apply_live(self) -> None:
        self.engine.update_state(
            self.prompt_text.get("1.0", "end").strip(),
            self.reference_image_path,
            bool(self.enhance_var.get()),
        )
        save_settings(self._collect_settings())

    # ------------------------------------------------------------------ #
    # Engine events
    # ------------------------------------------------------------------ #
    def _on_engine_event(self, kind: str, payload: object) -> None:
        # Called from the worker thread -> hand off to the GUI thread.
        self.event_queue.put((kind, payload))

    def _drain_events(self) -> None:
        while True:
            try:
                kind, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(kind, payload)
            except Exception:
                self._log("UI error: " + traceback.format_exc().splitlines()[-1])

    def _handle_event(self, kind: str, payload: object) -> None:
        if kind == EVT_STATE:
            self._set_state(str(payload))
        elif kind == EVT_STATUS:
            self._log(str(payload))
        elif kind == EVT_ERROR:
            self._log("ERROR: " + str(payload))
            self._set_state("error")
        elif kind == EVT_TICK:
            self._billing_seconds = int(payload)
        elif kind == EVT_SESSION:
            data = payload or {}
            sid = data.get("session_id") if isinstance(data, dict) else None
            tok = data.get("subscribe_token") if isinstance(data, dict) else None
            if sid:
                self.session_label.configure(text=f"session: {sid}")
            if tok:
                self._log(f"Viewer subscribe token: {tok}")

    def _set_state(self, state: str) -> None:
        self._state = state
        if state == "disconnected":
            self.engine.clear_frame()
            self._last_frame = None
            self._draw_preview()

        label, color = C.STATE_STYLES.get(state, (state, C.COLOR_TEXT_DIM))
        self.state_label.configure(text=label, fg=color)
        self.state_dot.configure(fg=color)

        live = state in ("connected", "generating", "connecting", "reconnecting")
        if live:
            self.connect_btn.configure(text="■  Disconnect", bg=C.COLOR_DISCONNECT,
                                       activebackground=C.COLOR_DISCONNECT_HOVER)
            self.apply_btn.configure(state="normal")
            if state in ("connected", "generating") and self._connect_started_at is None:
                self._connect_started_at = time.time()
        else:
            self.connect_btn.configure(text="●  Connect & Start Stream", bg=C.COLOR_CONNECT,
                                       activebackground=C.COLOR_CONNECT_HOVER)
            self.apply_btn.configure(state="disabled")
            self._connect_started_at = None

        mode = "Mobile 9:16" if self.view_var.get() == C.VIEW_MOBILE else "Desktop 16:9"
        self.info_label.configure(text=f"{self.resolution_var.get()} · {mode} · {self._current_model_key()}")

    def _log(self, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # Preview rendering
    # ------------------------------------------------------------------ #
    def _poll(self) -> None:
        self._drain_events()

        frame = self.engine.get_latest_frame()
        if frame is not None:
            self._last_frame = frame
            self._draw_preview()

        # timer
        if self._connect_started_at is not None:
            elapsed = int(time.time() - self._connect_started_at)
            self.timer_label.configure(text=f"{elapsed // 60:02d}:{elapsed % 60:02d}", fg=C.COLOR_TEXT)
        else:
            self.timer_label.configure(text="00:00", fg=C.COLOR_TEXT_DIM)

        self.root.after(C.PREVIEW_INTERVAL_MS, self._poll)

    def _draw_preview(self) -> None:
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        self.canvas.delete("all")
        img = self._last_frame
        if img is None:
            self.canvas.create_text(cw // 2, ch // 2,
                                    text="Live preview\n\nConnect to start the transformed stream",
                                    fill=C.COLOR_TEXT_DIM, font=("Segoe UI", 12), justify="center")
            return
        scale = min(cw / img.width, ch / img.height)
        nw = max(1, int(img.width * scale))
        nh = max(1, int(img.height * scale))
        disp = img.resize((nw, nh), Image.BILINEAR)
        self._preview_photo = ImageTk.PhotoImage(disp)
        self.canvas.create_image(cw // 2, ch // 2, image=self._preview_photo)

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #
    def _on_close(self) -> None:
        try:
            save_settings(self._collect_settings())
        except Exception:
            pass
        try:
            self.engine.shutdown()
        except Exception:
            pass
        self.root.destroy()


# --------------------------------------------------------------------------- #
def main() -> int:
    missing = check_dependencies()
    if missing:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Missing dependencies",
            "The following Python packages are required but not installed:\n\n"
            + "\n".join(f"  • {m}" for m in sorted(set(missing)))
            + "\n\nInstall them with:\n\n    pip install -r requirements.txt\n",
        )
        root.destroy()
        return 1

    root = tk.Tk()
    try:
        root.iconbitmap(str(Path(__file__).with_name("assets") / "app.ico"))
    except Exception:
        pass
    DecartLivestreamApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
