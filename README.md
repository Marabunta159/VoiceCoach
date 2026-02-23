# 🎙 VoiceCoach – Free Real-Time Conversation Assistant

> **The free, open-source alternative to HuddleMate, Cluely & Co.**
> Listens to your conversations, tracks how long you've been quiet, and suggests
> exactly what to say next — powered by your own AI API key. Runs 100 % on your
> machine, nothing leaves your PC except the API call.
> For: Quiet people in friendship groups, nervous people when applying for jobs, etc.
> It does not save the transcript, but check if you are allowed legally to use it and send Information to AI. 
> Note: Not invisible in Screen Sharing

---

## ✨ What it does

- 🎙 **Listens** to your **microphone** and your **speaker** output **simultaneously**
- 📝 **Transcribes live** using [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — locally, no cloud.
  Default transcription model: [`TheTobyB/whisper-large-v3-turbo-german-ct2`](https://huggingface.co/TheTobyB/whisper-large-v3-turbo-german-ct2) (optimized for German), swappable in `config.py`
- ⏱ **Tracks your silence** — yellow → orange → red warning when you've been quiet for a long time
- 🤖 **Asks an AI** what you could say next, based on the last N lines of the conversation
  Default AI model: **google/gemini-2.5-flash-lite** fast and cheap
- 💡 **Shows 3 concrete suggestions** — not generic filler, real sentences you can actually say
- 🗂 **Profile system** — create different prompt styles for different groups or situations
- 📌 **Context field** — add a topic or position on the fly ("Topic: AI · I'm pro · counter the last argument")

**Works completely locally** — Whisper runs on your GPU or CPU, the only network call is to your AI API (OpenRouter or Gemini).

---

## 📸 Screenshot

<img width="1302" height="908" alt="grafik" src="https://github.com/user-attachments/assets/78cc41c4-8468-4699-8d9e-d733280c136e" />
<img width="818" height="630" alt="grafik" src="https://github.com/user-attachments/assets/7264ea77-485d-4ef8-85bd-267dd0599091" />

---

## 🚀 Quick Start (Windows)

### 1 · Prerequisites

| Requirement | Notes |
|---|---|
| **Windows 10 / 11** | WASAPI loopback for speaker capture |
| **Python 3.10 or newer** | [python.org/downloads](https://www.python.org/downloads/) — ✅ check *"Add to PATH"* during install |
| **FFmpeg** | [ffmpeg.org](https://ffmpeg.org/download.html) — extract and add the `bin/` folder to your PATH |
| **NVIDIA GPU (optional)** | Recommended for fast Whisper transcription. Works without GPU too, just slower. |

<details>
<summary>How to add FFmpeg to PATH (click to expand)</summary>

1. Download the FFmpeg ZIP from [ffmpeg.org](https://ffmpeg.org/download.html) (Windows build)
2. Extract it somewhere, e.g. `C:\ffmpeg`
3. Open **Start → Edit the system environment variables → Environment Variables**
4. Under *System variables* find `Path`, click **Edit → New**
5. Add `C:\ffmpeg\bin`
6. Click OK everywhere and reopen any terminals

Verify with: `ffmpeg -version`

</details>

---

### 2 · Install

```bash
git clone https://github.com/YOUR_USERNAME/voicecoach.git
cd voicecoach
```

Then simply run:
```
setup.bat
```

This will create an isolated Python `venv`, install all dependencies, check for FFmpeg, and tell you what to do next. The Whisper model (~1.6 GB) downloads automatically on first launch.

> **No GPU?** Open `config.py` and change:
> ```python
> WHISPER_DEVICE  = "cpu"
> WHISPER_COMPUTE = "int8"
> ```

#### GPU (CUDA) setup — optional but recommended

If you have an NVIDIA GPU, install the CUDA-enabled version of PyTorch first:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

Then in `config.py` (already set by default):
```python
WHISPER_DEVICE  = "cuda"
WHISPER_COMPUTE = "float16"
```

Without a GPU, change these to:
```python
WHISPER_DEVICE  = "cpu"
WHISPER_COMPUTE = "int8"
```

---

### 3 · Get an API key

VoiceCoach needs an AI API to generate suggestions. You have two options prepared:

**Option A — OpenRouter** *(recommended, works with many free models)*
1. Create a free account at [openrouter.ai](https://openrouter.ai)
2. Go to *Keys* and create a new key
3. Paste it into `config.py`:
```python
OPENROUTER_API_KEY  = "sk-or-v1-123"
API_PROVIDER       = "openrouter"
```

**Option B — Google Gemini**
1. Get a key at [aistudio.google.com](https://aistudio.google.com/app/apikey)
2. Paste it into `config.py`:
```python
GEMINI_API_KEY      = "AIza..."
API_PROVIDER   = "gemini"
```

---

### 4 · Run

```
start.bat
```

---

## ⚙️ Configuration

All settings live in `config.py`. The most important ones:

| Setting | Default | What it does |
|---|---|---|
| `WHISPER_MODEL` | `whisper-large-v3-turbo-german-ct2` | Whisper model — swap for `base` if you want faster/lighter |
| `WHISPER_DEVICE` | `cuda` | `cuda` for GPU, `cpu` for CPU-only |
| `SILENCE_LEVELS` | `[60, 90, 120]` | Seconds until yellow / orange / red warning |
| `SPEAK_THRESHOLD_RMS` | `50` | How loud you need to be to count as "speaking" — adjustable via slider in the UI |
| `AUTOSEND_INTERVAL_SEC` | `30` | How often Auto-Send fires (seconds) |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash-lite` | AI model for suggestions — see [openrouter.ai/models](https://openrouter.ai/models) for options |

---

## 🗂 Profiles

Profiles are plain `.txt` files in the `profiles/` folder.
Each file contains a complete system prompt — what you write there is exactly what the AI receives.

**Managing profiles in the UI:**
1. Click **⚙ Profile verwalten** in the top bar
2. Select a profile from the list to edit it
3. Change the name and/or the prompt text
4. Click **💾 Speichern**

**Creating a new profile:**
1. Click **+ Neu**
2. Give it a name (e.g. `Work Meeting`, `Debate Club`, `Fortnite Squad`)
3. Write or paste your system prompt
4. Save

Starter profile included:
- `Standard` — neutral, adapts tone to the conversation

---

## 🎮 Hotkeys

| Hotkey | Action |
|---|---|
| `Ctrl + Shift + A` | Send transcript to AI → get suggestions |
| `Ctrl + Shift + C` | Clear the transcript |
| `Ctrl + Shift + S` | Toggle Auto-Send on/off |

> The `keyboard` package may require **administrator rights** on Windows for global hotkeys to work.
> If they don't respond, try running `python app.py` as Administrator.

---

## 🔊 Speaker capture not working?

The speaker capture uses **WASAPI Loopback** (Windows-only).

1. Open **Windows Sound Settings → Recording** — you should see a *"Stereo Mix"* or similar loopback device. Enable it if it's disabled.
2. In the app, click the **↻ refresh** button next to the Speaker dropdown.
3. If it's still missing, find your device index manually:
   ```python
   import sounddevice as sd
   print(sd.query_devices())
   ```
   Then set `LOOPBACK_DEVICE_INDEX` in `config.py` to the correct index.

---

## 📦 Dependencies

| Package | Why |
|---|---|
| `faster-whisper` | Local speech-to-text |
| `pyaudiowpatch` | Audio capture incl. WASAPI Loopback |
| `numpy` | Audio buffer processing |
| `requests` | API calls to OpenRouter / Gemini |
| `keyboard` | Global hotkeys |
| `tkinter` | UI (included with Python) |

Full list: [`requirements.txt`](requirements.txt)

---

## 📁 Project Structure

```
voicecoach/
├── app.py              # UI + main application
├── config.py           # All settings — edit this first
├── transcriber.py      # Whisper + VAD audio pipeline
├── mic_monitor.py      # Microphone level + silence timer
├── audio_devices.py    # Device detection (WASAPI)
├── ai_suggestions.py   # API calls for AI suggestions
├── requirements.txt
├── profiles/           # Your system prompt profiles (.txt)
│   └── Standard.txt
└── README.md
```

---

## 📜 License

**CC BY-NC 4.0 — Creative Commons Attribution-NonCommercial 4.0**

- ✅ Free to use personally
- ✅ Free to modify and share
- ❌ Not for commercial use
- 📌 If you modify and share it, you must credit the original author

Full license: [creativecommons.org/licenses/by-nc/4.0](https://creativecommons.org/licenses/by-nc/4.0/)

---

## 🙏 Credits

Built by **Marabunta159**.
If you fork or modify this project, please keep a mention of the original — that's all that's asked.

---

## 💬 Contributing / Issues

Found a bug? Have a suggestion? Open an [Issue](../../issues) or a Pull Request.
Built with help of AI.
This is a PoC — rough edges exist. Contributions welcome.
