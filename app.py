"""
app.py  –  Conversation Assistant PoC
══════════════════════════════════════════
Layout:
  Oben  : Geräte-Auswahl (Mic + Speaker, je Ein/Aus + Dropdown)
           + Profil-Leiste (Dropdown + Kontext-Feld + Profile-Manager-Button)
  Links : Pegel-Panel  (Mic-VU + Speaker-VU + Silence-Timer)
  Rechts: Live-Transkription + KI-Vorschläge
"""

import tkinter as tk
from tkinter import scrolledtext, ttk, messagebox
import threading
import time
import math
import os

from mic_monitor    import MicMonitor, SpeakerMonitor
from transcriber    import Transcriber
from ai_suggestions import AISuggester
from audio_devices  import get_all_devices, get_default_mic, get_default_loopback, AudioDevice
from config import (
    SILENCE_LEVELS,
    HOTKEY_SEND_TO_AI, HOTKEY_CLEAR_TRANSCRIPT, HOTKEY_AUTOSEND_TOGGLE,
    AUTOSEND_ENABLED, AUTOSEND_INTERVAL_SEC, AUTOSEND_MIN_LINES,
    PROFILES_DIR, SYSTEM_PROMPT_FALLBACK,
)

# ── Farb-Schema ──────────────────────────────────────────────────────────────
C = {
    "bg":        "#1a1a2e",
    "panel":     "#16213e",
    "panel2":    "#0d1b2a",
    "accent":    "#0f3460",
    "text":      "#e0e0e0",
    "dim":       "#888888",
    "green":     "#00d26a",
    "yellow":    "#ffd166",
    "orange":    "#f77f00",
    "red":       "#e63946",
    "blue":      "#4cc9f0",
    "cyan":      "#00b4d8",
    "sug_bg":    "#1b4332",
    "new_chunk": "#1e3a5f",
    "ctx_bg":    "#1a2f1a",
    "on":        "#00d26a",
    "off":       "#555555",
    "on_bg":     "#0d2b1a",
    "off_bg":    "#1a1a1a",
    "entry_bg":  "#0f2035",
}

LEVEL_COLORS = [C["bg"], C["yellow"], C["orange"], C["red"]]
LEVEL_LABELS = ["OK – du sprichst", "⚠ 1 Min. still", "⚠⚠ 1,5 Min.", "🔴 2 Min. still!"]
DEFAULT_CTX  = 20
MAX_LINES    = 200
VU_BARS      = 16
VU_BAR_H     = 11
VU_BAR_GAP   = 2
VU_BAR_W     = 58
VU_X0        = 8
VU_Y0        = 8


# ══════════════════════════════════════════════════════════════════════════════
#  PROFIL-VERWALTUNG  (Dateisystem-Helfer)
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_profiles_dir():
    """Erstellt den profiles/-Ordner falls er nicht existiert."""
    os.makedirs(PROFILES_DIR, exist_ok=True)


def _list_profiles():
    """Gibt sortierte Liste der Profilnamen (ohne .txt) zurück."""
    _ensure_profiles_dir()
    names = [
        f[:-4] for f in os.listdir(PROFILES_DIR)
        if f.endswith(".txt")
    ]
    return sorted(names)


