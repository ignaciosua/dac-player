#!/usr/bin/env python3
"""
DAC6 GUI — flat dark, bulk encode/decode, drag-and-drop, dual audio player.
"""
from __future__ import annotations
import json
import os
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import numpy as np

# ── ensure local bin/ (ffmpeg) is in PATH so both GUI and worker find it ─────
_BIN_DIR = Path(__file__).parent / "bin"
if _BIN_DIR.is_dir():
    os.environ["PATH"] = str(_BIN_DIR) + os.pathsep + os.environ.get("PATH", "")

# ── optional deps ─────────────────────────────────────────────────────────────
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _HAS_DND = True
except ImportError:
    _HAS_DND = False

try:
    import sounddevice as sd
    _HAS_SD = True
except ImportError:
    _HAS_SD = False


def _pick_output_device():
    """First non-HDMI stereo output device, or None to let sounddevice decide."""
    if not _HAS_SD:
        return None
    try:
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] >= 2 and "hdmi" not in d["name"].lower():
                return i
    except Exception:
        pass
    return None


_OUTPUT_DEVICE = _pick_output_device()

# ── palette ───────────────────────────────────────────────────────────────────
BG       = "#18181B"
SURFACE  = "#27272A"
BORDER   = "#3F3F46"
ACCENT   = "#3B82F6"
ACCENT_H = "#2563EB"
SUCCESS  = "#22C55E"
ERROR    = "#EF4444"
WARNING  = "#F59E0B"
TEXT     = "#F4F4F5"
MUTED    = "#A1A1AA"
MUTED2   = "#71717A"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_DIR  = Path(__file__).parent
WORKER   = APP_DIR / "dac6_worker.py"
PYTHON   = sys.executable
LOG_FILE = APP_DIR / "dac6.log"


def _log(line: str) -> None:
    """Append a line to dac6.log (best-effort, never raises)."""
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Audio backend
# ─────────────────────────────────────────────────────────────────────────────

class AudioBackend:
    """Wraps sounddevice OutputStream; each instance is independent."""

    def __init__(self):
        self._audio: np.ndarray | None = None  # (samples, channels) float32
        self._sr      = 44100
        self._shared  = [0]    # [current_sample] shared with callback closure
        self._volume  = [0.4]  # [0.0–1.0] shared with callback closure
        self._stream: "sd.OutputStream | None" = None
        self._playing = False
        self._on_error: "callable | None" = None

    def set_error_callback(self, cb: "callable"):
        self._on_error = cb

    def load(self, audio: np.ndarray, sr: int):
        self.stop()
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)
        elif audio.shape[0] < audio.shape[1]:
            audio = audio.T
        self._audio   = audio
        self._sr      = sr
        self._shared  = [0]
    
    def append_audio(self, audio_chunk: np.ndarray):
        """Append audio chunk to the existing buffer (for progressive streaming)."""
        if self._audio is None:
            self.load(audio_chunk, self._sr)
            return
        
        # Ensure same format
        audio_chunk = np.ascontiguousarray(audio_chunk, dtype=np.float32)
        if audio_chunk.ndim == 1:
            audio_chunk = audio_chunk.reshape(-1, 1)
        elif audio_chunk.shape[0] < audio_chunk.shape[1]:
            audio_chunk = audio_chunk.T
        
        # Concatenate to existing audio
        self._audio = np.concatenate([self._audio, audio_chunk], axis=0)
        _log(f"[BACKEND] Audio extended to {len(self._audio)} samples ({self.duration:.1f}s)")

    def set_volume(self, v: float):
        self._volume[0] = max(0.0, min(1.0, v))

    def play(self):
        if not _HAS_SD or self._audio is None:
            return
        self._close_stream()
        shared = self._shared
        vol    = self._volume
        audio  = self._audio

        def cb(outdata, frames, _t, _s):
            i = shared[0]
            n = min(frames, len(audio) - i)
            if n <= 0:
                outdata[:] = 0
                raise sd.CallbackStop()
            outdata[:n] = audio[i : i + n] * vol[0]
            if n < frames:
                outdata[n:] = 0
            shared[0] = i + n

        # on_finish must NOT acquire any lock — stream.close() may block
        # waiting for this callback, causing a deadlock.
        def on_finish():
            self._playing = False

        try:
            self._stream = sd.OutputStream(
                samplerate=self._sr,
                channels=self._audio.shape[1],
                device=_OUTPUT_DEVICE,
                callback=cb,
                finished_callback=on_finish,
            )
            self._stream.start()
            self._playing = True
        except Exception as exc:
            self._stream  = None
            self._playing = False
            if self._on_error:
                self._on_error(str(exc))

    def pause(self):
        self._close_stream()
        self._playing = False

    def stop(self):
        self._close_stream()
        self._playing    = False
        self._shared[0]  = 0

    def seek(self, frac: float):
        was = self._playing
        self._close_stream()
        self._playing = False
        if self._audio is not None:
            self._shared[0] = int(frac * len(self._audio))
        if was:
            self.play()

    def _close_stream(self):
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.abort()   # signal stop (non-blocking)
                s.close()   # wait for full teardown; on_finish is called here
            except Exception:
                pass

    @property
    def position(self) -> float:
        if self._audio is None or len(self._audio) == 0:
            return 0.0
        return min(1.0, self._shared[0] / len(self._audio))

    @property
    def duration(self) -> float:
        return 0.0 if self._audio is None else len(self._audio) / self._sr

    @property
    def is_playing(self) -> bool:
        return self._playing


# ─────────────────────────────────────────────────────────────────────────────
# Waveform canvas
# ─────────────────────────────────────────────────────────────────────────────

class WaveformCanvas(tk.Canvas):
    def __init__(self, master, on_seek=None, **kw):
        kw.setdefault("bg",           BG)
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("height",       80)
        super().__init__(master, **kw)
        self._on_seek   = on_seek
        self._audio_mono: np.ndarray | None = None
        self._pos_frac   = 0.0
        self.bind("<Button-1>",  self._click)
        self.bind("<B1-Motion>", self._click)
        self.bind("<Configure>", lambda _: self._draw_wave())

    def load(self, audio: np.ndarray):
        mono = audio[:, 0] if audio.ndim == 2 else audio
        self._audio_mono = mono.astype(np.float32)
        self._draw_wave()

    def set_position(self, frac: float):
        self._pos_frac = frac
        self._draw_pos()

    def clear(self):
        self._audio_mono = None
        self.delete("all")

    # ── drawing ──────────────────────────────────────────────────────────────

    def _draw_wave(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4 or self._audio_mono is None:
            return

        n    = len(self._audio_mono)
        step = max(1, n // w)
        mid  = h / 2
        sc   = mid * 0.88

        top, bot = [], []
        for x in range(w):
            s = x * step
            e = min(s + step, n)
            if s >= n:
                break
            chunk = self._audio_mono[s:e]
            if len(chunk) == 0:
                continue
            top.append((x, mid - float(np.max(chunk)) * sc))
            bot.append((x, mid - float(np.min(chunk)) * sc))

        if len(top) < 2:
            return

        poly = top + list(reversed(bot))
        flat = [v for pt in poly for v in pt]
        self.create_polygon(flat, fill="#2563EB", outline="", tags="wave")

        top_flat = [v for pt in top for v in pt]
        self.create_line(top_flat, fill=ACCENT, width=1, tags="wave")
        bot_flat = [v for pt in bot for v in pt]
        self.create_line(bot_flat, fill="#1D4ED8", width=1, tags="wave")

        self._draw_pos()

    def _draw_pos(self):
        self.delete("posline")
        w = self.winfo_width()
        h = self.winfo_height()
        x = int(self._pos_frac * w)
        self.create_line(x, 0, x, h, fill=TEXT, width=2, tags="posline")

    def _click(self, event):
        w = self.winfo_width()
        if w > 0 and self._on_seek:
            self._on_seek(max(0.0, min(1.0, event.x / w)))


# ─────────────────────────────────────────────────────────────────────────────
# Player widget
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_time(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m:02d}:{s:02d}"


class PlayerWidget(ctk.CTkFrame):
    """Self-contained audio player: file picker, waveform, volume, controls."""

    def __init__(self, master, title="Player", **kw):
        super().__init__(master, fg_color=SURFACE, corner_radius=10,
                         border_width=1, border_color=BORDER, **kw)
        self.columnconfigure(0, weight=1)
        self._backend  = AudioBackend()
        self._backend.set_volume(0.4)
        self._backend.set_error_callback(
            lambda msg: self.after(0, self._show_audio_error, msg)
        )
        self._audio: np.ndarray | None = None
        self._path: Path | None = None
        self._poll_id  = None

        # ── header ───────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        hdr.columnconfigure(1, weight=1)
        ctk.CTkLabel(hdr, text=title, font=("Segoe UI", 11, "bold"),
                     text_color=MUTED).grid(row=0, column=0, sticky="w")
        self._file_lbl = ctk.CTkLabel(hdr, text="— no file —",
                                       font=("Segoe UI", 11), text_color=MUTED2,
                                       anchor="e", wraplength=240)
        self._file_lbl.grid(row=0, column=1, sticky="e")

        # ── browse button ─────────────────────────────────────────────────────
        ctk.CTkButton(self, text="Browse", width=80, height=26,
                      fg_color=BORDER, hover_color="#52525B", text_color=TEXT,
                      font=("Segoe UI", 11), command=self._browse
                      ).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 6))

        # ── waveform ──────────────────────────────────────────────────────────
        self._wave = WaveformCanvas(self, on_seek=self._on_seek, height=80)
        self._wave.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))

        # ── transport controls ────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 4))
        ctrl.columnconfigure(3, weight=1)

        btn_kw = dict(width=72, height=30, font=("Segoe UI", 11),
                      fg_color=BORDER, hover_color="#52525B", text_color=TEXT)

        self._play_btn = ctk.CTkButton(ctrl, text="Play",
                                        command=self._toggle_play, **btn_kw)
        self._play_btn.grid(row=0, column=0, padx=(0, 5))

        ctk.CTkButton(ctrl, text="Stop",
                      command=self._stop, **btn_kw).grid(row=0, column=1)

        self._time_lbl = ctk.CTkLabel(ctrl, text="00:00 / 00:00",
                                       font=("Segoe UI", 10), text_color=MUTED2,
                                       anchor="e")
        self._time_lbl.grid(row=0, column=3, sticky="e")

        # ── volume row ────────────────────────────────────────────────────────
        vol_row = ctk.CTkFrame(self, fg_color="transparent")
        vol_row.grid(row=4, column=0, sticky="ew", padx=10, pady=(2, 10))
        vol_row.columnconfigure(1, weight=1)

        ctk.CTkLabel(vol_row, text="App vol", font=("Segoe UI", 10),
                     text_color=MUTED2).grid(row=0, column=0, padx=(0, 6))

        self._vol_slider = ctk.CTkSlider(
            vol_row, from_=0, to=100, height=14,
            fg_color=BORDER, progress_color=ACCENT,
            button_color="#94A3B8", button_hover_color=TEXT,
            command=self._set_volume,
        )
        self._vol_slider.set(40)
        self._vol_slider.grid(row=0, column=1, sticky="ew")

        self._vol_lbl = ctk.CTkLabel(vol_row, text="40%",
                                      font=("Segoe UI", 10), text_color=MUTED2,
                                      width=32, anchor="e")
        self._vol_lbl.grid(row=0, column=2, padx=(6, 0))

        if not _HAS_SD:
            ctk.CTkLabel(self, text="⚠ sounddevice not installed — playback disabled",
                         font=("Segoe UI", 10), text_color=WARNING
                         ).grid(row=5, column=0, pady=(0, 6))

    # ── public ────────────────────────────────────────────────────────────────

    def set_file(self, path: Path):
        self._path = path
        self._file_lbl.configure(text=path.name, text_color=MUTED2)
        threading.Thread(target=self._load_audio, args=(path,), daemon=True).start()

    # ── private ───────────────────────────────────────────────────────────────

    def _show_audio_error(self, msg: str):
        self._play_btn.configure(text="Play")
        self._file_lbl.configure(
            text=f"Audio error — change device in status bar: {msg[:60]}",
            text_color=ERROR,
        )

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Audio files", "*.wav *.mp3 *.flac *.ogg *.m4a *.opus"),
                       ("All files", "*.*")])
        if p:
            self.set_file(Path(p))

    def _load_audio(self, path: Path):
        if path.suffix.lower() == ".ncmp":
            self.after(0, lambda: self._file_lbl.configure(
                text="Decode the .ncmp first, then load the WAV here.",
                text_color=WARNING))
            return
        try:
            from audiotools import AudioSignal
            sig = AudioSignal(str(path))
            # .detach().cpu() before .numpy() — tensor may have autograd attached
            raw   = sig.audio_data.squeeze(0).detach().cpu().numpy()  # (ch, samples)
            audio = np.ascontiguousarray(raw.T, dtype=np.float32)     # (samples, ch)
            sr    = sig.sample_rate

            self._audio = audio
            self._backend.load(audio, sr)
            self.after(0, self._on_loaded)
        except Exception as exc:
            err = str(exc)[:80]
            self.after(0, lambda: self._file_lbl.configure(
                text=f"Error: {err}", text_color=ERROR))

    def _on_loaded(self):
        dur = self._backend.duration
        self._time_lbl.configure(text=f"00:00 / {_fmt_time(dur)}")
        self._file_lbl.configure(text_color=TEXT)
        if self._audio is not None:
            mono = self._audio[:, 0] if self._audio.ndim == 2 else self._audio
            self._wave.load(np.ascontiguousarray(mono))

    def _set_volume(self, val: float):
        self._backend.set_volume(val / 100)
        self._vol_lbl.configure(text=f"{int(val)}%")

    def _toggle_play(self):
        if self._backend.is_playing:
            self._backend.pause()
            self._play_btn.configure(text="Play")
            if self._poll_id:
                self.after_cancel(self._poll_id)
                self._poll_id = None
        else:
            self._backend.play()
            self._play_btn.configure(text="Pause")
            self._poll()

    def _stop(self):
        self._backend.stop()
        self._play_btn.configure(text="Play")
        if self._poll_id:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self._wave.set_position(0.0)
        self._time_lbl.configure(
            text=f"00:00 / {_fmt_time(self._backend.duration)}")

    def _on_seek(self, frac: float):
        self._backend.seek(frac)
        self._wave.set_position(frac)
        dur  = self._backend.duration
        pos_s = frac * dur
        self._time_lbl.configure(
            text=f"{_fmt_time(pos_s)} / {_fmt_time(dur)}")
        if self._backend.is_playing:
            self._play_btn.configure(text="Pause")
            if not self._poll_id:
                self._poll()

    def _poll(self):
        self._poll_id = None
        if not self._backend.is_playing:
            self._play_btn.configure(text="Play")
            self._wave.set_position(self._backend.position)
            return
        pos   = self._backend.position
        dur   = self._backend.duration
        self._wave.set_position(pos)
        self._time_lbl.configure(
            text=f"{_fmt_time(pos * dur)} / {_fmt_time(dur)}")
        self._poll_id = self.after(50, self._poll)


