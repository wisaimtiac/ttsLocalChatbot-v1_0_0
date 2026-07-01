## Local TTS Roleplay Chatbot

Conversational agent for tabletop game masters.
It pairs a locally hosted LLM with a high-quality neural voice so you can inspire or plan your characters and interactions 
with predefined NPCs, then review every exchange later as **text and/or audio**.

Built as a Dungeon Master's idea engine: chat with a character, let the conversation surface unexpected story threads, 
and harvest the logged text/MP3 afterwards for world-building.
---

## Features

- **Fully offline:** Talks only to a local LLM endpoint.
- **Character personas.** NPCs are defined as granular, rule-based system prompts in an editable `npc_profiles.json`.
- **Natural sounding voice (Kokoro).** Each reply is synthesized to a lifelike voice and saved as an MP3.
- **No VRAM contention.** The TTS engine is pinned to the **CPU**, leaving your GPU free for the LLM.
- **Persistent logs.** Every turn is appended to a timestamped transcript `.txt`; every reply is voiced and saved as an MP3 in `audio/`.
- **Graceful degradation.** If TTS libraries are missing, chatting still works — it just skips audio and tells you why.
- **Reasoning-model friendly.** Empty `content` falls back to `reasoning_content`, and `<think>…</think>` blocks are stripped.
---

## Requirements

- **Python 3.11** (3.10–3.12 supported)
- A running local LLM with an OpenAI-compatible API — e.g. **[LM Studio](https://lmstudio.ai)** with its local server enabled on port `1234`
- For text-to-speech:
  - `kokoro`, `numpy`, `lameenc` (Python packages)
  - **espeak-ng** (system dependency, for pronunciation)

`tkinter` ships with the standard Python installer on Windows and macOS. 
On Debian/Ubuntu: `sudo apt install python3-tk`.
---

## Installation

```bash

# (Recommended) virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Python dependencies
pip install kokoro numpy lameenc

# System dependency: espeak-ng
#   Windows: download and run the espeak-ng-*.msi from
#            https://github.com/espeak-ng/espeak-ng/releases
#   macOS:   brew install espeak-ng
#   Linux:   sudo apt install espeak-ng
```

On first run, Kokoro downloads its ~327 MB voice model and caches it; afterwards it runs fully offline.
---

## Usage

1. Start your local LLM server.
2. Run the script.
3. Pick a character from the dropdown, type in the box, and press **Enter** to send (**Shift+Enter** for a newline).
4. Replies appear in the window and are saved to MP3 in the background.
---

## Configuration

All settings live at the top of `tts_chatbot.py`:

| Constant | Default | Purpose |
|---|---|---|
| `API_URL` | `http://localhost:1234/v1/chat/completions` | Local LLM endpoint |
| `MODEL_NAME` | `local-model` | Model id sent to the API |
| `HISTORY_LIMIT` | `5` | Recent messages kept as context |
| `API_TIMEOUT` | `300` | Seconds before a request gives up |
| `TTS_ENABLED` | `True` | Master switch for audio |
| `TTS_VOICE` | `af_sarah` | Kokoro voice id (other options listed in script)|
| `TTS_LANG` | `a` | `a` = US English, `b` = UK English |
| `TTS_SPEED` | `1.5` | Speech rate (0.5–2.0) |
| `TTS_BITRATE` | `256` | MP3 bitrate (kbps) |

**Voices:** other natural female options include `af_bella`, `af_nicole` (US) and `bf_emma` (UK; set `TTS_LANG = "b"`).

**Adding an NPC:** edit `npc_profiles.json` — the key is the display name; the value is the system prompt. The app falls back to a built-in default profile if the file is missing or invalid.
---

## How it works

```
You type ─► Tk main thread ─► request worker ──HTTP──► local LLM
                                   │
                  reply ◄──────────┘
                    │
        ┌───────────┼───────────────┐
        ▼           ▼               ▼
   chat window   transcript.txt   TTS queue ─► TTS worker ─► .mp3
```
---

## Project structure

```
.
├── ttsLocalChatbot-v1_0_0.py       # the application
├── npc_profiles-ttsCB.json         # editable NPC personas
├── npc_chat_*.txt                  # transcripts (created at runtime)
├── audio/                          # generated MP3s
└────── reply_CHARACTER_*.mp3       # audios (created at runtime)

```
---

## Troubleshooting

- **"TTS off: pip install kokoro lameenc numpy"** — a TTS dependency is missing; install it (and espeak-ng).
- **"Network error on http://localhost:1234..."** — the LLM server isn't running or is on a different port; check LM Studio and `API_URL`.
- **Replies say "(The character stays silent.)"** — sometimes reasoning models spend their whole budget on thinking; disable it or raise context length in LM Studio.
- **Symlink / unauthenticated HF warnings** — harmless; already silenced via environment variables.
---

## Planned Updates/Developments:

- **User Interface** — Direct selection options for TTS on/off (switch).
- **Different Voices** — A (preset) way of matching Voice ID to characters, but keeping it modular, so all kinds of combinations are possible.
- **Character Depth** — An easily accessible and editable format for adding/editing further background information like personal history, personality, beliefs or quirks.
---

## License

MIT — see `LICENSE`.

## Acknowledgements

- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) by hexgrad (Apache-2.0)
- [LM Studio](https://lmstudio.ai) for the local LLM runtime
