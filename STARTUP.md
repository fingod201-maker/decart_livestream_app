# 🚀 Startup Instructions — Decart Livestream Studio

A quick, copy-paste guide to get the app running on Windows. For full
documentation see [README.md](README.md).

---

## 0 · Before you start (one-time)

You need three things:

| # | What | Where to get it |
|---|------|-----------------|
| 1 | **Python 3.10 or newer** | <https://www.python.org/downloads/> — during install, **tick "Add python.exe to PATH"** |
| 2 | **A Decart API key** | <https://platform.decart.ai> → API keys |
| 3 | **A webcam** (or a reference picture for the static source) | built-in or USB |

> The standard python.org installer includes **Tkinter**, which this app uses for
> its window. Don't use a stripped-down Python distribution without Tk.

---

## 1 · Easiest way — one double-click

1. Unzip `DecartLivestreamStudio.zip`.
2. Open the `decart_livestream_app` folder.
3. **Double-click `run.bat`.**

That's it. On the **first run** it will:

- create a local virtual environment (`.venv`),
- install all dependencies (this can take a few minutes),
- launch the app.

On later runs it skips straight to launching.

---

## 2 · Manual way (command line)

Open **Command Prompt** or **PowerShell** in the `decart_livestream_app` folder:

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

If `py` is not available, use `python` instead of `py -3.11`.

---

## 3 · Using the app (60 seconds)

1. **Paste your Decart API key** into section 1.
2. *(Optional)* click **Choose picture…** in section 4 to pick a reference
   portrait. Leave it empty for text-only editing.
3. Type or insert a **streaming description** in section 5 (use the **Template**
   dropdown for a well-structured prompt).
4. Pick **Desktop 16:9** or **Mobile 9:16** in section 7.
5. Click **● Connect & Start Stream** in section 8.
6. The transformed video appears in the preview on the right. Click the button
   again (**Disconnect**) to stop.

You can change the prompt or picture **mid-stream** with **Apply prompt /
picture update** — no reconnection needed.

---

## 4 · Build a standalone .exe (optional)

To make a single double-clickable program that needs no Python installed:

1. Double-click **`build_windows.bat`**.
2. When it finishes, your app is at:

   ```
   dist\DecartLivestreamStudio\DecartLivestreamStudio.exe
   ```

3. Double-click that `.exe` to run. (The whole `dist\DecartLivestreamStudio`
   folder is the distributable — zip it to share.)

---

## 5 · Troubleshooting startup

| Symptom | Fix |
|---------|-----|
| `'python' is not recognized` | Reinstall Python and tick **"Add python.exe to PATH"**, or use the full path to `python.exe`. |
| `No module named tkinter` | Install the standard python.org build (it bundles Tkinter). |
| `pip install` fails on `decart` / `livekit` | Make sure you're on **Python 3.10+** and the venv is activated (`.venv\Scripts\activate`). |
| App opens but **camera error** | Close other apps using the webcam; try a different **Camera index** (1, 2…), or switch the source to **Reference picture (static)**. |
| **Invalid API key** on connect | Re-copy the key from <https://platform.decart.ai> (no trailing spaces). |
| Antivirus flags the built `.exe` | Normal for unsigned PyInstaller apps — add an exclusion or run from source instead. |

---

## 6 · Where things live

```
decart_livestream_app/
├─ run.bat               ← double-click to start
├─ build_windows.bat     ← double-click to build the .exe
├─ app.py                ← the GUI
├─ decart_engine.py      ← the realtime engine
├─ config.py             ← models, resolutions, templates
├─ requirements.txt
└─ README.md             ← full documentation
```