# ─────────────────────────────────────────────────────────────────────────────
# Compare tab
# ─────────────────────────────────────────────────────────────────────────────

class CompareTab(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.columnconfigure(0, weight=1)
        self._pairs: dict[str, dict] = {}   # ncmp_stem → {original, ncmp, decoded}

        # ── pair list ─────────────────────────────────────────────────────────
        list_card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=10)
        list_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        list_card.columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(list_card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        hdr.columnconfigure(0, weight=1)
        ctk.CTkLabel(hdr, text="File pairs", font=("Segoe UI", 11, "bold"),
                     text_color=MUTED).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(hdr, text="Browse .ncmp", width=100, height=26,
                      fg_color=BORDER, hover_color="#52525B", text_color=TEXT,
                      font=("Segoe UI", 11), command=self._browse_ncmp
                      ).grid(row=0, column=1)

        self._list = ctk.CTkScrollableFrame(
            list_card, fg_color="transparent", height=110,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color="#52525B",
        )
        self._list.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._list.columnconfigure(0, weight=1)

        self._empty_lbl = ctk.CTkLabel(
            self._list,
            text="No pairs yet — encode + decode files to populate this list",
            font=("Segoe UI", 11), text_color=MUTED2,
        )
        self._empty_lbl.grid(row=0, column=0, pady=12)

        # ── dual players ──────────────────────────────────────────────────────
        pf = ctk.CTkFrame(self, fg_color="transparent")
        pf.grid(row=1, column=0, sticky="ew")
        pf.columnconfigure(0, weight=1)
        pf.columnconfigure(1, weight=1)

        self.player_orig    = PlayerWidget(pf, title="ORIGINAL")
        self.player_decoded = PlayerWidget(pf, title="RESTORED")
        self.player_orig.grid(   row=0, column=0, sticky="nsew", padx=(0, 6))
        self.player_decoded.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

    # ── public API (called from Encode/Decode tabs) ───────────────────────────

    def register_encode(self, original: Path, ncmp: Path):
        key = ncmp.stem
        entry = self._pairs.setdefault(key, {"original": None, "ncmp": ncmp, "decoded": None})
        entry["original"] = original
        entry["ncmp"]     = ncmp
        self.after(0, self._refresh)

    def add_decoded(self, ncmp_path: Path, decoded_path: Path):
        key = ncmp_path.stem
        entry = self._pairs.setdefault(key, {"original": None, "ncmp": ncmp_path, "decoded": None})
        entry["decoded"] = decoded_path
        self.after(0, self._refresh)

    # ── private ───────────────────────────────────────────────────────────────

    def _browse_ncmp(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("DAC6 files", "*.ncmp"), ("All files", "*.*")])
        for p in (Path(x) for x in paths):
            self._pairs.setdefault(p.stem, {"original": None, "ncmp": p, "decoded": None})
        self._refresh()

    def _refresh(self):
        for w in self._list.winfo_children():
            if w is not self._empty_lbl:
                w.destroy()

        if not self._pairs:
            self._empty_lbl.grid()
            return
        self._empty_lbl.grid_remove()

        for i, pair in enumerate(self._pairs.values()):
            self._make_row(i, pair)

    def _make_row(self, idx: int, pair: dict):
        row = ctk.CTkFrame(self._list, fg_color=BORDER, corner_radius=6)
        row.grid(row=idx, column=0, sticky="ew", pady=(0, 4), padx=2)
        row.columnconfigure(0, weight=1)

        orig_name = pair["original"].name if pair["original"] else "unknown source"
        dec_name  = pair["decoded"].name  if pair["decoded"]  else "not restored yet"
        has_dec   = bool(pair["decoded"])

        ctk.CTkLabel(
            row, text=f"{orig_name}  ->  {dec_name}",
            font=("Segoe UI", 10),
            text_color=TEXT if has_dec else MUTED,
            anchor="w", wraplength=400,
        ).grid(row=0, column=0, sticky="w", padx=10, pady=6)

        if has_dec:
            ctk.CTkButton(
                row, text="Load", width=54, height=24,
                fg_color=ACCENT, hover_color=ACCENT_H, text_color=TEXT,
                font=("Segoe UI", 10),
                command=lambda p=pair: self._load_pair(p),
            ).grid(row=0, column=1, padx=(4, 8))

    def _load_pair(self, pair: dict):
        if pair.get("original") and pair["original"].exists():
            self.player_orig.set_file(pair["original"])
        if pair.get("decoded") and pair["decoded"].exists():
            self.player_decoded.set_file(pair["decoded"])


# ─────────────────────────────────────────────────────────────────────────────
# Bulk file list
# ─────────────────────────────────────────────────────────────────────────────