def _load_profile(name: str) -> str:
    """Lädt den System-Prompt eines Profils. Gibt Fallback zurück bei Fehler."""
    path = os.path.join(PROFILES_DIR, f"{name}.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return SYSTEM_PROMPT_FALLBACK


def _save_profile(name: str, content: str):
    """Speichert einen System-Prompt als Profil-Datei."""
    _ensure_profiles_dir()
    path = os.path.join(PROFILES_DIR, f"{name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _delete_profile(name: str):
    """Löscht eine Profil-Datei."""
    path = os.path.join(PROFILES_DIR, f"{name}.txt")
    if os.path.exists(path):
        os.remove(path)


# ══════════════════════════════════════════════════════════════════════════════
#  PROFIL-MANAGER-FENSTER
# ══════════════════════════════════════════════════════════════════════════════

class ProfileManagerWindow(tk.Toplevel):
    """
    Eigenständiges Fenster zum Verwalten von Profilen.
    Öffnet sich über den "Profile"-Button im Hauptfenster.
    Callback on_profiles_changed() wird aufgerufen wenn sich die Liste ändert.
    """

    def __init__(self, parent, current_profile: str, on_profiles_changed):
        super().__init__(parent)
        self.title("Profile verwalten")
        self.configure(bg=C["bg"])
        self.geometry("820x600")
        self.minsize(700, 480)
        self.resizable(True, True)

        self._on_profiles_changed = on_profiles_changed
        self._selected_profile    = None

        self._build_ui()
        self._refresh_list(select=current_profile)

        # Modal – aber nicht blockierend
        self.transient(parent)
        self.focus_force()

    # ── UI ──

    def _build_ui(self):
        # Haupt-Layout: Listenbereich links, Editor rechts
        main = tk.Frame(self, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=10, pady=10)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=3)
        main.rowconfigure(0, weight=1)

        # ── Linke Spalte: Profilliste + Buttons ──
        left = tk.Frame(main, bg=C["panel"], padx=8, pady=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.rowconfigure(1, weight=1)

        tk.Label(left, text="PROFILE", bg=C["panel"], fg=C["blue"],
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=0,
                                                     columnspan=2, sticky="w",
                                                     pady=(0, 6))

        self._listbox = tk.Listbox(
            left, bg=C["panel2"], fg=C["text"],
            selectbackground=C["accent"], selectforeground=C["text"],
            font=("Segoe UI", 10), relief="flat", bd=0,
            activestyle="none", exportselection=False
        )
        self._listbox.grid(row=1, column=0, columnspan=2, sticky="nsew",
                           pady=(0, 8))
        self._listbox.bind("<<ListboxSelect>>", self._on_list_select)

        btn_cfg = dict(bg=C["accent"], fg=C["text"], relief="flat",
                       font=("Segoe UI", 9), padx=8, pady=4, cursor="hand2")

        tk.Button(left, text="+ Neu", command=self._new_profile,
                  **btn_cfg).grid(row=2, column=0, sticky="ew", padx=(0, 3))
        tk.Button(left, text="🗑 Löschen", command=self._delete_profile,
                  **btn_cfg).grid(row=2, column=1, sticky="ew", padx=(3, 0))

        left.columnconfigure(0, weight=1)
        left.columnconfigure(1, weight=1)

        # ── Rechte Spalte: Name + Editor + Speichern ──
        right = tk.Frame(main, bg=C["panel"], padx=8, pady=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)

        tk.Label(right, text="Profilname:", bg=C["panel"], fg=C["dim"],
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")

        name_row = tk.Frame(right, bg=C["panel"])
        name_row.grid(row=1, column=0, sticky="ew", pady=(2, 8))
        name_row.columnconfigure(0, weight=1)

        self._name_var = tk.StringVar()
        tk.Entry(name_row, textvariable=self._name_var,
                 bg=C["entry_bg"], fg=C["text"],
                 insertbackground=C["text"], relief="flat",
                 font=("Segoe UI", 11)
                 ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        tk.Button(name_row, text="💾 Speichern",
                  command=self._save_profile,
                  bg=C["green"], fg="#000000",
                  font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=10, pady=4,
                  cursor="hand2"
                  ).grid(row=0, column=1)

        tk.Label(right, text="System-Prompt:", bg=C["panel"], fg=C["dim"],
                 font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w",
                                            pady=(6, 2))

        self._editor = scrolledtext.ScrolledText(
            right, bg=C["panel2"], fg=C["text"],
            font=("Consolas", 10), relief="flat", bd=4,
            wrap="word", insertbackground=C["text"]
        )
        self._editor.grid(row=3, column=0, sticky="nsew")

        # Statuszeile
        self._status_lbl = tk.Label(right, text="", bg=C["panel"],
                                    fg=C["dim"], font=("Segoe UI", 8))
        self._status_lbl.grid(row=4, column=0, sticky="w", pady=(4, 0))

    # ── Logik ──

    def _refresh_list(self, select: str = None):
        self._listbox.delete(0, "end")
        profiles = _list_profiles()
        for name in profiles:
            self._listbox.insert("end", name)
        # Auswahl setzen
        if select and select in profiles:
            idx = profiles.index(select)
            self._listbox.selection_set(idx)
            self._listbox.see(idx)
            self._load_into_editor(select)
        elif profiles:
            self._listbox.selection_set(0)
            self._load_into_editor(profiles[0])

    def _on_list_select(self, event=None):
        sel = self._listbox.curselection()
        if not sel:
            return
        name = self._listbox.get(sel[0])
        self._load_into_editor(name)

    def _load_into_editor(self, name: str):
        content = _load_profile(name)
        self._name_var.set(name)
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", content)
        self._selected_profile = name
        self._status_lbl.config(text=f"Geladen: {name}")

    def _save_profile(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Kein Name", "Bitte einen Profilnamen eingeben.",
                                   parent=self)
            return
        # Ungültige Zeichen für Dateinamen entfernen
        safe_name = "".join(c for c in name if c not in r'\/:*?"<>|')
        if not safe_name:
            messagebox.showwarning("Ungültiger Name",
                                   "Profilname enthält nur ungültige Zeichen.",
                                   parent=self)
            return
        content = self._editor.get("1.0", "end-1c").strip()
        if not content:
            messagebox.showwarning("Leerer Prompt",
                                   "Der System-Prompt darf nicht leer sein.",
                                   parent=self)
            return

        # Falls Name geändert wurde: altes Profil löschen
        if self._selected_profile and self._selected_profile != safe_name:
            _delete_profile(self._selected_profile)

        _save_profile(safe_name, content)
        self._selected_profile = safe_name
        self._name_var.set(safe_name)
        self._status_lbl.config(text=f"✔ Gespeichert: {safe_name}")
        self._refresh_list(select=safe_name)
        self._on_profiles_changed(safe_name)

    def _new_profile(self):
        # Vorlage aus Fallback-Prompt
        self._selected_profile = None
        self._name_var.set("Neues Profil")
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", SYSTEM_PROMPT_FALLBACK)
        self._editor.focus_set()
        self._status_lbl.config(text="Neues Profil – bitte Name und Prompt anpassen, dann Speichern.")

    def _delete_profile(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        name = self._listbox.get(sel[0])
        if not messagebox.askyesno(
                "Profil löschen",
                f"Profil '{name}' wirklich löschen?",
                parent=self):
            return
        _delete_profile(name)
        self._selected_profile = None
        self._editor.delete("1.0", "end")
        self._name_var.set("")
        self._status_lbl.config(text=f"Gelöscht: {name}")
        self._refresh_list()
        self._on_profiles_changed(None)


# ══════════════════════════════════════════════════════════════════════════════
#  HAUPTANWENDUNG
# ══════════════════════════════════════════════════════════════════════════════

class ConversationAssistantApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Conversation Assistant")
        root.configure(bg=C["bg"])
        root.geometry("1300x880")
        root.minsize(1000, 700)

        self.mic_monitor     = MicMonitor()
        self.speaker_monitor = SpeakerMonitor()
        self.transcriber     = Transcriber()
        self.ai_suggester    = AISuggester()

        self.transcriber.speaker_monitor = self.speaker_monitor

        self._mic_devices      = []
        self._loopback_devices = []
        self._active_mic       : AudioDevice | None = None
        self._active_loopback  : AudioDevice | None = None

        self._mic_enabled      = tk.BooleanVar(value=True)
        self._loopback_enabled = tk.BooleanVar(value=True)
        self._auto_scroll      = tk.BooleanVar(value=True)
        self._ai_ctx_lines     = tk.IntVar(value=DEFAULT_CTX)

        # Auto-Send
        self._autosend_enabled  = tk.BooleanVar(value=AUTOSEND_ENABLED)
        self._autosend_interval = tk.IntVar(value=AUTOSEND_INTERVAL_SEC)
        self._autosend_last     = time.time()
        self._autosend_last_linecount = 0

        # ── Profil-State ──
        # Aktives Profil: Name des gewählten Profils (oder None = Fallback)
        profiles = _list_profiles()
        default_profile = profiles[0] if profiles else None
        self._active_profile_name = default_profile
        self._profile_var = tk.StringVar(
            value=default_profile if default_profile else "– kein Profil –"
        )

        self._build_ui()
        self._load_devices()
        self._connect_backends()
        self._start_backends()
        self._register_hotkeys()
        self._update_loop()

    # ══════════════════════════════════════════════════════════════════════════
    #  UI AUFBAU
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self._build_device_panel()
        self._build_profile_bar()       # ← neu: zweite Zeile unter Geräten
        main = tk.Frame(self.root, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        main.columnconfigure(0, weight=2)
        main.columnconfigure(1, weight=5)
        main.rowconfigure(0, weight=1)
        self._build_level_panel(main)
        self._build_transcript_panel(main)
        self._build_statusbar()

    # ── Geräte-Panel ──────────────────────────────────────────────────────────

    def _build_device_panel(self):
        pnl = tk.Frame(self.root, bg=C["panel2"], pady=6)
        pnl.pack(fill="x", padx=10, pady=(10, 0))

        tk.Label(pnl, text="AUDIO-GERÄTE",
                 bg=C["panel2"], fg=C["blue"],
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(10, 16))

        # ── Mikrofon ──
        mic_frm = tk.Frame(pnl, bg=C["panel2"])
        mic_frm.pack(side="left", padx=(0, 8))

        self._mic_toggle_btn = tk.Button(
            mic_frm, text="🎙 MIC  ● ",
            bg=C["on_bg"], fg=C["on"],
            font=("Segoe UI", 9, "bold"),
            relief="flat", padx=8, pady=4, cursor="hand2",
            command=self._toggle_mic
        )
        self._mic_toggle_btn.pack(side="left", padx=(0, 6))

        self._mic_var = tk.StringVar(value="Lade…")
        self._mic_dropdown = ttk.Combobox(
            mic_frm, textvariable=self._mic_var,
            state="readonly", width=30, font=("Segoe UI", 9)
        )
        self._mic_dropdown.pack(side="left")
        self._mic_dropdown.bind("<<ComboboxSelected>>", self._on_mic_selected)

        tk.Frame(pnl, bg=C["accent"], width=2).pack(
            side="left", fill="y", padx=12, pady=4)

        # ── Lautsprecher ──
        lb_frm = tk.Frame(pnl, bg=C["panel2"])
        lb_frm.pack(side="left", padx=(0, 8))

        self._lb_toggle_btn = tk.Button(
            lb_frm, text="🔊 SPEAKER  ● ",
            bg=C["on_bg"], fg=C["on"],
            font=("Segoe UI", 9, "bold"),
            relief="flat", padx=8, pady=4, cursor="hand2",
            command=self._toggle_loopback
        )
        self._lb_toggle_btn.pack(side="left", padx=(0, 6))

        self._lb_var = tk.StringVar(value="Lade…")
        self._lb_dropdown = ttk.Combobox(
            lb_frm, textvariable=self._lb_var,
            state="readonly", width=30, font=("Segoe UI", 9)
        )
        self._lb_dropdown.pack(side="left")
        self._lb_dropdown.bind("<<ComboboxSelected>>", self._on_lb_selected)

        tk.Button(
            pnl, text="↻", bg=C["accent"], fg=C["text"],
            font=("Segoe UI", 11), relief="flat",
            padx=6, pady=2, cursor="hand2",
            command=self._load_devices
        ).pack(side="left", padx=8)

        self._device_status = tk.Label(
            pnl, text="", bg=C["panel2"], fg=C["dim"],
            font=("Segoe UI", 8)
        )
        self._device_status.pack(side="left", padx=4)

        tk.Frame(pnl, bg=C["accent"], width=2).pack(
            side="left", fill="y", padx=12, pady=4)

        # ── Auto-Send ──
        as_frm = tk.Frame(pnl, bg=C["panel2"])
        as_frm.pack(side="left", padx=(0, 8))

        self._autosend_btn = tk.Button(
            as_frm, text="⏱ AUTO  ○",
            bg=C["off_bg"], fg=C["off"],
            font=("Segoe UI", 9, "bold"),
            relief="flat", padx=8, pady=4, cursor="hand2",
            command=self._toggle_autosend
        )
        self._autosend_btn.pack(side="left", padx=(0, 6))

        tk.Label(as_frm, text="alle",
                 bg=C["panel2"], fg=C["dim"],
                 font=("Segoe UI", 9)).pack(side="left")

        tk.Spinbox(
            as_frm, from_=5, to=300,
            textvariable=self._autosend_interval,
            width=4, font=("Segoe UI", 9),
            bg=C["accent"], fg=C["text"],
            buttonbackground=C["accent"],
            relief="flat"
        ).pack(side="left", padx=2)

        tk.Label(as_frm, text="s  [Ctrl+Shift+S]",
                 bg=C["panel2"], fg=C["dim"],
                 font=("Segoe UI", 9)).pack(side="left")

        self._autosend_countdown = tk.Label(
            as_frm, text="",
            bg=C["panel2"], fg=C["blue"],
            font=("Segoe UI", 9, "bold")
        )
        self._autosend_countdown.pack(side="left", padx=(8, 0))

    # ── Profil-Leiste ─────────────────────────────────────────────────────────

    def _build_profile_bar(self):
        """
        Zweite Leiste direkt unter den Geräten.
        Inhalt: Profil-Dropdown | [Profile verwalten] | Kontext-Feld
        """
        bar = tk.Frame(self.root, bg=C["panel2"], pady=5)
        bar.pack(fill="x", padx=10, pady=(2, 4))

        tk.Label(bar, text="Profil:",
                 bg=C["panel2"], fg=C["blue"],
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(10, 4))

        # Profil-Dropdown
        profiles = _list_profiles()
        values   = profiles if profiles else ["– kein Profil –"]
        self._profile_dropdown = ttk.Combobox(
            bar, textvariable=self._profile_var,
            values=values, state="readonly",
            width=22, font=("Segoe UI", 9)
        )
        self._profile_dropdown.pack(side="left", padx=(0, 6))
        self._profile_dropdown.bind("<<ComboboxSelected>>", self._on_profile_selected)

        # Profile-Manager-Button
        tk.Button(
            bar, text="⚙ Profile verwalten",
            bg=C["accent"], fg=C["text"],
            font=("Segoe UI", 9), relief="flat",
            padx=8, pady=3, cursor="hand2",
            command=self._open_profile_manager
        ).pack(side="left", padx=(0, 16))

        # Trennlinie
        tk.Frame(bar, bg=C["accent"], width=2).pack(
            side="left", fill="y", padx=(0, 12), pady=3)

        # Kontext-Feld (Thema / Position / freier Text)
        tk.Label(bar, text="Kontext:",
                 bg=C["panel2"], fg=C["blue"],
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))

        self._context_var = tk.StringVar()
        context_entry = tk.Entry(
            bar, textvariable=self._context_var,
            bg=C["entry_bg"], fg=C["text"],
            insertbackground=C["text"],
            relief="flat", font=("Segoe UI", 9),
            width=55
        )
        context_entry.pack(side="left", padx=(0, 8))

        # Placeholder-Verhalten
        _placeholder = "z.B. Thema: KI-Regulierung · Ich bin Pro · Konter den letzten Punkt"
        context_entry.insert(0, _placeholder)
        context_entry.config(fg=C["dim"])

        def _on_focus_in(e):
            if self._context_var.get() == _placeholder:
                context_entry.delete(0, "end")
                context_entry.config(fg=C["text"])

        def _on_focus_out(e):
            if not self._context_var.get().strip():
                context_entry.insert(0, _placeholder)
                context_entry.config(fg=C["dim"])

        context_entry.bind("<FocusIn>",  _on_focus_in)
        context_entry.bind("<FocusOut>", _on_focus_out)
        self._context_placeholder = _placeholder

        # ── Expand-Button: öffnet Popup für mehrzeilige Eingabe ──
        tk.Button(
            bar, text="⤢",
            bg=C["accent"], fg=C["text"],
            font=("Segoe UI", 10), relief="flat",
            padx=5, pady=2, cursor="hand2",
            command=lambda: self._open_context_editor(context_entry)
        ).pack(side="left", padx=(2, 8))

        # Label zeigt aktives Profil klein an
        self._active_profile_lbl = tk.Label(
            bar, text=self._fmt_active_profile(),
            bg=C["panel2"], fg=C["dim"],
            font=("Segoe UI", 8)
        )
        self._active_profile_lbl.pack(side="right", padx=(0, 10))

    def _fmt_active_profile(self) -> str:
        name = self._active_profile_name
        return f"aktiv: {name}" if name else "aktiv: Fallback"

    # ── Pegel-Panel ──────────────────────────────────────────────────────────

    def _build_level_panel(self, parent):
        pnl = tk.Frame(parent, bg=C["panel"])
        pnl.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        tk.Label(pnl, text="🔊  PEGEL",
                 bg=C["panel"], fg=C["blue"],
                 font=("Segoe UI", 11, "bold")).pack(pady=(12, 2))

        vu_w = (VU_X0 * 3 + VU_BAR_W * 2)
        vu_h = VU_Y0 + VU_BARS * (VU_BAR_H + VU_BAR_GAP) + 20
        self.vu_canvas = tk.Canvas(
            pnl, width=vu_w, height=vu_h,
            bg=C["panel"], highlightthickness=0
        )
        self.vu_canvas.pack(pady=4, padx=8)
        self._build_vu_canvas()

        rms_row = tk.Frame(pnl, bg=C["panel"])
        rms_row.pack(fill="x", padx=8, pady=(0, 4))
        self.mic_rms_label = tk.Label(
            rms_row, text="🎙 0",
            bg=C["panel"], fg=C["green"],
            font=("Segoe UI", 8)
        )
        self.mic_rms_label.pack(side="left", expand=True)
        self.spk_rms_label = tk.Label(
            rms_row, text="🔊 0",
            bg=C["panel"], fg=C["cyan"],
            font=("Segoe UI", 8)
        )
        self.spk_rms_label.pack(side="right", expand=True)

        self.silence_label = tk.Label(
            pnl, text="Still seit: 0 s",
            bg=C["panel"], fg=C["dim"],
            font=("Segoe UI", 10)
        )
        self.silence_label.pack(pady=(4, 2))

        tk.Label(pnl, text="Warnstufen",
                 bg=C["panel"], fg=C["dim"],
                 font=("Segoe UI", 9)).pack(pady=(8, 2))

        self.level_indicators = []
        for lbl in LEVEL_LABELS:
            frm = tk.Frame(pnl, bg=C["panel"])
            frm.pack(fill="x", padx=12, pady=1)
            dot = tk.Label(frm, text="● ", bg=C["panel"],
                           fg=C["accent"], font=("Segoe UI", 13))
            dot.pack(side="left", padx=(0, 5))
            tk.Label(frm, text=lbl, bg=C["panel"], fg=C["dim"],
                     font=("Segoe UI", 8), anchor="w").pack(side="left")
            self.level_indicators.append(dot)

        tk.Label(pnl, text="Sprach-Schwelle (RMS)",
                 bg=C["panel"], fg=C["dim"],
                 font=("Segoe UI", 8)).pack(pady=(14, 0))
        self.threshold_var = tk.IntVar(value=50)
        tk.Scale(pnl, from_=50, to=1500, variable=self.threshold_var,
                 orient="horizontal", bg=C["panel"], fg=C["text"],
                 troughcolor=C["accent"], highlightthickness=0,
                 command=self._on_threshold_change).pack(fill="x", padx=12)
        self.rms_thresh_label = tk.Label(pnl, text="Schwelle: 50",
                                         bg=C["panel"], fg=C["dim"],
                                         font=("Segoe UI", 8))
        self.rms_thresh_label.pack()

        tk.Label(pnl, text="KI-Kontext (letzte N Zeilen)",
                 bg=C["panel"], fg=C["dim"],
                 font=("Segoe UI", 8)).pack(pady=(14, 0))
        tk.Scale(pnl, from_=5, to=60, variable=self._ai_ctx_lines,
                 orient="horizontal", bg=C["panel"], fg=C["text"],
                 troughcolor=C["accent"], highlightthickness=0
                 ).pack(fill="x", padx=12)
        self._ctx_lbl = tk.Label(pnl, text=f"→ {DEFAULT_CTX} Zeilen",
                                 bg=C["panel"], fg=C["blue"],
                                 font=("Segoe UI", 8))
        self._ctx_lbl.pack(pady=(0, 10))

    def _build_vu_canvas(self):
        self.vu_canvas.delete("all")
        self._mic_bars  = []
        self._spk_bars  = []

        mid_x_mic = VU_X0 + VU_BAR_W // 2
        mid_x_spk = VU_X0 * 2 + VU_BAR_W + VU_BAR_W // 2
        self.vu_canvas.create_text(
            mid_x_mic, VU_Y0 - 4, text="MIC",
            fill=C["green"], font=("Segoe UI", 7, "bold"), anchor="s"
        )
        self.vu_canvas.create_text(
            mid_x_spk, VU_Y0 - 4, text="SPK",
            fill=C["cyan"], font=("Segoe UI", 7, "bold"), anchor="s"
        )

        for i in range(VU_BARS):
            y  = VU_Y0 + i * (VU_BAR_H + VU_BAR_GAP)
            y2 = y + VU_BAR_H

            x0_mic = VU_X0
            x1_mic = VU_X0 + VU_BAR_W
            self.vu_canvas.create_rectangle(
                x0_mic, y, x1_mic, y2, fill=C["accent"], outline="")
            bar_mic = self.vu_canvas.create_rectangle(
                x0_mic, y, x0_mic, y2, fill=C["green"], outline="")
            self._mic_bars.append((bar_mic, x0_mic, y, y2, VU_BAR_W))

            x0_spk = VU_X0 * 2 + VU_BAR_W
            x1_spk = x0_spk + VU_BAR_W
            self.vu_canvas.create_rectangle(
                x0_spk, y, x1_spk, y2, fill=C["accent"], outline="")
            bar_spk = self.vu_canvas.create_rectangle(
                x0_spk, y, x0_spk, y2, fill=C["cyan"], outline="")
            self._spk_bars.append((bar_spk, x0_spk, y, y2, VU_BAR_W))

    def _update_vu(self, bars: list, rms_normalized: float, base_color_low: str):
        n      = len(bars)
        level  = min(1.0, math.log1p(rms_normalized * 8) / math.log1p(8))
        filled = int(level * n)
        for i, (bid, x0, y0, y1, bw) in enumerate(bars):
            if i < filled:
                r = i / n
                color = (base_color_low if r < 0.6
                         else C["yellow"] if r < 0.85
                         else C["red"])
                fw = max(1, int(bw * min(1.0, (level * n - i + 1))))
                self.vu_canvas.coords(bid, x0, y0, x0 + fw, y1)
                self.vu_canvas.itemconfig(bid, fill=color)
            else:
                self.vu_canvas.coords(bid, x0, y0, x0, y1)

    # ── Transkript-Panel ──────────────────────────────────────────────────────

    def _build_transcript_panel(self, parent):
        pnl = tk.Frame(parent, bg=C["panel"])
        pnl.grid(row=0, column=1, sticky="nsew")
        pnl.rowconfigure(1, weight=3)
        pnl.rowconfigure(4, weight=2)
        pnl.columnconfigure(0, weight=1)

        hdr = tk.Frame(pnl, bg=C["panel"])
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        tk.Label(hdr, text="📝   LIVE TRANSKRIPTION",
                 bg=C["panel"], fg=C["blue"],
                 font=("Segoe UI", 11, "bold")).pack(side="left")

        btn = {"bg": C["accent"], "fg": C["text"], "relief": "flat",
               "padx": 8, "pady": 3, "cursor": "hand2", "font": ("Segoe UI", 9)}
        tk.Button(hdr, text="🤖 An KI  [Ctrl+Shift+A]",
                  command=self._send_to_ai, **btn).pack(side="right", padx=(4, 0))
        tk.Button(hdr, text="🗑 Leeren  [Ctrl+Shift+C]",
                  command=self._clear_transcript, **btn).pack(side="right", padx=4)
        tk.Checkbutton(
            hdr, text="Auto-Scroll", variable=self._auto_scroll,
            bg=C["panel"], fg=C["dim"], selectcolor=C["accent"],
            activebackground=C["panel"], font=("Segoe UI", 9)
        ).pack(side="right", padx=8)

        info = tk.Frame(pnl, bg=C["panel"])
        info.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 0))
        self._line_count_lbl = tk.Label(info, text="0 Zeilen",
                                        bg=C["panel"], fg=C["dim"],
                                        font=("Segoe UI", 8))
        self._line_count_lbl.pack(side="left")
        self._ctx_info_lbl = tk.Label(
            info, text=f"  ·  KI bekommt letzte {DEFAULT_CTX} Zeilen",
            bg=C["panel"], fg=C["blue"], font=("Segoe UI", 8))
        self._ctx_info_lbl.pack(side="left")
        tk.Label(info, text=f"  ·  Puffer rollt nach {MAX_LINES} Zeilen",
                 bg=C["panel"], fg=C["dim"],
                 font=("Segoe UI", 8)).pack(side="left")

        self.transcript_text = scrolledtext.ScrolledText(
            pnl, bg="#0a0f1e", fg=C["text"],
            font=("Consolas", 10), relief="flat", bd=4,
            wrap="word", insertbackground=C["text"],
            selectbackground=C["accent"]
        )
        self.transcript_text.grid(row=1, column=0, sticky="nsew",
                                  padx=10, pady=(6, 0))
        self.transcript_text.tag_configure("new_chunk",  background=C["new_chunk"])
        self.transcript_text.tag_configure("ai_context", background=C["ctx_bg"],
                                           foreground="#c8f7c5")
        self.transcript_text.tag_configure("src_mic",      foreground="#e0e0e0")
        self.transcript_text.tag_configure("src_loopback", foreground="#ff6b6b")
        self.transcript_text.tag_configure("src_mixed",    foreground="#e0e0e0")
        self.transcript_text.tag_configure("src_edit",     foreground="#00d26a")
        self.transcript_text.tag_raise("src_edit")
        self.transcript_text.tag_raise("new_chunk")

        self._is_whisper_insert = False
        self.transcript_text.bind("<KeyRelease>", self._on_key_edit)

        ai_hdr = tk.Frame(pnl, bg=C["panel"])
        ai_hdr.grid(row=3, column=0, sticky="ew", padx=10, pady=(8, 0))
        tk.Label(ai_hdr, text="💡  KI-VORSCHLÄGE",
                 bg=C["panel"], fg=C["blue"],
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        self.ai_status = tk.Label(ai_hdr, text="",
                                  bg=C["panel"], fg=C["dim"],
                                  font=("Segoe UI", 9))
        self.ai_status.pack(side="right")

        self.ai_text = scrolledtext.ScrolledText(
            pnl, bg=C["sug_bg"], fg=C["text"],
            font=("Segoe UI", 10), relief="flat", bd=0,
            wrap="word", state="disabled"
        )
        self.ai_text.grid(row=4, column=0, sticky="nsew", padx=10, pady=(2, 10))

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=C["accent"], height=24)
        bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="Initialisiere …")
        tk.Label(bar, textvariable=self.status_var,
                 bg=C["accent"], fg=C["text"],
                 font=("Segoe UI", 9), anchor="w").pack(side="left", padx=8)
        tk.Label(bar, text="Ctrl+Shift+A = KI  |  Ctrl+Shift+C = Leeren",
                 bg=C["accent"], fg=C["dim"],
                 font=("Segoe UI", 9)).pack(side="right", padx=8)

    # ══════════════════════════════════════════════════════════════════════════
    #  PROFIL-LOGIK
    # ══════════════════════════════════════════════════════════════════════════

    def _on_profile_selected(self, event=None):
        name = self._profile_var.get()
        if name and name != "– kein Profil –":
            self._active_profile_name = name
            self._active_profile_lbl.config(text=self._fmt_active_profile())
            self._set_status(f"Profil gewechselt: {name}")

    def _open_profile_manager(self):
        ProfileManagerWindow(
            self.root,
            current_profile=self._active_profile_name or "",
            on_profiles_changed=self._on_profiles_changed
        )

    def _on_profiles_changed(self, saved_name):
        """Wird vom ProfileManagerWindow aufgerufen nach Speichern/Löschen."""
        profiles = _list_profiles()
        values   = profiles if profiles else ["– kein Profil –"]
        self._profile_dropdown["values"] = values

        # Aktives Profil aktualisieren
        if saved_name and saved_name in profiles:
            self._active_profile_name = saved_name
            self._profile_var.set(saved_name)
        elif profiles:
            self._active_profile_name = profiles[0]
            self._profile_var.set(profiles[0])
        else:
            self._active_profile_name = None
            self._profile_var.set("– kein Profil –")

        self._active_profile_lbl.config(text=self._fmt_active_profile())

    def _get_active_system_prompt(self) -> str:
        """Gibt den System-Prompt des aktiven Profils zurück, oder Fallback."""
        if self._active_profile_name:
            return _load_profile(self._active_profile_name)
        return SYSTEM_PROMPT_FALLBACK

    def _get_context_note(self) -> str:
        """
        Gibt den Inhalt des Kontext-Feldes zurück.
        Leer-String wenn nur der Placeholder drin steht.
        """
        val = self._context_var.get().strip()
        if val == self._context_placeholder:
            return ""
        return val

    def _open_context_editor(self, context_entry_widget):
        """
        Öffnet ein kleines Popup-Fenster mit einem mehrzeiligen Texteditor
        für das Kontext-Feld. Änderungen werden beim Schließen übernommen.
        """
        popup = tk.Toplevel(self.root)
        popup.title("Kontext bearbeiten")
        popup.configure(bg=C["bg"])
        popup.geometry("560x280")
        popup.resizable(True, True)
        popup.transient(self.root)
        popup.focus_force()

        tk.Label(
            popup,
            text="Kontext  –  Thema, Position, Hinweise für die KI",
            bg=C["bg"], fg=C["blue"],
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", padx=12, pady=(10, 4))

        tk.Label(
            popup,
            text='z.B.  "Thema: KI-Regulierung · Ich bin Pro · Konter den letzten Punkt"',
            bg=C["bg"], fg=C["dim"],
            font=("Segoe UI", 8)
        ).pack(anchor="w", padx=12, pady=(0, 6))

        editor = scrolledtext.ScrolledText(
            popup, bg=C["entry_bg"], fg=C["text"],
            font=("Segoe UI", 10), relief="flat", bd=4,
            wrap="word", insertbackground=C["text"],
            height=6
        )
        editor.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Aktuellen Wert laden (Placeholder ignorieren)
        current = self._get_context_note()
        if current:
            editor.insert("1.0", current)
        editor.focus_set()

        def _apply():
            val = editor.get("1.0", "end-1c").strip()
            # Einzeiler-Feld aktualisieren
            self._context_var.set(val if val else self._context_placeholder)
            context_entry_widget.config(fg=C["text"] if val else C["dim"])
            popup.destroy()

        btn_row = tk.Frame(popup, bg=C["bg"])
        btn_row.pack(fill="x", padx=12, pady=(0, 10))
        tk.Button(
            btn_row, text="✔ Übernehmen",
            bg=C["green"], fg="#000000",
            font=("Segoe UI", 9, "bold"),
            relief="flat", padx=12, pady=4, cursor="hand2",
            command=_apply
        ).pack(side="right", padx=(4, 0))
        tk.Button(
            btn_row, text="Abbrechen",
            bg=C["accent"], fg=C["text"],
            font=("Segoe UI", 9),
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=popup.destroy
        ).pack(side="right")
        # Enter im Popup schließt nicht aus Versehen
        popup.bind("<Escape>", lambda e: popup.destroy())

    # ══════════════════════════════════════════════════════════════════════════
    #  GERÄTE-VERWALTUNG
    # ══════════════════════════════════════════════════════════════════════════

    def _load_devices(self):
        self._device_status.config(text="⟳ Erkenne Geräte …")
        self.root.update_idletasks()
        try:
            mics, loopbacks = get_all_devices()
            self._mic_devices      = mics
            self._loopback_devices = loopbacks

            mic_names = [d.display_name for d in mics] or ["Kein Mikrofon gefunden"]
            self._mic_dropdown["values"] = mic_names

            default_mic = get_default_mic()
            if default_mic:
                self._active_mic = default_mic
                try:
                    self._mic_dropdown.current(
                        [d.index for d in mics].index(default_mic.index))
                except ValueError:
                    self._mic_dropdown.current(0)
            elif mics:
                self._active_mic = mics[0]
                self._mic_dropdown.current(0)

            lb_names = [d.display_name for d in loopbacks] or ["Kein Loopback gefunden"]
            self._lb_dropdown["values"] = lb_names

            default_lb = get_default_loopback()
            if default_lb:
                self._active_loopback = default_lb
                try:
                    self._lb_dropdown.current(
                        [d.index for d in loopbacks].index(default_lb.index))
                except ValueError:
                    self._lb_dropdown.current(0)
            elif loopbacks:
                self._active_loopback = loopbacks[0]
                self._lb_dropdown.current(0)

            self._device_status.config(
                text=f"✔ {len(mics)} Mic(s), {len(loopbacks)} Loopback(s)")
        except Exception as e:
            self._device_status.config(text=f"Fehler: {e}")

    def _on_mic_selected(self, event=None):
        idx = self._mic_dropdown.current()
        if 0 <= idx < len(self._mic_devices):
            self._active_mic = self._mic_devices[idx]
            if self._mic_enabled.get():
                self.mic_monitor.set_device(self._active_mic)
                self.transcriber.set_mic_device(self._active_mic)
                self._set_status(f"Mikrofon: {self._active_mic.name}")

    def _on_lb_selected(self, event=None):
        idx = self._lb_dropdown.current()
        if 0 <= idx < len(self._loopback_devices):
            self._active_loopback = self._loopback_devices[idx]
            if self._loopback_enabled.get():
                self.transcriber.set_loopback_device(self._active_loopback)
                self._set_status(f"Speaker: {self._active_loopback.name}")

    def _toggle_mic(self):
        enabled = not self._mic_enabled.get()
        self._mic_enabled.set(enabled)
        if enabled:
            self._mic_toggle_btn.config(text="🎙 MIC  ● ", fg=C["on"], bg=C["on_bg"])
            self._mic_dropdown.config(state="readonly")
            if self._active_mic:
                self.mic_monitor.set_device(self._active_mic)
                self.transcriber.set_mic_device(self._active_mic)
            self._set_status("Mikrofon aktiviert")
        else:
            self._mic_toggle_btn.config(text="🎙 MIC  ○", fg=C["off"], bg=C["off_bg"])
            self._mic_dropdown.config(state="disabled")
            self.mic_monitor.set_device(None)
            self.transcriber.set_mic_device(None)
            self._set_status("Mikrofon deaktiviert")

    def _toggle_loopback(self):
        enabled = not self._loopback_enabled.get()
        self._loopback_enabled.set(enabled)
        if enabled:
            self._lb_toggle_btn.config(text="🔊 SPEAKER  ● ", fg=C["on"], bg=C["on_bg"])
            self._lb_dropdown.config(state="readonly")
            if self._active_loopback:
                self.transcriber.set_loopback_device(self._active_loopback)
            self._set_status("Speaker-Transkription aktiviert")
        else:
            self._lb_toggle_btn.config(text="🔊 SPEAKER  ○", fg=C["off"], bg=C["off_bg"])
            self._lb_dropdown.config(state="disabled")
            self.transcriber.set_loopback_device(None)
            self.speaker_monitor.current_rms = 0.0
            self._set_status("Speaker-Transkription deaktiviert")

    # ══════════════════════════════════════════════════════════════════════════
    #  BACKEND
    # ══════════════════════════════════════════════════════════════════════════

    def _connect_backends(self):
        self.mic_monitor.register_callback(self._on_silence_change)
        self.transcriber.register_callback(self._on_transcript)
        self.ai_suggester.register_callback(self._on_ai_response)

    def _start_backends(self):
        mic_dev = self._active_mic if self._mic_enabled.get() else None
        self.mic_monitor.start(device=mic_dev)
        self._set_status("Lade faster-whisper …")
        threading.Thread(target=self._load_transcriber, daemon=True).start()

    def _load_transcriber(self):
        try:
            self.transcriber.start()
            if self._mic_enabled.get() and self._active_mic:
                self.transcriber.set_mic_device(self._active_mic)
            if self._loopback_enabled.get() and self._active_loopback:
                self.transcriber.set_loopback_device(self._active_loopback)
            self.root.after(0, lambda: self._set_status(
                "Bereit  ·  Mic + Speaker werden transkribiert"))
        except Exception as e:
            msg = str(e)
            self.root.after(0, lambda m=msg: self._set_status(f"Fehler: {m}"))

    # ══════════════════════════════════════════════════════════════════════════
    #  HOTKEYS
    # ══════════════════════════════════════════════════════════════════════════

    def _register_hotkeys(self):
        try:
            import keyboard
            keyboard.add_hotkey(HOTKEY_SEND_TO_AI,       self._send_to_ai)
            keyboard.add_hotkey(HOTKEY_CLEAR_TRANSCRIPT, self._clear_transcript)
            keyboard.add_hotkey(HOTKEY_AUTOSEND_TOGGLE,  self._toggle_autosend)
        except Exception as e:
            print(f"[Hotkeys] Fallback: {e}")
            self.root.bind("<Control-Shift-A>", lambda e: self._send_to_ai())
            self.root.bind("<Control-Shift-C>", lambda e: self._clear_transcript())
            self.root.bind("<Control-Shift-S>", lambda e: self._toggle_autosend())

    # ══════════════════════════════════════════════════════════════════════════
    #  CALLBACKS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_silence_change(self, level, silence_s):
        self.root.after(0, lambda: self._apply_silence_level(level))

    def _on_transcript(self, text, is_partial, source="mic"):
        self.root.after(0, lambda: self._append_transcript(text, source))

    def _on_ai_response(self, suggestions):
        self.root.after(0, lambda: self._show_ai_suggestions(suggestions))

    # ══════════════════════════════════════════════════════════════════════════
    #  UI UPDATES
    # ══════════════════════════════════════════════════════════════════════════

    def _apply_silence_level(self, level):
        for i, dot in enumerate(self.level_indicators):
            color = (C["green"] if (i == 0 and level == 0)
                     else LEVEL_COLORS[i] if level >= i
                     else C["accent"])
            dot.config(fg=color)

    def _update_loop(self):
        mic_rms = self.mic_monitor.current_rms
        self._update_vu(self._mic_bars, mic_rms / 3000.0, C["green"])
        self.mic_rms_label.config(text=f"🎙 {int(mic_rms)}")

        self.speaker_monitor.tick_decay()
        spk_rms = self.speaker_monitor.current_rms
        self._update_vu(self._spk_bars, spk_rms * 25.0, C["cyan"])
        self.spk_rms_label.config(text=f"🔊 {spk_rms:.4f}")

        sil = self.mic_monitor.seconds_since_last_speech()
        self.silence_label.config(
            text=f"Still seit: {int(sil)} s",
            fg=(C["red"]    if sil > SILENCE_LEVELS[2] else
                C["orange"] if sil > SILENCE_LEVELS[1] else
                C["yellow"] if sil > SILENCE_LEVELS[0] else
                C["green"])
        )

        self.rms_thresh_label.config(
            text=f"Schwelle: {self.threshold_var.get()}")

        n = self._ai_ctx_lines.get()
        self._ctx_lbl.config(text=f"→ {n} Zeilen")
        self._ctx_info_lbl.config(text=f"  ·  KI bekommt letzte {n} Zeilen")

        try:
            content = self.transcript_text.get("1.0", "end-1c")
            n_lines = len([l for l in content.splitlines() if l.strip()])
            self._line_count_lbl.config(text=f"{n_lines} Zeilen")
        except Exception:
            pass

        if self._autosend_enabled.get():
            interval  = self._autosend_interval.get()
            elapsed   = time.time() - self._autosend_last
            remaining = max(0, interval - elapsed)
            self._autosend_countdown.config(text=f"{int(remaining)}s")

            if elapsed >= interval:
                content   = self.transcript_text.get("1.0", "end-1c")
                cur_lines = len([l for l in content.splitlines() if l.strip()])
                new_lines = cur_lines - self._autosend_last_linecount
                if new_lines >= AUTOSEND_MIN_LINES:
                    self._send_to_ai()
                    self._autosend_last_linecount = cur_lines
                else:
                    self._set_status(
                        f"Auto-Send: zu wenig neue Zeilen ({new_lines}/{AUTOSEND_MIN_LINES}), warte...")
                self._autosend_last = time.time()

        self.root.after(60, self._update_loop)

    def _on_key_edit(self, event=None):
        if self._is_whisper_insert:
            return
        if event and event.keysym in (
            "Up", "Down", "Left", "Right",
            "Home", "End", "Prior", "Next",
            "Shift_L", "Shift_R", "Control_L", "Control_R",
            "Alt_L", "Alt_R", "Escape", "F1", "F2",
            "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10",
        ):
            return
        try:
            cursor    = self.transcript_text.index(tk.INSERT)
            line_num  = cursor.split(".")[0]
            line_start = f"{line_num}.0"
            line_end   = f"{line_num}.end"
            for tag in ("src_mic", "src_loopback", "src_mixed"):
                self.transcript_text.tag_remove(tag, line_start, line_end)
            self.transcript_text.tag_add("src_edit", line_start, line_end)
        except Exception:
            pass

    def _append_transcript(self, text, source="mic"):
        at_end = self.transcript_text.yview()[1] >= 0.95
        try:
            cursor_pos = self.transcript_text.index(tk.INSERT)
        except Exception:
            cursor_pos = None

        content = self.transcript_text.get("1.0", "end-1c")
        lines   = content.splitlines()
        if len(lines) >= MAX_LINES:
            overflow = len(lines) - MAX_LINES + 1
            self.transcript_text.delete("1.0", f"{overflow + 1}.0")

        src_tag    = f"src_{source}"
        src_prefix = {"mic": "🎙 ", "loopback": "🔊 ", "mixed": "🎙🔊 "}.get(source, "")
        display    = src_prefix + text

        ins_start = self.transcript_text.index("end-1c")
        self._is_whisper_insert = True
        self.transcript_text.insert("end", display + "\n", (src_tag, "new_chunk"))
        ins_end = self.transcript_text.index("end-1c")
        self._is_whisper_insert = False

        if cursor_pos:
            try:
                self.transcript_text.mark_set(tk.INSERT, cursor_pos)
            except Exception:
                pass

        if self._auto_scroll.get() and at_end:
            self.transcript_text.see("end")

        self.root.after(800, lambda: self._remove_tag("new_chunk", ins_start, ins_end))

    def _remove_tag(self, tag, start, end):
        try:
            self.transcript_text.tag_remove(tag, start, end)
        except Exception:
            pass

    def _show_ai_suggestions(self, suggestions):
        self.ai_text.config(state="normal")
        self.ai_text.delete("1.0", "end")
        self.ai_text.insert("1.0", suggestions)
        self.ai_text.config(state="disabled")
        self.ai_status.config(text="✔ Aktualisiert")

    def _send_to_ai(self):
        n       = self._ai_ctx_lines.get()
        content = self.transcript_text.get("1.0", "end-1c")
        lines   = [l for l in content.splitlines() if l.strip()]
        if not lines:
            self._set_status("Kein Transkript vorhanden.")
            return

        # ── Kontext-Header ──────────────────────────────────────────────────
        header_parts = []

        # Silence-Dauer
        sil = int(self.mic_monitor.seconds_since_last_speech())
        header_parts.append(f"Still seit: {sil}s")

        # Spontaner Kontext aus dem Eingabefeld (Thema / Position / etc.)
        ctx_note = self._get_context_note()
        if ctx_note:
            header_parts.append(f"Nutzer-Kontext: {ctx_note}")

        header  = "\n".join(header_parts) + "\n\n"
        context = header + "\n".join(lines[-n:])
        # ────────────────────────────────────────────────────────────────────

        self._highlight_context(lines, n)
        self.ai_status.config(text="⟳ Anfrage läuft …")
        self._set_status(f"KI-Anfrage: letzte {min(n, len(lines))} Zeilen …")

        # System-Prompt aus aktivem Profil an den Suggester übergeben
        system_prompt = self._get_active_system_prompt()
        self.ai_suggester.request_suggestions(context, system_prompt=system_prompt)

    def _highlight_context(self, all_lines, n):
        try:
            self.transcript_text.tag_remove("ai_context", "1.0", "end")
            start_i = max(0, len(all_lines) - n)
            self.transcript_text.tag_add("ai_context", f"{start_i + 1}.0", "end")
            self.root.after(2000, lambda: self.transcript_text.tag_remove(
                "ai_context", "1.0", "end"))
        except Exception:
            pass

    def _toggle_autosend(self):
        enabled = not self._autosend_enabled.get()
        self._autosend_enabled.set(enabled)
        if enabled:
            self._autosend_btn.config(
                text="⏱ AUTO  ● ", fg=C["green"], bg=C["on_bg"])
            self._autosend_last = time.time()
            content = self.transcript_text.get("1.0", "end-1c")
            self._autosend_last_linecount = len(
                [l for l in content.splitlines() if l.strip()])
            self._set_status(
                f"Auto-Send AN – alle {self._autosend_interval.get()}s  [Ctrl+Shift+S zum Stoppen]")
        else:
            self._autosend_btn.config(
                text="⏱ AUTO  ○", fg=C["off"], bg=C["off_bg"])
            self._autosend_countdown.config(text="")
            self._set_status("Auto-Send AUS")

    def _clear_transcript(self):
        self.transcript_text.delete("1.0", "end")
        self.transcriber.clear_buffer()
        self._set_status("Transkript geleert.")

    def _on_threshold_change(self, val):
        import config as cfg
        cfg.SPEAK_THRESHOLD_RMS = int(val)

    def _set_status(self, msg):
        self.status_var.set(msg)

    def on_close(self):
        self.mic_monitor.stop()
        self.transcriber.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    app  = ConversationAssistantApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
