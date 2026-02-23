# ─────────────────────────────────────────────
#  CONFIGURATION  –  Conversation Assistant PoC
# ─────────────────────────────────────────────
import os
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# ── Microphone Monitor ──
MIC_DEVICE_INDEX       = None       # None = system default
SILENCE_LEVELS         = [60, 90, 120]  # Sekunden → gelb, orange, rot
SPEAK_THRESHOLD_RMS    = 50        # RMS-Wert ab dem "Sprechen" erkannt wird
PING_FREQUENCY_HZ      = 880        # Ton-Pitch für Audio-Ping
PING_DURATION_MS       = 300        # Ton-Dauer in ms

# ── Transcriber ──
LOOPBACK_DEVICE_INDEX  = None       # None = auto; für manuell: python -c "import sounddevice as sd; print(sd.query_devices())"
SAMPLE_RATE            = 16000      # Whisper erwartet 16 kHz

# faster-whisper Modell: "tiny" (~1s Latenz), "base" (~2s), "small" (~4s)
# Empfehlung für Echtzeit: "tiny" oder "base"
#WHISPER_MODEL          = "base" #alt
WHISPER_MODEL   = "TheTobyB/whisper-large-v3-turbo-german-ct2" #NEUBETTERWHISPER
WHISPER_DEVICE     = "cuda"        # statt "cpu" NEUBETTERWHISPER
WHISPER_COMPUTE    = "float16"     # statt "int8" NEUBETTERWHISPER
# VAD-Filter (Voice Activity Detection): überspringt stille Chunks → schneller
WHISPER_VAD_FILTER     = False

CHUNK_SECONDS          = 1.0          # Aufnahme-Intervall in Sekunden (1.5s = sehr reaktiv)
MAX_TRANSCRIPT_LINES   = 200

# ── KI-Vorschläge: API-Auswahl ──────────────────────────────────────────────
#
#  OPTION A – OpenRouter  (empfohlen: du hast bereits einen Key)
#    Base URL : https://openrouter.ai/api/v1
#    Gute Modelle für diese Aufgabe (schnell + günstig):
#      - "google/gemini-2.5-flash-lite"      ← ultra-schnell, sehr günstig
#      - "google/gemini-3-flash-preview"     ← höhere Qualität
#      - "bytedance-seed/seed-1.6-flash"     ← sehr schnell, 75ct/1M out
#      - "qwen/qwen3-next-80b-a3b-instruct"  ← kostenlos (free tier)
#      - "nvidia/nemotron-3-nano-30b-a3b"    ← kostenlos (free tier)
#
#  OPTION B – Google Gemini direkt
#    Base URL : https://generativelanguage.googleapis.com/v1beta/openai
#    Modell   : "gemini-2.5-flash-lite"  oder  "gemini-3-flash-preview"
#
# ────────────────────────────────────────────────────────────────────────────

API_PROVIDER = "openrouter"   # "openrouter"  oder  "gemini"

# OpenRouter
OPENROUTER_API_KEY  = "sk-or-v1-123"           # ← deinen Key hier eintragen
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL    = "google/gemini-2.5-flash-lite"   # schnellste Option

# Google Gemini direkt
GEMINI_API_KEY      = "AIza..."             # ← deinen Key hier eintragen
GEMINI_BASE_URL     = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL        = "gemini-2.5-flash-lite"

# ── Aktive Werte (werden automatisch gesetzt) ──
if API_PROVIDER == "openrouter":
    ACTIVE_API_KEY  = OPENROUTER_API_KEY
    ACTIVE_BASE_URL = OPENROUTER_BASE_URL
    ACTIVE_MODEL    = OPENROUTER_MODEL
else:
    ACTIVE_API_KEY  = GEMINI_API_KEY
    ACTIVE_BASE_URL = GEMINI_BASE_URL
    ACTIVE_MODEL    = GEMINI_MODEL

# ── Profile ──────────────────────────────────────────────────────────────────
# Profile werden als .txt-Dateien im PROFILES_DIR gespeichert.
# Jede Datei = ein vollständiger System-Prompt.
# Im UI können Profile erstellt, bearbeitet und gelöscht werden.
# Der Dateiname (ohne .txt) ist der Anzeigename im Dropdown.
PROFILES_DIR = "profiles"

# Fallback-System-Prompt: wird verwendet wenn kein Profil existiert
# oder das gewählte Profil nicht geladen werden kann.
SYSTEM_PROMPT_FALLBACK = (
    "Du bist ein Gesprächs-Coach. Deine Aufgabe: dem Nutzer helfen, "
    "sich in einem laufenden Gespräch besser einzubringen – nicht nur Stille brechen, "
    "sondern wirklich etwas beitragen.\n\n"
    "Du bekommst ein Transkript eines laufenden Gesprächs. "
    "Es enthält die Stimmen mehrerer Personen gleichzeitig – das kann fragmentarisch oder widersprüchlich klingen. "
    "Zeilen mit 🎙 kommen vom Mikrofon, Zeilen mit 🔊 vom Lautsprecher (andere Teilnehmer). "
    "Sprache-zu-Text ist fehleranfällig: Ignoriere offensichtliche Transkriptionsfehler "
    "und erschließe den Sinn aus dem Kontext.\n\n"
    "DEINE AUFGABE:\n"
    "Gib genau 3 Sätze zurück, die der Nutzer als nächstes sagen kann. "
    "Jeder Satz soll direkt auf den aktuellen Stand eingehen, eine eigene Haltung mitbringen "
    "und einen Gedanken weiterführen – nicht nur nachfragen.\n\n"
    "FORMAT:\n"
    "Nur die 3 nummerierten Sätze. Kein Intro, kein Kommentar. Auf Deutsch. Nummerierung: 1. 2. 3."
)

# Rückwärtskompatibilität: SYSTEM_PROMPT zeigt auf Fallback
SYSTEM_PROMPT = SYSTEM_PROMPT_FALLBACK

# ── Auto-Send ──
AUTOSEND_ENABLED        = False   # beim Start deaktiviert
AUTOSEND_INTERVAL_SEC   = 30      # alle 30 Sekunden neuer Vorschlag
AUTOSEND_MIN_LINES      = 3       # mindestens N neue Zeilen seit letztem Send

# ── Hotkeys ──
HOTKEY_SEND_TO_AI       = "ctrl+shift+a"
HOTKEY_CLEAR_TRANSCRIPT = "ctrl+shift+c"
HOTKEY_AUTOSEND_TOGGLE  = "ctrl+shift+s"   # Auto-Send ein/aus