class FileRow(ctk.CTkFrame):
    ICONS = {"waiting": "...", "processing": ">>", "done": "OK", "error": "XX"}
    COLORS = {"waiting": MUTED, "processing": ACCENT, "done": SUCCESS, "error": ERROR}

    def __init__(self, master, path: Path, on_remove, **kw):
        super().__init__(master, fg_color=BORDER, corner_radius=6, **kw)
        self.path = path
        self.columnconfigure(1, weight=1)

        self._icon = ctk.CTkLabel(self, text="...", font=("Segoe UI", 13),
                                   text_color=MUTED, width=22)
        self._icon.grid(row=0, column=0, padx=(8, 4), pady=6)

        name_col = ctk.CTkFrame(self, fg_color="transparent")
        name_col.grid(row=0, column=1, sticky="ew")
        name_col.columnconfigure(0, weight=1)

        self._name = ctk.CTkLabel(name_col, text=path.name,
                                   font=("Segoe UI", 11, "bold"),
                                   text_color=TEXT, anchor="w")
        self._name.grid(row=0, column=0, sticky="w")

        self._info = ctk.CTkLabel(name_col, text="",
                                   font=("Segoe UI", 10), text_color=MUTED,
                                   anchor="w")
        self._info.grid(row=1, column=0, sticky="w")

        self._bar = ctk.CTkProgressBar(self, fg_color="#52525B",
                                        progress_color=ACCENT, height=4, width=80)
        self._bar.set(0)
        self._bar.grid(row=0, column=2, padx=8)
        self._bar.grid_remove()

        self._rm_btn = ctk.CTkButton(self, text="×", width=28, height=28,
                                      fg_color="transparent", hover_color="#52525B",
                                      text_color=MUTED, font=("Segoe UI", 14),
                                      command=lambda: on_remove(self))
        self._rm_btn.grid(row=0, column=3, padx=(0, 4))

    def set_status(self, status: str):
        self._icon.configure(text=self.ICONS.get(status, ""),
                             text_color=self.COLORS.get(status, MUTED))
        if status == "processing":
            self._bar.grid()
        elif status in ("done", "error"):
            self._bar.grid_remove()

    def set_progress(self, value: float):
        self._bar.set(value / 100)

    def set_info(self, text: str, color=None):
        self._info.configure(text=text, text_color=color or MUTED)

    def lock(self):
        self._rm_btn.configure(state="disabled")

    def unlock(self):
        self._rm_btn.configure(state="normal")


class BulkPanel(ctk.CTkFrame):
    """Drag-and-drop file queue with per-file status rows."""

    def __init__(self, master, accept_ext: list[str], on_process, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.columnconfigure(0, weight=1)
        self._accept_ext = accept_ext
        self._on_process = on_process
        self._rows: list[FileRow] = []

        # Drop zone / header
        self._drop_zone = ctk.CTkFrame(
            self, fg_color=SURFACE, corner_radius=10,
            border_width=1, border_color=BORDER,
        )
        self._drop_zone.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._drop_zone.columnconfigure(0, weight=1)
        self._drop_lbl = ctk.CTkLabel(
            self._drop_zone,
            text="Drop files here  or",
            font=("Segoe UI", 12), text_color=MUTED,
        )
        self._drop_lbl.grid(row=0, column=0, padx=14, pady=(14, 4))
        ctk.CTkButton(
            self._drop_zone, text="Add Files", width=100, height=30,
            fg_color=BORDER, hover_color="#52525B", text_color=TEXT,
            font=("Segoe UI", 12), command=self._browse,
        ).grid(row=1, column=0, pady=(0, 14))

        if _HAS_DND:
            for w in (self._drop_zone, self._drop_lbl):
                try:
                    w.drop_target_register(DND_FILES)
                    w.dnd_bind("<<Drop>>", self._on_drop)
                except Exception:
                    pass

        # File list
        self._list = ctk.CTkScrollableFrame(
            self, fg_color=SURFACE, corner_radius=10,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color="#52525B",
        )
        self._list.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._list.columnconfigure(0, weight=1)

        self._empty_lbl = ctk.CTkLabel(
            self._list, text="No files added yet",
            font=("Segoe UI", 11), text_color=MUTED2,
        )
        self._empty_lbl.grid(row=0, column=0, pady=16)

    # ── public ────────────────────────────────────────────────────────────────

    def add_paths(self, paths: list[Path]):
        existing = {r.path for r in self._rows}
        added = 0
        for p in paths:
            if p.suffix.lower() in self._accept_ext and p not in existing:
                self._add_row(p)
                existing.add(p)
                added += 1
        return added

    def get_paths(self) -> list[Path]:
        return [r.path for r in self._rows]

    def clear_done(self):
        for row in list(self._rows):
            if row._icon.cget("text") == FileRow.ICONS["done"]:
                self._remove_row(row)

    # ── private ───────────────────────────────────────────────────────────────

    def _browse(self):
        types_str = " ".join(f"*{e}" for e in self._accept_ext)
        paths = filedialog.askopenfilenames(
            filetypes=[(f"Supported ({types_str})", types_str),
                       ("All files", "*.*")]
        )
        if paths:
            self.add_paths([Path(p) for p in paths])

    def _on_drop(self, event):
        raw = event.data
        # tkinterdnd2 wraps paths with braces when they contain spaces
        paths = []
        if raw.startswith("{"):
            import re
            paths = [Path(p) for p in re.findall(r"\{([^}]+)\}", raw)]
        else:
            paths = [Path(p.strip()) for p in raw.split() if p.strip()]
        self.add_paths(paths)

    def _add_row(self, path: Path):
        if self._empty_lbl.winfo_ismapped():
            self._empty_lbl.grid_remove()
        row = FileRow(self._list, path, on_remove=self._remove_row)
        row.grid(row=len(self._rows), column=0, sticky="ew", pady=(0, 4), padx=4)
        self._rows.append(row)

    def _remove_row(self, row: FileRow):
        row.destroy()
        self._rows.remove(row)
        # Re-grid remaining
        for i, r in enumerate(self._rows):
            r.grid(row=i, column=0, sticky="ew", pady=(0, 4), padx=4)
        if not self._rows:
            self._empty_lbl.grid(row=0, column=0, pady=16)

    def get_row(self, path: Path) -> FileRow | None:
        for r in self._rows:
            if r.path == path:
                return r
        return None

    def lock_all(self):
        for r in self._rows:
            r.lock()

    def unlock_all(self):
        for r in self._rows:
            r.unlock()


# ─────────────────────────────────────────────────────────────────────────────
# Encode tab
# ─────────────────────────────────────────────────────────────────────────────

class EncodeTab(ctk.CTkFrame):
    def __init__(self, master, compare_tab: CompareTab, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.columnconfigure(0, weight=1)
        self._compare = compare_tab
        self._queue: list[Path] = []
        self._cancel = False
        self._proc: subprocess.Popen | None = None

        # Bulk panel
        self._bulk = BulkPanel(
            self,
            accept_ext=[".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus"],
            on_process=None,
        )
        self._bulk.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        # Settings
        sf = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=10)
        sf.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        sf.columnconfigure(1, weight=1)

        ctk.CTkLabel(sf, text="Codebooks / channel", font=("Segoe UI", 12),
                     text_color=MUTED).grid(row=0, column=0, sticky="w",
                                             padx=(14, 8), pady=8)
        self._cb_var = ctk.StringVar(value="9")
        self._cb_menu = ctk.CTkOptionMenu(sf, values=["3", "4", "6", "8", "9"],
                          variable=self._cb_var, width=90,
                          fg_color=BORDER, button_color="#52525B",
                          button_hover_color=ACCENT, text_color=TEXT,
                          dropdown_fg_color=SURFACE,
                          command=self._update_est
                          )
        self._cb_menu.grid(row=0, column=1, sticky="w", padx=(0, 14), pady=8)

        ctk.CTkLabel(sf, text="Model", font=("Segoe UI", 12),
                     text_color=MUTED).grid(row=1, column=0, sticky="w",
                                             padx=(14, 8), pady=8)
        self._model_var = ctk.StringVar(value="44khz")
        ctk.CTkOptionMenu(sf, values=["44khz", "24khz", "16khz"],
                          variable=self._model_var, width=90,
                          fg_color=BORDER, button_color="#52525B",
                          button_hover_color=ACCENT, text_color=TEXT,
                          dropdown_fg_color=SURFACE,
                          command=self._on_model_change
                          ).grid(row=1, column=1, sticky="w", padx=(0, 14), pady=8)

        ctk.CTkLabel(sf, text="Output folder", font=("Segoe UI", 12),
                     text_color=MUTED).grid(row=2, column=0, sticky="w",
                                             padx=(14, 8), pady=8)
        self._out_var = _outdir_widget(sf, row=2, default="out")

        ctk.CTkLabel(sf, text="Chunk size (seconds)", font=("Segoe UI", 12),
                     text_color=MUTED).grid(row=3, column=0, sticky="w",
                                             padx=(14, 8), pady=8)
        self._chunk_var = ctk.StringVar(value="10")
        chunk_values = ["3", "5"] + [str(i) for i in range(10, 310, 10)]
        ctk.CTkOptionMenu(sf, values=chunk_values,
                          variable=self._chunk_var, width=90,
                          fg_color=BORDER, button_color="#52525B",
                          button_hover_color=ACCENT, text_color=TEXT,
                          dropdown_fg_color=SURFACE
                          ).grid(row=3, column=1, sticky="w", padx=(0, 14), pady=8)

        self._est_lbl = ctk.CTkLabel(sf, text="Est. ~12 kbps (stereo, 6 cb)",
                                      font=("Segoe UI", 11), text_color=MUTED2)
        self._est_lbl.grid(row=4, column=0, columnspan=2, sticky="w",
                            padx=14, pady=(0, 10))

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        btn_row.columnconfigure(0, weight=1)

        self._enc_btn = ctk.CTkButton(
            btn_row, text="ENCODE ALL", height=44,
            font=("Segoe UI", 14, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_H,
            text_color=TEXT, command=self._start_all,
        )
        self._enc_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self._cancel_btn = ctk.CTkButton(
            btn_row, text="Cancel", width=80, height=44,
            fg_color="transparent", border_width=1,
            border_color=BORDER, text_color=MUTED,
            hover_color=BORDER, font=("Segoe UI", 12),
            command=self._do_cancel, state="disabled",
        )
        self._cancel_btn.grid(row=0, column=1)

    def _on_model_change(self, *_):
        """Update available codebook options based on selected model."""
        model = self._model_var.get()
        # Model limits: 44khz=9, 24khz=32, 16khz=12
        if model == "44khz":
            max_cb = 9
            options = ["3", "4", "6", "8", "9"]
        elif model == "24khz":
            max_cb = 32
            options = ["3", "4", "6", "8", "9", "12", "16", "24", "32"]
        else:  # 16khz
            max_cb = 12
            options = ["3", "4", "6", "8", "9", "12"]
        
        # Update dropdown options
        self._cb_menu.configure(values=options)
        
        # Adjust current selection if it exceeds the limit
        try:
            current = int(self._cb_var.get())
            if current > max_cb:
                self._cb_var.set(str(max_cb))
        except Exception:
            self._cb_var.set(options[-1])  # Default to max available
        
        self._update_est()

    def _update_est(self, *_):
        try:
            cb   = int(self._cb_var.get())
            kbps = 86.1 * cb * 10 / 1000
            self._est_lbl.configure(
                text=f"Est. ~{kbps:.1f} kbps/ch  (×2 stereo ≈ {kbps*2:.0f} kbps)")
        except Exception:
            pass

    def _start_all(self):
        paths = self._bulk.get_paths()
        if not paths:
            messagebox.showwarning("No files", "Add audio files first.")
            return
        self._queue   = list(paths)
        self._cancel  = False
        self._enc_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._bulk.lock_all()
        threading.Thread(target=self._process_queue, daemon=True).start()

    def _process_queue(self):
        for path in self._queue:
            if self._cancel:
                break
            row = self._bulk.get_row(path)
            if row is None:
                continue
            self.after(0, row.set_status, "processing")
            ncmp = self._run_one(path, row)
            if ncmp:
                self.after(0, self._compare.register_encode, path, ncmp)
                decoded = self._auto_decode(ncmp, row)
                if decoded:
                    self.after(0, self._compare.add_decoded, ncmp, decoded)
                    self.after(0, self._compare.player_orig.set_file, path)
                    self.after(0, self._compare.player_decoded.set_file, decoded)
        self.after(0, self._finish)

    def _run_one(self, path: Path, row: FileRow) -> "Path | None":
        cmd = [
            PYTHON, str(WORKER), "encode",
            str(path),
            "--out-dir",     self._out_var.get(),
            "--n-codebooks", self._cb_var.get(),
            "--model",       self._model_var.get(),
            "--chunk-seconds", self._chunk_var.get(),
        ]
        _log(f"\n{'='*60}")
        _log(f"[ENCODE] {' '.join(str(x) for x in cmd)}")
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        last_ncmp = None
        got_error = False
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            _log(line)  # log every line — JSON and raw tracebacks alike
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # non-JSON is in the log; nothing to show in UI
            t = msg.get("type")
            if t == "progress":
                self.after(0, row.set_progress, msg["value"])
            elif t == "status":
                self.after(0, row.set_info, msg["message"])
            elif t == "info":
                ch  = msg["channels"]
                dur = msg["duration"]
                sr  = msg["sample_rate"]
                info = f"{dur:.1f}s · {'Stereo' if ch==2 else 'Mono'} · {sr//1000} kHz"
                self.after(0, row.set_info, info)
                self.after(0, self._compare.player_orig.set_file, path)
            elif t == "done":
                last_ncmp = Path(msg["path"])
                kbps = msg.get("kbps", 0)
                sk   = msg.get("size_kb", 0)
                self.after(0, row.set_status, "done")
                self.after(0, row.set_info,
                           f"{sk:.1f} KB · {kbps:.2f} kbps", SUCCESS)
            elif t == "error":
                got_error = True
                self.after(0, row.set_status, "error")
                self.after(0, row.set_info, msg["message"], ERROR)
        self._proc.wait()
        _log(f"[ENCODE] exit code {self._proc.returncode}")
        # Only show a generic fallback if the worker didn't already send an error
        if last_ncmp is None and self._proc.returncode != 0 and not got_error:
            self.after(0, row.set_status, "error")
            self.after(0, row.set_info,
                       f"Worker crashed (exit {self._proc.returncode}). "
                       f"See {LOG_FILE.name} for details.", ERROR)
        return last_ncmp

    def _auto_decode(self, ncmp: Path, row: FileRow) -> "Path | None":
        """Decode .ncmp right after encoding so the compare tab has both sides."""
        out_dir = Path(self._out_var.get()) / "decoded"
        self.after(0, row.set_info, "Decoding for compare...", ACCENT)

        # Calculate chunk frames from chunk seconds (44.1kHz model default)
        # hop_length=512 for 44khz model, so frames = (chunk_s * 44100) / 512
        chunk_s = int(self._chunk_var.get())
        chunk_frames = int((chunk_s * 44100) / 512)
        
        cmd = [PYTHON, str(WORKER), "decode", str(ncmp),
               "--out-dir", str(out_dir),
               "--chunk-frames", str(chunk_frames)]
        _log(f"\n[AUTO-DECODE] {' '.join(str(x) for x in cmd)}")
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        decoded_path = None
        got_error = False
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            _log(line)
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = msg.get("type")
            if t == "progress":
                self.after(0, row.set_progress, msg["value"])
            elif t == "status":
                self.after(0, row.set_info, msg["message"])
            elif t == "done":
                decoded_path = Path(msg["path"])
                ds = msg.get("decode_s", 0)
                self.after(0, row.set_status, "done")
                self.after(0, row.set_info,
                           f"Encoded + decoded in {ds:.1f}s  —  ready to compare",
                           SUCCESS)
            elif t == "error":
                got_error = True
                self.after(0, row.set_info, f"Decode error: {msg['message']}", ERROR)
        proc.wait()
        _log(f"[AUTO-DECODE] exit code {proc.returncode}")
        if decoded_path is None and proc.returncode != 0 and not got_error:
            self.after(0, row.set_info,
                       f"Auto-decode crashed (exit {proc.returncode}). "
                       f"See {LOG_FILE.name}.", ERROR)
        return decoded_path

    def _do_cancel(self):
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def _finish(self):
        self._enc_btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        self._bulk.unlock_all()


# ─────────────────────────────────────────────────────────────────────────────
# Decode tab
# ─────────────────────────────────────────────────────────────────────────────

class DecodeTab(ctk.CTkFrame):
    def __init__(self, master, compare_tab: CompareTab, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.columnconfigure(0, weight=1)
        self._compare = compare_tab
        self._cancel  = False
        self._proc: subprocess.Popen | None = None

        self._bulk = BulkPanel(
            self,
            accept_ext=[".ncmp"],
            on_process=None,
        )
        self._bulk.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        sf = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=10)
        sf.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        sf.columnconfigure(1, weight=1)

        ctk.CTkLabel(sf, text="Output folder", font=("Segoe UI", 12),
                     text_color=MUTED).grid(row=0, column=0, sticky="w",
                                             padx=(14, 8), pady=8)
        self._out_var = _outdir_widget(sf, row=0, default="recovered")

        ctk.CTkLabel(sf, text="Export MP3", font=("Segoe UI", 12),
                     text_color=MUTED).grid(row=1, column=0, sticky="w",
                                             padx=(14, 8), pady=8)
        mp3_row = ctk.CTkFrame(sf, fg_color="transparent")
        mp3_row.grid(row=1, column=1, sticky="w", padx=(0, 14), pady=8)
        self._mp3_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(mp3_row, text="", variable=self._mp3_var,
                      progress_color=ACCENT, button_color=TEXT,
                      command=self._toggle_mp3).grid(row=0, column=0)
        self._mp3_opts = ctk.CTkFrame(mp3_row, fg_color="transparent")
        self._mp3_opts.grid(row=0, column=1, padx=(12, 0))
        self._br_var = ctk.StringVar(value="192")
        ctk.CTkOptionMenu(self._mp3_opts, values=["128", "192", "256", "320"],
                          variable=self._br_var, width=80,
                          fg_color=BORDER, button_color="#52525B",
                          button_hover_color=ACCENT, text_color=TEXT,
                          dropdown_fg_color=SURFACE,
                          ).grid(row=0, column=0)
        ctk.CTkLabel(self._mp3_opts, text="kbps", font=("Segoe UI", 11),
                     text_color=MUTED).grid(row=0, column=1, padx=(6, 0))
        self._mp3_opts.grid_remove()

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        btn_row.columnconfigure(0, weight=1)

        self._dec_btn = ctk.CTkButton(
            btn_row, text="DECODE ALL", height=44,
            font=("Segoe UI", 14, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_H,
            text_color=TEXT, command=self._start_all,
        )
        self._dec_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self._cancel_btn = ctk.CTkButton(
            btn_row, text="Cancel", width=80, height=44,
            fg_color="transparent", border_width=1,
            border_color=BORDER, text_color=MUTED,
            hover_color=BORDER, font=("Segoe UI", 12),
            command=self._do_cancel, state="disabled",
        )
        self._cancel_btn.grid(row=0, column=1)

        # ── playback preview ──────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Preview", font=("Segoe UI", 11, "bold"),
                     text_color=MUTED).grid(row=3, column=0, sticky="w",
                                             pady=(10, 4))
        self._player = PlayerWidget(self, title="Last decoded")
        self._player.grid(row=4, column=0, sticky="ew")

    def _toggle_mp3(self):
        if self._mp3_var.get():
            self._mp3_opts.grid()
        else:
            self._mp3_opts.grid_remove()

    def _start_all(self):
        paths = self._bulk.get_paths()
        if not paths:
            messagebox.showwarning("No files", "Add .ncmp files first.")
            return
        self._queue  = list(paths)
        self._cancel = False
        self._dec_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._bulk.lock_all()
        threading.Thread(target=self._process_queue, daemon=True).start()

    def _process_queue(self):
        for path in self._queue:
            if self._cancel:
                break
            row = self._bulk.get_row(path)
            if row is None:
                continue
            self.after(0, row.set_status, "processing")
            self._run_one(path, row)
        self.after(0, self._finish)

    def _run_one(self, path: Path, row: FileRow):
        cmd = [
            PYTHON, str(WORKER), "decode",
            str(path),
            "--out-dir", self._out_var.get(),
        ]
        if self._mp3_var.get():
            cmd += ["--mp3", "--mp3-bitrate", self._br_var.get()]

        _log(f"\n{'='*60}")
        _log(f"[DECODE] {' '.join(str(x) for x in cmd)}")
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        got_error = False
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            _log(line)
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = msg.get("type")
            if t == "progress":
                self.after(0, row.set_progress, msg["value"])
            elif t == "status":
                self.after(0, row.set_info, msg["message"])
            elif t == "info":
                ch   = msg["channels"]
                dur  = msg["duration"]
                n_cb = msg.get("n_codebooks", "?")
                self.after(0, row.set_info,
                           f"{dur:.1f}s · {'Stereo' if ch==2 else 'Mono'} · {n_cb} cb")
            elif t == "done":
                out_path = Path(msg["path"])
                ds = msg.get("decode_s", 0)
                self.after(0, row.set_status, "done")
                self.after(0, row.set_info, f"Restored in {ds:.1f}s", SUCCESS)
                self.after(0, self._player.set_file, out_path)
                self.after(0, self._compare.add_decoded, path, out_path)
            elif t == "error":
                got_error = True
                self.after(0, row.set_status, "error")
                self.after(0, row.set_info, msg["message"], ERROR)
        self._proc.wait()
        _log(f"[DECODE] exit code {self._proc.returncode}")
        if self._proc.returncode != 0 and not got_error:
            self.after(0, row.set_status, "error")
            self.after(0, row.set_info,
                       f"Worker crashed (exit {self._proc.returncode}). "
                       f"See {LOG_FILE.name}.", ERROR)

    def _do_cancel(self):
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def _finish(self):
        self._dec_btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        self._bulk.unlock_all()


# ─────────────────────────────────────────────────────────────────────────────
# Helper: output dir widget
# ─────────────────────────────────────────────────────────────────────────────

def _outdir_widget(parent, row: int, default: str) -> ctk.StringVar:
    var = ctk.StringVar(value=default)
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid(row=row, column=1, sticky="ew", padx=(0, 14), pady=8)
    frame.columnconfigure(0, weight=1)
    ctk.CTkEntry(frame, textvariable=var, fg_color=BORDER,
                 border_color=BORDER, text_color=TEXT,
                 font=("Segoe UI", 12)).grid(row=0, column=0, sticky="ew")

    def browse():
        d = filedialog.askdirectory()
        if d:
            var.set(d)

    ctk.CTkButton(frame, text="…", width=32, fg_color=BORDER,
                  hover_color="#52525B", text_color=TEXT,
                  command=browse).grid(row=0, column=1, padx=(6, 0))
    return var


# ─────────────────────────────────────────────────────────────────────────────
# Playlist Player Tab
# ─────────────────────────────────────────────────────────────────────────────

class PlaylistTab(ctk.CTkFrame):
    """Full-featured playlist player with shuffle, loop, and .ncmp decoding."""
    
    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.columnconfigure(0, weight=1)
        
        self._playlist: list[Path] = []  # All files in playlist
        self._current_idx = -1           # Current playing index
        self._shuffle = False
        self._loop_one = False
        self._loop_all = False
        self._shuffle_order: list[int] = []  # Shuffled indices
        self._temp_dir = APP_DIR / "temp_decode"
        self._temp_dir.mkdir(exist_ok=True)
        
        self._backend = AudioBackend()
        self._backend.set_volume(0.4)
        self._backend.set_error_callback(
            lambda msg: self.after(0, self._show_error, msg)
        )
        self._poll_id = None
        self._loading = False
        
        # Streaming state for .ncmp files
        self._stream_mode = False
        self._stream_chunks = []  # List of decoded audio chunks
        self._stream_current_chunk = 0
        self._stream_total_chunks = 0
        self._stream_ncmp_path = None
        self._stream_metadata = None
        self._stream_buffer_thread = None
        self._stream_stop_flag = False
        self._stream_complete_path = None  # Path to save complete decoded audio
        
        # Pre-decode worker for playlist
        self._predecode_thread = None
        self._predecode_stop_flag = False
        
        # ── Add files section ─────────────────────────────────────────────────
        add_card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=10)
        add_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        add_card.columnconfigure(0, weight=1)
        
        hdr = ctk.CTkFrame(add_card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        hdr.columnconfigure(0, weight=1)
        ctk.CTkLabel(hdr, text="Playlist Player", font=("Segoe UI", 12, "bold"),
                     text_color=TEXT).grid(row=0, column=0, sticky="w")
        
        btn_row = ctk.CTkFrame(add_card, fg_color="transparent")
        btn_row.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        
        btn_kw = dict(height=28, font=("Segoe UI", 11), 
                     fg_color=BORDER, hover_color="#52525B", text_color=TEXT)
        
        ctk.CTkButton(btn_row, text="Add Files", width=90,
                     command=self._add_files, **btn_kw).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkButton(btn_row, text="Add Folder", width=90,
                     command=self._add_folder, **btn_kw).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(btn_row, text="Clear", width=70,
                     command=self._clear_playlist, **btn_kw).grid(row=0, column=2)
        
        # ── Playlist display ──────────────────────────────────────────────────
        list_frame = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=10)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        
        ctk.CTkLabel(list_frame, text="Queue", font=("Segoe UI", 11, "bold"),
                    text_color=MUTED).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        
        self._list_scroll = ctk.CTkScrollableFrame(
            list_frame, fg_color=BORDER, corner_radius=6, height=120
        )
        self._list_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self._list_scroll.columnconfigure(0, weight=1)
        
        self._list_items: list[ctk.CTkFrame] = []
        
        # ── Now playing ───────────────────────────────────────────────────────
        now_card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=10)
        now_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        now_card.columnconfigure(0, weight=1)
        
        ctk.CTkLabel(now_card, text="Now Playing", font=("Segoe UI", 11, "bold"),
                    text_color=MUTED).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        
        self._now_playing_lbl = ctk.CTkLabel(
            now_card, text="— no track —", 
            font=("Segoe UI", 12), text_color=MUTED2, anchor="w"
        )
        self._now_playing_lbl.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
        
        self._status_lbl = ctk.CTkLabel(
            now_card, text="",
            font=("Segoe UI", 10), text_color=MUTED2, anchor="w"
        )
        self._status_lbl.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        
        # ── Waveform ──────────────────────────────────────────────────────────
        self._wave = WaveformCanvas(now_card, on_seek=self._on_seek, height=60)
        self._wave.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        
        # ── Time display ──────────────────────────────────────────────────────
        self._time_lbl = ctk.CTkLabel(
            now_card, text="00:00 / 00:00",
            font=("Segoe UI", 10), text_color=MUTED2
        )
        self._time_lbl.grid(row=4, column=0, sticky="e", padx=12, pady=(0, 6))
        
        # ── Transport controls ────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(now_card, fg_color="transparent")
        ctrl.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 10))
        ctrl.columnconfigure(0, weight=1)
        ctrl.columnconfigure(7, weight=1)
        
        ctrl_btn_kw = dict(height=40, font=("Segoe UI", 13),
                          fg_color=BORDER, hover_color="#52525B", text_color=TEXT,
                          border_width=0, corner_radius=8)
        
        ctk.CTkButton(ctrl, text="<<", width=55, command=self._seek_back,
                     **ctrl_btn_kw).grid(row=0, column=1, padx=2)
        ctk.CTkButton(ctrl, text="<", width=55, command=self._prev_track,
                     **ctrl_btn_kw).grid(row=0, column=2, padx=2)
        
        self._play_btn = ctk.CTkButton(ctrl, text="▶", width=70, height=40,
                                       command=self._toggle_play,
                                       fg_color=ACCENT, hover_color=ACCENT_H,
                                       text_color=TEXT, font=("Segoe UI", 14, "bold"),
                                       border_width=0, corner_radius=8)
        self._play_btn.grid(row=0, column=3, padx=4)
        
        ctk.CTkButton(ctrl, text="■", width=55, command=self._stop,
                     **ctrl_btn_kw).grid(row=0, column=4, padx=2)
        ctk.CTkButton(ctrl, text=">", width=55, command=self._next_track,
                     **ctrl_btn_kw).grid(row=0, column=5, padx=2)
        ctk.CTkButton(ctrl, text=">>", width=55, command=self._seek_forward,
                     **ctrl_btn_kw).grid(row=0, column=6, padx=2)
        
        # ── Mode toggles ──────────────────────────────────────────────────────
        mode_row = ctk.CTkFrame(now_card, fg_color="transparent")
        mode_row.grid(row=6, column=0, sticky="ew", padx=12, pady=(0, 10))
        
        self._shuffle_var = ctk.BooleanVar(value=False)
        self._loop_one_var = ctk.BooleanVar(value=False)
        self._loop_all_var = ctk.BooleanVar(value=False)
        
        ctk.CTkCheckBox(mode_row, text="Shuffle", variable=self._shuffle_var,
                       command=self._toggle_shuffle,
                       font=("Segoe UI", 10), text_color=TEXT,
                       fg_color=ACCENT, hover_color=ACCENT_H,
                       border_color=BORDER).grid(row=0, column=0, padx=(0, 12))
        
        ctk.CTkCheckBox(mode_row, text="Loop One", variable=self._loop_one_var,
                       command=self._toggle_loop_one,
                       font=("Segoe UI", 10), text_color=TEXT,
                       fg_color=ACCENT, hover_color=ACCENT_H,
                       border_color=BORDER).grid(row=0, column=1, padx=(0, 12))
        
        ctk.CTkCheckBox(mode_row, text="Loop All", variable=self._loop_all_var,
                       command=self._toggle_loop_all,
                       font=("Segoe UI", 10), text_color=TEXT,
                       fg_color=ACCENT, hover_color=ACCENT_H,
                       border_color=BORDER).grid(row=0, column=2)
        
        # ── Volume ────────────────────────────────────────────────────────────
        vol_card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=10)
        vol_card.grid(row=3, column=0, sticky="ew")
        vol_card.columnconfigure(1, weight=1)
        
        ctk.CTkLabel(vol_card, text="Volume", font=("Segoe UI", 10),
                    text_color=MUTED2).grid(row=0, column=0, padx=(12, 8), pady=10)
        
        self._vol_slider = ctk.CTkSlider(
            vol_card, from_=0, to=100, height=14,
            fg_color=BORDER, progress_color=ACCENT,
            button_color="#94A3B8", button_hover_color=TEXT,
            command=self._set_volume,
        )
        self._vol_slider.set(40)
        self._vol_slider.grid(row=0, column=1, sticky="ew", pady=10)
        
        self._vol_lbl = ctk.CTkLabel(vol_card, text="40%",
                                     font=("Segoe UI", 10), text_color=MUTED2,
                                     width=32, anchor="e")
        self._vol_lbl.grid(row=0, column=2, padx=(8, 12), pady=10)
        
    # ── Playlist management ───────────────────────────────────────────────────
    
    def _add_files(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Audio/DAC", "*.ncmp *.wav *.mp3 *.flac *.aac *.ogg *.m4a *.opus"),
                      ("All files", "*.*")]
        )
        if paths:
            for p in paths:
                self._playlist.append(Path(p))
            self._update_playlist_display()
            if self._shuffle:
                self._regenerate_shuffle()
            # Start pre-decoding .ncmp files in background
            self._start_predecode_worker()
    
    def _add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            folder_path = Path(folder)
            exts = {".ncmp", ".wav", ".mp3", ".flac", ".aac", ".ogg", ".m4a", ".opus"}
            files = [f for f in folder_path.iterdir() 
                    if f.is_file() and f.suffix.lower() in exts]
            files.sort()
            self._playlist.extend(files)
            self._update_playlist_display()
            if self._shuffle:
                self._regenerate_shuffle()
            # Start pre-decoding .ncmp files in background
            self._start_predecode_worker()
    
    def _clear_playlist(self):
        self._stop()
        # Stop pre-decode worker
        self._predecode_stop_flag = True
        self._playlist.clear()
        self._current_idx = -1
        self._shuffle_order.clear()
        self._update_playlist_display()
        self._now_playing_lbl.configure(text="— no track —", text_color=MUTED2)
        self._status_lbl.configure(text="")
    
    def _update_playlist_display(self):
        # Clear existing items
        for item in self._list_items:
            item.destroy()
        self._list_items.clear()
        
        # Add items
        for idx, path in enumerate(self._playlist):
            item = ctk.CTkFrame(self._list_scroll, fg_color=SURFACE, corner_radius=4)
            item.grid(row=idx, column=0, sticky="ew", pady=1)
            item.columnconfigure(1, weight=1)
            
            # Index
            idx_lbl = ctk.CTkLabel(item, text=f"{idx+1}.", width=30,
                                  font=("Segoe UI", 10), text_color=MUTED2)
            idx_lbl.grid(row=0, column=0, padx=(6, 4), pady=4)
            
            # Check if .ncmp file is cached
            is_ncmp = path.suffix.lower() == ".ncmp"
            cached_wav = self._temp_dir / f"{path.stem}_complete.wav" if is_ncmp else None
            is_cached = cached_wav.exists() if cached_wav else True  # Non-ncmp files always "ready"
            
            # Status icon (✔ for ready, ○ for pending)
            status_icon = "✔" if is_cached else "○"
            status_color = SUCCESS if is_cached else MUTED2
            if is_ncmp:
                status_lbl = ctk.CTkLabel(item, text=status_icon, width=20,
                                         font=("Segoe UI", 12, "bold"), text_color=status_color)
                status_lbl.grid(row=0, column=1, sticky="w", padx=(0, 4), pady=4)
            
            # Filename
            name_lbl = ctk.CTkLabel(item, text=path.name, anchor="w",
                                   font=("Segoe UI", 10), text_color=TEXT)
            name_lbl.grid(row=0, column=2 if is_ncmp else 1, sticky="ew", pady=4)
            
            if is_ncmp:
                item.columnconfigure(2, weight=1)
            
            # Play button - create with closure to capture idx correctly
            def make_play_command(track_idx):
                def cmd():
                    _log(f"[PLAYLIST] Button clicked for track {track_idx}")
                    self._play_index(track_idx)
                return cmd
            
            play_btn = ctk.CTkButton(item, text="▶", width=28, height=22,
                                    font=("Segoe UI", 9),
                                    fg_color=BORDER if is_cached else MUTED2,
                                    hover_color=ACCENT if is_cached else MUTED2,
                                    text_color=TEXT if is_cached else MUTED1,
                                    command=make_play_command(idx))
            play_btn.grid(row=0, column=3 if is_ncmp else 2, padx=(4, 6), pady=4)
            
            self._list_items.append(item)
    
    def _is_track_ready(self, idx: int) -> bool:
        """Check if a track is ready to play (cached if .ncmp)."""
        if idx < 0 or idx >= len(self._playlist):
            return False
        path = self._playlist[idx]
        if path.suffix.lower() == ".ncmp":
            cached_wav = self._temp_dir / f"{path.stem}_complete.wav"
            return cached_wav.exists()
        return True  # Non-ncmp files always ready
    
    def _regenerate_shuffle(self):
        import random
        self._shuffle_order = list(range(len(self._playlist)))
        random.shuffle(self._shuffle_order)
    
    # ── Playback control ──────────────────────────────────────────────────────
    
    def _play_index(self, idx: int):
        _log(f"[PLAYER] _play_index called with idx={idx}")
        if idx < 0 or idx >= len(self._playlist):
            return
        # Check if track is ready
        if not self._is_track_ready(idx):
            _log(f"[PLAYER] Track {idx} not ready (still decoding)")
            self._status_lbl.configure(text="Track not ready yet, please wait...", text_color=MUTED2)
            return
        _log(f"[PLAYER] Track {idx} is ready, loading and playing...")
        self._current_idx = idx
        self._load_and_play(self._playlist[idx])
    
    def _load_and_play(self, path: Path):
        if self._loading:
            return
        
        # Stop any previous streaming
        if self._stream_mode:
            self._stream_stop_flag = True
            self._stream_mode = False
        
        self._loading = True
        self._status_lbl.configure(text="Loading...", text_color=ACCENT)
        threading.Thread(target=self._load_track, args=(path,), daemon=True).start()
    
    def _load_track(self, path: Path):
        try:
            # Use progressive streaming for .ncmp files
            if path.suffix.lower() == ".ncmp":
                self._stream_ncmp_progressive(path)
                return
            
            # Load regular audio files normally
            from audiotools import AudioSignal
            sig = AudioSignal(str(path))
            raw = sig.audio_data.squeeze(0).detach().cpu().numpy()
            audio = np.ascontiguousarray(raw.T, dtype=np.float32)
            sr = sig.sample_rate
            
            self.after(0, self._on_track_loaded, path, audio, sr)
            
        except Exception as exc:
            err = str(exc)[:80]
            self.after(0, self._status_lbl.configure,
                      {"text": f"Error: {err}", "text_color": ERROR})
            self._loading = False
    
    def _stream_ncmp_progressive(self, path: Path):
        """Load .ncmp file - only plays if completely cached, otherwise waits for pre-decode."""
        try:
            # Check if we already have a complete decoded WAV cached
            cached_wav = self._temp_dir / f"{path.stem}_complete.wav"
            if cached_wav.exists():
                _log(f"[CACHE] Using cached complete WAV: {cached_wav}")
                # Load from cache and play normally
                from audiotools import AudioSignal
                sig = AudioSignal(str(cached_wav))
                raw = sig.audio_data.squeeze(0).detach().cpu().numpy()
                audio = np.ascontiguousarray(raw.T, dtype=np.float32)
                sr = sig.sample_rate
                
                # Pass original path, not cached_wav, for correct UI display
                self.after(0, self._on_track_loaded, path, audio, sr)
                return
            
            # Not cached - show waiting message
            _log(f"[DECODE] {path.name} not cached, decoding now...")
            self.after(0, self._status_lbl.configure,
                      {"text": "Decoding track, please wait...", "text_color": ACCENT})
            
            # Decode complete file synchronously
            success = self._predecode_full_ncmp(path, cached_wav)
            
            if success and cached_wav.exists():
                # Now load the decoded file
                from audiotools import AudioSignal
                sig = AudioSignal(str(cached_wav))
                raw = sig.audio_data.squeeze(0).detach().cpu().numpy()
                audio = np.ascontiguousarray(raw.T, dtype=np.float32)
                sr = sig.sample_rate
                
                # Pass original path, not cached_wav, for correct UI display
                self.after(0, self._on_track_loaded, path, audio, sr)
                # Update playlist display to show checkmark
                self.after(0, self._update_playlist_display)
            else:
                raise Exception("Failed to decode .ncmp file")
                
        except Exception as exc:
            err = str(exc)[:100]
            _log(f"[DECODE ERROR] {err}")
            self.after(0, self._status_lbl.configure,
                      {"text": f"Decode error: {err}", "text_color": ERROR})
            self._loading = False
    
    def _decode_ncmp_chunk(self, ncmp_path: Path, chunk_idx: int, chunk_frames: int) -> Path:
        """Decode a single chunk of .ncmp file and return the WAV path."""
        chunk_dir = self._temp_dir / "chunks" / ncmp_path.stem
        chunk_dir.mkdir(parents=True, exist_ok=True)
        
        # Expected output path
        chunk_wav = chunk_dir / f"chunk_{chunk_idx:04d}.wav"
        
        # Skip if already decoded
        if chunk_wav.exists():
            _log(f"[STREAM] Using cached chunk {chunk_idx}: {chunk_wav}")
            return chunk_wav
        
        # Decode this specific chunk
        cmd = [
            PYTHON, str(WORKER), "decode", str(ncmp_path),
            "--out-dir", str(chunk_dir),
            "--chunk-frames", str(chunk_frames),
            "--start-chunk", str(chunk_idx),
            "--num-chunks", "1"
        ]
        
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            _log(f"[STREAM ERROR] Chunk {chunk_idx} decode failed: {proc.stderr[:200]}")
            return None
        
        # Find the generated WAV file and rename it
        decoded_files = list(chunk_dir.glob("*.wav"))
        decoded_files = [f for f in decoded_files if not f.name.startswith("chunk_")]
        
        if decoded_files:
            # Rename to standardized chunk name
            try:
                decoded_files[0].replace(chunk_wav)
                _log(f"[STREAM] Decoded chunk {chunk_idx} saved as {chunk_wav}")
                return chunk_wav
            except Exception as e:
                _log(f"[STREAM ERROR] Failed to rename chunk {chunk_idx}: {e}")
                return decoded_files[0]  # Return original if rename fails
        
        return None
    
    def _stream_buffer_worker(self, path: Path, chunk_frames: int, sample_rate: int):
        """Background thread that decodes chunks ahead of playback and appends them to audio buffer."""
        from audiotools import AudioSignal
        
        for chunk_idx in range(1, self._stream_total_chunks):
            if self._stream_stop_flag:
                _log("[STREAM] Stopped by user")
                break
            
            _log(f"[STREAM] Decoding chunk {chunk_idx}/{self._stream_total_chunks}")
            self.after(0, self._status_lbl.configure,
                      {"text": f"Streaming ({chunk_idx}/{self._stream_total_chunks} chunks)...",
                       "text_color": ACCENT})
            
            # Decode next chunk
            chunk_wav = self._decode_ncmp_chunk(path, chunk_idx, chunk_frames)
            if chunk_wav is None:
                _log(f"[STREAM ERROR] Failed to decode chunk {chunk_idx}")
                continue
            
            # Load chunk audio
            try:
                sig = AudioSignal(str(chunk_wav))
                raw = sig.audio_data.squeeze(0).detach().cpu().numpy()
                audio_chunk = np.ascontiguousarray(raw.T, dtype=np.float32)
                
                # APPEND chunk to backend's audio buffer (this extends the playback)
                self._backend.append_audio(audio_chunk)
                self._stream_current_chunk = chunk_idx
                
                _log(f"[STREAM] Chunk {chunk_idx} appended (total: {self._backend.duration:.1f}s)")
                
            except Exception as exc:
                _log(f"[STREAM ERROR] Failed to load chunk {chunk_idx}: {exc}")
        
        # All chunks decoded - save complete audio to cache
        if not self._stream_stop_flag and self._backend._audio is not None:
            _log(f"[STREAM] All chunks decoded, saving to cache...")
            self.after(0, self._status_lbl.configure,
                      {"text": "Saving complete audio...", "text_color": SUCCESS})
            
            try:
                import soundfile as sf
                complete_audio = np.clip(self._backend._audio, -1.0, 1.0)
                sf.write(str(self._stream_complete_path), complete_audio, sample_rate)
                _log(f"[STREAM] Saved complete audio to {self._stream_complete_path}")
                
                self.after(0, self._status_lbl.configure,
                          {"text": f"Complete ({self._stream_total_chunks} chunks cached)", "text_color": SUCCESS})
            except Exception as exc:
                _log(f"[STREAM ERROR] Failed to save complete audio: {exc}")
        else:
            self.after(0, self._status_lbl.configure,
                      {"text": f"Streaming ({self._stream_current_chunk+1}/{self._stream_total_chunks} chunks)",
                       "text_color": SUCCESS})
    
    def _on_stream_chunk_loaded(self, path: Path, audio: np.ndarray, sample_rate: int):
        """Called when first chunk is loaded and ready to play."""
        self._loading = False
        self._now_playing_lbl.configure(text=f"{path.name} [STREAMING]", text_color=TEXT)
        
        # Show duration as estimated from first chunk
        chunk_dur = len(audio) / sample_rate
        total_dur = chunk_dur * self._stream_total_chunks
        self._time_lbl.configure(text=f"00:00 / ~{_fmt_time(total_dur)}")
        self._status_lbl.configure(text="Streaming...", text_color=ACCENT)
        
        # Update waveform with first chunk
        mono = audio[:, 0] if audio.ndim == 2 else audio
        self._wave.load(np.ascontiguousarray(mono))
        
        # Highlight current in playlist
        self._highlight_current()
        
        # Auto-play
        self._backend.play()
        self._play_btn.configure(text="⏸")
        self._poll_streaming()
    
    def _start_predecode_worker(self):
        """Start background worker to pre-decode all .ncmp files in playlist."""
        # Stop any existing worker
        self._predecode_stop_flag = True
        if self._predecode_thread and self._predecode_thread.is_alive():
            self._predecode_thread.join(timeout=0.5)
        
        # Start new worker
        self._predecode_stop_flag = False
        self._predecode_thread = threading.Thread(
            target=self._predecode_playlist_worker,
            daemon=True
        )
        self._predecode_thread.start()
        _log("[PREDECODE] Started playlist pre-decode worker")
    
    def _predecode_playlist_worker(self):
        """Background worker that pre-decodes all .ncmp files in playlist."""
        # Filter only .ncmp files
        ncmp_files = [f for f in self._playlist if f.suffix.lower() == ".ncmp"]
        
        if not ncmp_files:
            return
        
        _log(f"[PREDECODE] Found {len(ncmp_files)} .ncmp files to pre-decode")
        
        for idx, ncmp_path in enumerate(ncmp_files, 1):
            if self._predecode_stop_flag:
                _log("[PREDECODE] Stopped by user")
                break
            
            # Check if already cached
            cached_wav = self._temp_dir / f"{ncmp_path.stem}_complete.wav"
            if cached_wav.exists():
                _log(f"[PREDECODE] {idx}/{len(ncmp_files)} - {ncmp_path.name} already cached")
                continue
            
            _log(f"[PREDECODE] {idx}/{len(ncmp_files)} - Decoding {ncmp_path.name}...")
            
            # Only show status if not currently playing
            if not self._stream_mode:
                self.after(0, self._status_lbl.configure,
                          {"text": f"Pre-decoding playlist ({idx}/{len(ncmp_files)})...",
                           "text_color": MUTED2})
            
            # Decode complete .ncmp file
            success = self._predecode_full_ncmp(ncmp_path, cached_wav)
            
            if success:
                _log(f"[PREDECODE] {idx}/{len(ncmp_files)} - {ncmp_path.name} cached successfully")
                # Update playlist display to show checkmark
                self.after(0, self._update_playlist_display)
            else:
                _log(f"[PREDECODE] {idx}/{len(ncmp_files)} - {ncmp_path.name} failed")
        
        if not self._predecode_stop_flag:
            _log(f"[PREDECODE] Finished! All {len(ncmp_files)} .ncmp files cached")
            if not self._stream_mode:
                self.after(0, self._status_lbl.configure,
                          {"text": f"Playlist ready ({len(ncmp_files)} tracks cached)", "text_color": SUCCESS})
    
    def _predecode_full_ncmp(self, ncmp_path: Path, output_wav: Path) -> bool:
        """Decode a complete .ncmp file (all chunks) and save to output_wav."""
        try:
            # Read metadata
            import struct
            import json as json_lib
            
            with ncmp_path.open("rb") as f:
                if f.read(4) != b"NCMP":
                    return False
                f.read(2)
                hlen = struct.unpack("<I", f.read(4))[0]
                meta = json_lib.loads(f.read(hlen).decode())
            
            sample_rate = int(meta["sample_rate"])
            n_frames = int(meta["n_frames"])
            
            # Calculate chunks (10 seconds per chunk)
            chunk_seconds = 10
            hop_length = 512
            chunk_frames = int((chunk_seconds * sample_rate) / hop_length)
            total_chunks = max(1, (n_frames + chunk_frames - 1) // chunk_frames)
            
            # Decode all chunks
            all_audio = []
            
            for chunk_idx in range(total_chunks):
                if self._predecode_stop_flag:
                    return False
                
                chunk_wav = self._decode_ncmp_chunk(ncmp_path, chunk_idx, chunk_frames)
                if chunk_wav is None:
                    return False
                
                # Load chunk audio
                from audiotools import AudioSignal
                sig = AudioSignal(str(chunk_wav))
                raw = sig.audio_data.squeeze(0).detach().cpu().numpy()
                audio_chunk = np.ascontiguousarray(raw.T, dtype=np.float32)
                
                all_audio.append(audio_chunk)
            
            # Concatenate all chunks
            complete_audio = np.concatenate(all_audio, axis=0)
            
            # Save to cache
            import soundfile as sf
            complete_audio = np.clip(complete_audio, -1.0, 1.0)
            sf.write(str(output_wav), complete_audio, sample_rate)
            
            return True
            
        except Exception as exc:
            _log(f"[PREDECODE ERROR] {ncmp_path.name}: {exc}")
            return False
    
    def _on_track_loaded(self, path: Path, audio: np.ndarray, sr: int):
        self._loading = False
        
        try:
            # Load audio into backend (must be in main thread)
            _log(f"[PLAYER] Loading audio into backend...")
            self._backend.load(audio, sr)
            _log(f"[PLAYER] Track loaded: {path.name}, duration: {self._backend.duration:.1f}s")
            
            _log(f"[PLAYER] Updating UI labels...")
            self._now_playing_lbl.configure(text=path.name, text_color=TEXT)
            
            dur = self._backend.duration
            self._time_lbl.configure(text=f"00:00 / {_fmt_time(dur)}")
            self._status_lbl.configure(text="Ready", text_color=SUCCESS)
            
            # Update waveform
            _log(f"[PLAYER] Updating waveform...")
            mono = audio[:, 0] if audio.ndim == 2 else audio
            self._wave.load(np.ascontiguousarray(mono))
            
            # Highlight current in playlist
            _log(f"[PLAYER] Highlighting current track...")
            self._highlight_current()
            
            # Auto-play
            _log(f"[PLAYER] Starting playback...")
            self._backend.play()
            _log(f"[PLAYER] Backend.is_playing = {self._backend.is_playing}")
            self._play_btn.configure(text="⏸")
            self._poll()
            _log(f"[PLAYER] _on_track_loaded completed successfully")
        except Exception as e:
            _log(f"[PLAYER ERROR] Exception in _on_track_loaded: {e}")
            import traceback
            _log(f"[PLAYER ERROR] Traceback: {traceback.format_exc()}")
            self._status_lbl.configure(text=f"Error: {e}", text_color="#ef4444")
    
    def _highlight_current(self):
        for idx, item in enumerate(self._list_items):
            if idx == self._current_idx:
                item.configure(fg_color=BORDER)
            else:
                item.configure(fg_color=SURFACE)
    
    def _toggle_play(self):
        if not self._playlist:
            messagebox.showinfo("Empty Playlist", "Add files to playlist first.")
            return
        
        if self._current_idx < 0:
            # Start from beginning
            self._play_index(0)
            return
        
        if self._backend.is_playing:
            self._backend.pause()
            self._play_btn.configure(text="▶")
            if self._poll_id:
                self.after_cancel(self._poll_id)
                self._poll_id = None
        else:
            self._backend.play()
            self._play_btn.configure(text="⏸")
            self._poll()
    
    def _stop(self):
        # Stop streaming if active
        if self._stream_mode:
            self._stream_stop_flag = True
            self._stream_mode = False
            self._stream_chunks.clear()
            self._stream_current_chunk = 0
        
        self._backend.stop()
        self._play_btn.configure(text="▶")
        if self._poll_id:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        self._wave.set_position(0.0)
        if self._backend.duration > 0:
            self._time_lbl.configure(text=f"00:00 / {_fmt_time(self._backend.duration)}")
    
    def _prev_track(self):
        if not self._playlist:
            return
        
        if self._shuffle:
            # Find current in shuffle order and go back
            try:
                pos = self._shuffle_order.index(self._current_idx)
                # Try to find previous ready track
                for i in range(1, len(self._shuffle_order) + 1):
                    prev_pos = (pos - i) % len(self._shuffle_order)
                    prev_idx = self._shuffle_order[prev_pos]
                    if self._is_track_ready(prev_idx):
                        self._play_index(prev_idx)
                        return
                self._status_lbl.configure(text="No previous track ready", text_color=MUTED2)
            except ValueError:
                # Find first ready track
                for idx in self._shuffle_order:
                    if self._is_track_ready(idx):
                        self._play_index(idx)
                        return
        else:
            # Try to find previous ready track
            for i in range(1, len(self._playlist) + 1):
                prev_idx = (self._current_idx - i) % len(self._playlist)
                if self._is_track_ready(prev_idx):
                    self._play_index(prev_idx)
                    return
            self._status_lbl.configure(text="No previous track ready", text_color=MUTED2)
    
    def _next_track(self):
        if not self._playlist:
            return
        
        if self._shuffle:
            try:
                pos = self._shuffle_order.index(self._current_idx)
                # Try to find next ready track
                for i in range(1, len(self._shuffle_order) + 1):
                    next_pos = (pos + i) % len(self._shuffle_order)
                    next_idx = self._shuffle_order[next_pos]
                    if self._is_track_ready(next_idx):
                        self._play_index(next_idx)
                        return
                self._status_lbl.configure(text="No next track ready", text_color=MUTED2)
            except ValueError:
                # Find first ready track
                for idx in self._shuffle_order:
                    if self._is_track_ready(idx):
                        self._play_index(idx)
                        return
        else:
            # Try to find next ready track
            for i in range(1, len(self._playlist) + 1):
                next_idx = (self._current_idx + i) % len(self._playlist)
                if self._is_track_ready(next_idx):
                    self._play_index(next_idx)
                    return
            self._status_lbl.configure(text="No next track ready", text_color=MUTED2)
    
    def _seek_back(self):
        """Seek backward 10 seconds."""
        if self._backend.duration > 0:
            pos = self._backend.position
            new_pos = max(0.0, pos - (10.0 / self._backend.duration))
            self._backend.seek(new_pos)
            self._wave.set_position(new_pos)
    
    def _seek_forward(self):
        """Seek forward 10 seconds."""
        if self._backend.duration > 0:
            pos = self._backend.position
            new_pos = min(1.0, pos + (10.0 / self._backend.duration))
            self._backend.seek(new_pos)
            self._wave.set_position(new_pos)
    
    def _on_seek(self, frac: float):
        self._backend.seek(frac)
        self._wave.set_position(frac)
        dur = self._backend.duration
        pos_s = frac * dur
        self._time_lbl.configure(text=f"{_fmt_time(pos_s)} / {_fmt_time(dur)}")
    
    def _set_volume(self, val: float):
        self._backend.set_volume(val / 100)
        self._vol_lbl.configure(text=f"{int(val)}%")
    
    def _show_error(self, msg: str):
        self._status_lbl.configure(text=f"Audio error: {msg[:60]}", text_color=ERROR)
        self._play_btn.configure(text="▶")
    
    # ── Mode toggles ──────────────────────────────────────────────────────────
    
    def _toggle_shuffle(self):
        self._shuffle = self._shuffle_var.get()
        if self._shuffle:
            self._regenerate_shuffle()
        else:
            self._shuffle_order.clear()
    
    def _toggle_loop_one(self):
        self._loop_one = self._loop_one_var.get()
        if self._loop_one:
            self._loop_all_var.set(False)
            self._loop_all = False
    
    def _toggle_loop_all(self):
        self._loop_all = self._loop_all_var.get()
        if self._loop_all:
            self._loop_one_var.set(False)
            self._loop_one = False
    
    # ── Polling ───────────────────────────────────────────────────────────────
    
    def _poll_streaming(self):
        """Special polling for streaming .ncmp playback - audio buffer grows as chunks decode."""
        self._poll_id = None
        
        if not self._backend.is_playing:
            # Playback finished
            self._play_btn.configure(text="▶")
            self._wave.set_position(1.0)
            self._stream_mode = False
            
            # Handle loop modes
            if self._loop_one:
                self._play_index(self._current_idx)
            elif self._loop_all or len(self._playlist) > 0:
                self._next_track()
            
            return
        
        # Update time display and position
        pos = self._backend.position
        dur = self._backend.duration
        elapsed_s = pos * dur
        
        self._wave.set_position(pos)
        self._time_lbl.configure(text=f"{_fmt_time(elapsed_s)} / {_fmt_time(dur)}")
        
        # Continue polling
        self._poll_id = self.after(50, self._poll_streaming)
    
    def _poll(self):
        self._poll_id = None
        
        if not self._backend.is_playing:
            # Track finished
            _log(f"[POLL] Track finished. loop_one={self._loop_one}, loop_all={self._loop_all}")
            self._play_btn.configure(text="▶")
            self._wave.set_position(1.0)
            
            # Handle auto-advance to next track
            self._auto_advance_track()
            return
        
        pos = self._backend.position
        dur = self._backend.duration
        self._wave.set_position(pos)
        self._time_lbl.configure(text=f"{_fmt_time(pos * dur)} / {_fmt_time(dur)}")
        self._poll_id = self.after(50, self._poll)
    
    def _auto_advance_track(self):
        """Called when a track finishes playing - handles loop modes and auto-advance."""
        if self._loop_one:
            # Loop current track
            _log(f"[AUTO-ADVANCE] Loop One: replaying track {self._current_idx}")
            self._play_index(self._current_idx)
            return
        
        # Try to advance to next track
        if self._shuffle:
            try:
                pos = self._shuffle_order.index(self._current_idx)
                # Find next ready track
                for i in range(1, len(self._shuffle_order) + 1):
                    next_pos = (pos + i) % len(self._shuffle_order)
                    next_idx = self._shuffle_order[next_pos]
                    
                    # Check if we looped back to beginning
                    if i > 1 and next_pos <= pos and not self._loop_all:
                        _log(f"[AUTO-ADVANCE] Reached end of playlist, stopping (no loop_all)")
                        self._status_lbl.configure(text="Playlist finished", text_color=SUCCESS)
                        return
                    
                    if self._is_track_ready(next_idx):
                        _log(f"[AUTO-ADVANCE] Playing next track {next_idx} (shuffle)")
                        self._play_index(next_idx)
                        return
            except ValueError:
                pass
        else:
            # Sequential mode
            for i in range(1, len(self._playlist) + 1):
                next_idx = (self._current_idx + i) % len(self._playlist)
                
                # Check if we looped back to beginning
                if next_idx <= self._current_idx and not self._loop_all:
                    _log(f"[AUTO-ADVANCE] Reached end of playlist, stopping (no loop_all)")
                    self._status_lbl.configure(text="Playlist finished", text_color=SUCCESS)
                    return
                
                if self._is_track_ready(next_idx):
                    _log(f"[AUTO-ADVANCE] Playing next track {next_idx} (sequential)")
                    self._play_index(next_idx)
                    return
        
        _log(f"[AUTO-ADVANCE] No more ready tracks available")
        self._status_lbl.configure(text="Playlist finished", text_color=SUCCESS)


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────

if _HAS_DND:
    class _AppBase(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self):
            ctk.CTk.__init__(self)
            self.TkdndVersion = TkinterDnD._require(self)
else:
    _AppBase = ctk.CTk


class App(_AppBase):
    def __init__(self):
        super().__init__()
        self.title("DAC6 Audio Compressor")
        self.geometry("640x880")
        self.minsize(560, 600)
        self.configure(fg_color=BG)
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # ── header ──
        hdr = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=52)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.columnconfigure(1, weight=1)
        hdr.grid_propagate(False)
        ctk.CTkLabel(hdr, text="DAC6",
                     font=("Segoe UI", 20, "bold"), text_color=TEXT
                     ).grid(row=0, column=0, sticky="w", padx=20)
        self._gpu_lbl = ctk.CTkLabel(hdr, text="Checking…",
                                      font=("Segoe UI", 11), text_color=MUTED2)
        self._gpu_lbl.grid(row=0, column=1, sticky="e", padx=20)
        self.after(300, self._check_gpu)

        # ── tab bar ──
        tabs = ctk.CTkFrame(self, fg_color="#232326", corner_radius=0, height=42)
        tabs.grid(row=1, column=0, sticky="ew")
        tabs.grid_propagate(False)
        self._tab_btns: dict[str, ctk.CTkButton] = {}
        self._active   = "player"

        for col, (key, label) in enumerate(
            [("player", "PLAYER"), ("encode", "COMPRESS"), ("decode", "RESTORE"), ("compare", "A/B TEST")]
        ):
            active = key == "player"
            btn = ctk.CTkButton(
                tabs, text=label, width=110, height=42,
                font=("Segoe UI", 12, "bold"),
                fg_color=BG if active else "transparent",
                hover_color=BORDER, corner_radius=0,
                text_color=TEXT if active else MUTED,
                command=lambda k=key: self._switch(k),
            )
            btn.grid(row=0, column=col)
            self._tab_btns[key] = btn

        # ── scrollable content ──
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=BG, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color="#52525B",
        )
        self._scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=16)
        self._scroll.columnconfigure(0, weight=1)

        # Build tabs (compare first so encode/decode can reference it)
        self._compare_tab = CompareTab(self._scroll)
        self._encode_tab  = EncodeTab(self._scroll, compare_tab=self._compare_tab)
        self._decode_tab  = DecodeTab(self._scroll, compare_tab=self._compare_tab)
        self._player_tab  = PlaylistTab(self._scroll)

        self._tabs = {
            "encode":  self._encode_tab,
            "decode":  self._decode_tab,
            "compare": self._compare_tab,
            "player":  self._player_tab,
        }
        self._player_tab.grid(row=0, column=0, sticky="ew")
        for t in ("encode", "decode", "compare"):
            self._tabs[t].grid_remove()

        # ── status bar ──
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=28)
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_propagate(False)
        dev_name = ""
        if _HAS_SD and _OUTPUT_DEVICE is not None:
            try:
                dev_name = "  ·  " + sd.query_devices(_OUTPUT_DEVICE)["name"].split(":")[-1].strip()
            except Exception:
                pass
        ctk.CTkLabel(bar, text=f"DAC6  v1.0{dev_name}",
                     font=("Segoe UI", 10), text_color=MUTED2
                     ).grid(row=0, column=0, sticky="w", padx=14)

    def _switch(self, key: str):
        if key == self._active:
            return
        self._tabs[self._active].grid_remove()
        self._tabs[key].grid(row=0, column=0, sticky="ew")
        self._tab_btns[self._active].configure(
            fg_color="transparent", text_color=MUTED)
        self._tab_btns[key].configure(fg_color=BG, text_color=TEXT)
        self._active = key

    def _check_gpu(self):
        def _run():
            try:
                import torch
                if torch.cuda.is_available():
                    name  = torch.cuda.get_device_name(0)
                    mb    = torch.cuda.get_device_properties(0).total_memory // (1024**2)
                    short = name.replace("NVIDIA ", "").replace("GeForce ", "")
                    self.after(0, self._gpu_lbl.configure,
                               {"text": f"{short}  {mb//1024} GB",
                                "text_color": SUCCESS})
                else:
                    self.after(0, self._gpu_lbl.configure,
                               {"text": "CPU mode", "text_color": MUTED2})
            except Exception:
                self.after(0, self._gpu_lbl.configure,
                           {"text": "GPU: unknown", "text_color": MUTED2})
        threading.Thread(target=_run, daemon=True).start()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
