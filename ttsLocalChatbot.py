"""
ttsLocalChatbot-v1_0_0 by wisaimtiac

Local, offline TTS roleplay chatbot for tabletop DMs.

Desktop app that talks to a locally hosted LLM (e.g. LM Studio),
voices each reply with the Kokoro TTS engine on the CPU, and logs
every turn to text and mp3 for later review.
"""
import os
import re
import json
import queue
import random
import datetime
import threading
import urllib.request
import tkinter as tk
from tkinter import ttk, font

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
 
# --- Configuration ----------------------------------------------------
API_URL = "http://localhost:1234/v1/chat/completions"
MODEL_NAME = "local-model"
HISTORY_LIMIT = 5           # recent messages kept as context
API_TIMEOUT = 300
KNOWLEDGE_LIMIT = 4         # max knowledge entries injected per reply
 
INTRO_CPS = 275             # intro typing speed in characters per second
INTRO_TYPO_CHANCE = 0.0012  # per-character chance of a typed-then-fixed slip
 
TTS_ENABLED = False
TTS_VOICE = "af_sarah" # Voice ID
                       #  -> af = USA-female:
                       #            af_bella, af_nicole, af_sarah
                       #  -> am = USA-male:
                       #            am_adam, am_eric, am_michael
                       #  -> bf = UK-female:
                       #            bf_emma, bf_isabella, bf_lily
                       #  -> bm = UK-male: 
                       #            bm_daniel, bm_george, bm_lewis.
TTS_LANG = "a"         # 'a'= US, 'b'= UK English
TTS_SPEED = 2          # 0.5 - 2.0
TTS_RATE = 24000       # output rate in Hz
TTS_BITRATE = 128
 
PROFILES_FILE = "npc_profiles-ttsCB.json"
ANTI_LOOP = (
    "\nCRITICAL RULE: Your responses should match what the user "
    "requires from you: short, average, long length. Do not repeat "
    "previous phrasing or sentence structures unless asked to. "
    "Always advance the conversation."
)
 
# Theme colors.
BG, PANEL, TEXT = "#121212", "#1E1E1E", "#E0E0E0"
USER, NPC, SYS = "#4CAF50", "#007ACC", "#888888"
INPUT_BG, BTN = "#333333", "#2D2D2D"
 
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
 
DEFAULT_PROFILES = {
    "Narrator: Neutral guide.":
        "A calm, neutral narrator who sets scenes and "
        "answers in a measured, descriptive voice.",
}
 
# Welcome text that types itself out at startup (screen only, not
# logged). Covers the cast and three prompting tips while the heavy
# TTS libraries finish loading in the background.
INTRO_TEXT = (
    "Welcome! Choose 1 of 13 wandering souls (warriors, wizards, rogues, hermits, mighty, forgotten) holding grudges, dreams, and secrets for text/audio chat:\n\n"
    "Kargen (Thane): War-weary dwarf holding his martyred brother's axe. Trusts stone/steel; distrusts magic/strangers.\n"
    "Vespera (Archmage): Outlived 3 kings and all apprentices. Dismisses mundane wars for arcane truth.\n"
    "Gideon (Paladin): Death-sworn oathkeeper who failed to save a village from a demon. Sees absolute light/dark only.\n"
    "Silas (Rogue): Orphan raised by thieves. Distrusts nobles/promises; reluctantly shields the helpless.\n"
    "Elara (Druid): Let the forest avenge her burned grove. Answers to soil/seasons; hates city noise.\n"
    "Julian (Bard): Fears being forgotten. Seeking a masterpiece to replace his finest ballad stolen by a lover.\n"
    "Morrigan (Warlock): Traded her name and sanity to the Whispering Eye for knowledge. Believes power is the only cosmic truth.\n"
    "Bram (Tavern Keep): Ex-mercenary hiding scars and intellect. Sells town secrets for the right coin.\n"
    "Tarn (City Guard): Underpaid, passed-over cynic. Follows rules to avoid paperwork; accepts bribes.\n"
    "Lyra (Shop Clerk): Treats dangerous artifacts like beloved pets. Fondly recalls one leveling half her shop.\n"
    "Cassian (Beggar): Disgraced ex-spymaster disguised in rags. Uses street kids as spies; values secrets over gold.\n"
    "Aldous (Court Wizard): Terrified of losing royal favor. Hides past humiliation by over-regulating unlicensed magic.\n"
    "Finn (Squire): Dreamer in borrowed armor whose idol died in battle. Believes any errand is a legend.\n\n"
    "3 Tips:\n"
    "1. Set context (who/where you are).\n"
    "2. Ask for specifics (opinion, memory, decision).\n"
    "3. Specify response length (curt line or long tale).\n\n"
    "Save these instructions! Choose your character to begin."
)
 
# Rough QWERTY neighbors, used to fake believable typing slips.
_NEIGHBORS = {
    "a": "sq", "s": "ad", "d": "sf", "f": "dg", "g": "fh",
    "h": "gj", "j": "hk", "k": "jl", "l": "k", "q": "wa",
    "w": "qe", "e": "wr", "r": "et", "t": "ry", "y": "tu",
    "u": "yi", "i": "uo", "o": "ip", "p": "o", "z": "x",
    "x": "zc", "c": "xv", "v": "cb", "b": "vn", "n": "bm",
    "m": "n",
}
 
 
def typo_for(ch):
    """Return a plausible wrong key for CH, preserving its case."""
    near = _NEIGHBORS.get(ch.lower())
    wrong = random.choice(near) if near else random.choice(
        "abcdefghijklmnopqrstuvwxyz")
    return wrong.upper() if ch.isupper() else wrong
 
# Heavy TTS dependencies (numpy, lameenc, kokoro, torch) are imported
# lazily inside the TTS worker thread, so the window appears instantly
# instead of waiting on torch's slow import. Placeholders until loaded.
np = lameenc = KPipeline = torch = None
 
 
# --- Helper functions -------------------------------------------------
def in_dir(name):
    """Return the path to NAME next to this script."""
    return os.path.join(SCRIPT_DIR, name)
 
 
def load_profiles(path):
    """Load personas from JSON, else fall back to the default."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return data
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError) as e:
        print(f">>> profile load error: {e} <<<")
    return DEFAULT_PROFILES
 
 
def strip_think(text):
    """Remove <think>...</think> reasoning blocks."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
 
 
def profile_core(profile):
    """Always-on system text for a profile (new dict or old string)."""
    if isinstance(profile, dict):
        return profile.get("core", "")
    return profile
 
 
def retrieve_knowledge(profile, user_text, limit=KNOWLEDGE_LIMIT):
    """Return knowledge entries whose tags match the user's message.
 
    New-format profiles are dicts with a "knowledge" list of
    {"tags": [...], "text": "..."} items. A multi-word tag matches as
    a substring; a single word must match a whole word in the message.
    Old string profiles have no knowledge and yield nothing.
    """
    items = profile.get("knowledge") if isinstance(profile, dict) else None
    if not items:
        return []
    low = user_text.lower()
    words = set(re.findall(r"\w+", low))
    hits = []
    for item in items:
        text = item.get("text", "").strip()
        if not text:
            continue
        tags = [t.lower() for t in item.get("tags", [])]
        if any((t in low) if " " in t else (t in words) for t in tags):
            hits.append(text)
            if len(hits) >= limit:
                break
    return hits
 
 
def to_numpy(result):
    """One Kokoro result item -> flat float32 ndarray."""
    wav = getattr(result, "audio", None)
    if wav is None:
        wav = result[-1]
    if torch is not None and isinstance(wav, torch.Tensor):
        wav = wav.detach().cpu().numpy()
    return np.asarray(wav, dtype=np.float32).flatten()
 
 
def write_mp3(samples, path):
    """Encode float32 samples to a mono mp3 file."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
    enc = lameenc.Encoder()
    enc.set_bit_rate(TTS_BITRATE)
    enc.set_in_sample_rate(TTS_RATE)
    enc.set_channels(1)
    enc.set_quality(2)
    blob = enc.encode(pcm.tobytes()) + enc.flush()
    with open(path, "wb") as f:
        f.write(blob)
 
 
# --- Application ------------------------------------------------------
class ChatApp:
    """Tkinter chat UI with background TTS and logging."""
 
    def __init__(self, root):
        self.root = root
        self.history = []
        self.tts_q = queue.Queue()
        self.profiles = load_profiles(in_dir(PROFILES_FILE))
        self.stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.audio_dir = in_dir("audio")
        os.makedirs(self.audio_dir, exist_ok=True)
        self.log_path = in_dir(f"npc_chat_{self.stamp}.txt")
        self._intro_active = True   # buffer System msgs during intro
        self._pending = []
        self._build_ui()
        if TTS_ENABLED:
            threading.Thread(target=self._tts_worker,
                             daemon=True).start()
        self._start_intro()
 
    # ---- UI construction ----
    def _build_ui(self):
        r = self.root
        r.title("Local TTS Roleplay Chatbot")
        w, h = 1280, 720
        x = (r.winfo_screenwidth() - w) // 2
        y = (r.winfo_screenheight() - h) // 2
        r.geometry(f"{w}x{h}+{x}+{y}")
        r.configure(bg=BG)
        style = ttk.Style(r)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Load.Horizontal.TProgressbar",
                        troughcolor=PANEL, bordercolor=PANEL,
                        background=USER)
        self.f_ui = font.Font(family="Helvetica", size=11,
                              weight="bold")
        self.f_chat = font.Font(family="Consolas", size=14)
        f_bold = font.Font(family="Consolas", size=13, weight="bold")
        f_ital = font.Font(family="Consolas", size=11, slant="italic")
 
        # Top bar: character selector.
        top = tk.Frame(r, bg=PANEL, height=60)
        top.pack(fill=tk.X, side=tk.TOP)
        top.pack_propagate(False)
        tk.Label(top, text="Chatting with:", bg=PANEL, fg=TEXT,
                 font=self.f_ui).pack(side=tk.LEFT, padx=(20, 10),
                                      pady=15)
        names = list(self.profiles.keys())
        self.npc = tk.StringVar(value=names[0])
        ttk.Combobox(top, textvariable=self.npc, values=names,
                     state="readonly", font=self.f_ui,
                     width=90).pack(side=tk.LEFT, pady=15)
        self.npc.trace_add("write", self._on_npc_change)
 
        # Loading bar: fills as the intro types; full == ready to type.
        self.bar_load = ttk.Progressbar(
            r, style="Load.Horizontal.TProgressbar",
            mode="determinate", maximum=100)
        self.bar_load.pack(fill=tk.X, side=tk.TOP)
 
        # Chat transcript.
        frame = tk.Frame(r, bg=BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(20, 10))
        bar = tk.Scrollbar(frame)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat = tk.Text(frame, bg=BG, fg=TEXT, font=self.f_chat,
                            yscrollcommand=bar.set, wrap=tk.WORD,
                            state=tk.DISABLED, relief="flat",
                            highlightthickness=0)
        self.chat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bar.config(command=self.chat.yview)
        self.chat.tag_config("User", foreground=USER, font=f_bold)
        self.chat.tag_config("NPC", foreground=NPC, font=f_bold)
        self.chat.tag_config("System", foreground=SYS, font=f_ital)
        self.chat.tag_config("Normal", foreground=TEXT)
        self.chat.tag_config("Intro", foreground=TEXT, font=self.f_chat)
 
        # Input box + send button.
        bottom = tk.Frame(r, bg=PANEL, height=90)
        bottom.pack(fill=tk.X, side=tk.BOTTOM)
        bottom.pack_propagate(False)
        self.entry = tk.Text(bottom, bg=INPUT_BG, fg=TEXT,
                             font=self.f_chat, relief="flat",
                             insertbackground=TEXT, height=2,
                             wrap=tk.WORD)
        self.entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                        padx=(20, 10), pady=20)
        self.send = tk.Button(bottom, text="Send", bg=BTN, fg=TEXT,
                              font=self.f_ui, relief="flat",
                              cursor="hand2", width=8,
                              command=self._on_send)
        self.send.pack(side=tk.RIGHT, padx=(0, 20), pady=20)
        self.entry.bind("<Return>", self._on_send)
        self.entry.bind("<Shift-Return>", lambda e: None)
        self.entry.focus_set()
 
    # ---- Chat output ----
    def _log(self, sender, message):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{sender}: {message}\n\n")
        except OSError as e:
            print(f">>> log write error: {e} <<<")
 
    def _append(self, sender, msg, tag, log=True):
        if self._intro_active:          # hold System msgs until intro ends
            self._pending.append((sender, msg, tag, log))
            return
        self.chat.config(state=tk.NORMAL)
        self.chat.insert(tk.END, f"{sender}: ", tag)
        self.chat.insert(tk.END, f"{msg}\n\n", "Normal")
        self.chat.see(tk.END)
        self.chat.config(state=tk.DISABLED)
        if log:
            self._log(sender, msg)
 
    def _ui(self, *args):
        """Append from a worker thread via the Tk main thread."""
        self.root.after(0, self._append, *args)
 
    # ---- Intro typewriter (screen only, not logged) ----
    def _start_intro(self):
        """Disable input and begin typing the welcome text."""
        self._intro_i = 0
        self._just_fixed = False
        self.entry.config(state=tk.DISABLED)
        self.send.config(state=tk.DISABLED)
        self.bar_load.config(value=0)
        self.root.after(400, self._intro_step)
 
    def _ins(self, s):
        self.chat.config(state=tk.NORMAL)
        self.chat.insert(tk.END, s, "Intro")
        self.chat.see(tk.END)
        self.chat.config(state=tk.DISABLED)
 
    def _ins_typo(self, s):
        self.chat.config(state=tk.NORMAL)
        self._typo_at = self.chat.index("end-1c")
        self.chat.insert(tk.END, s, "Intro")
        self.chat.see(tk.END)
        self.chat.config(state=tk.DISABLED)
 
    def _undo_typo(self):
        self.chat.config(state=tk.NORMAL)
        self.chat.delete(self._typo_at, "end-1c")
        self.chat.see(tk.END)
        self.chat.config(state=tk.DISABLED)
 
    def _char_delay(self, ch):
        base = 1000.0 / INTRO_CPS
        d = base * random.uniform(0.6, 1.5)
        if ch in ".!?":
            d += random.uniform(350, 550)
        elif ch in ",;:":
            d += random.uniform(120, 220)
        elif ch == "\n":
            d += random.uniform(150, 300)
        return int(d)
 
    def _intro_step(self):
        if self._intro_i >= len(INTRO_TEXT):
            self._finish_intro()
            return
        self.bar_load.config(value=100 * self._intro_i / len(INTRO_TEXT))
        ch = INTRO_TEXT[self._intro_i]
        if (not self._just_fixed and ch.isalpha()
                and random.random() < INTRO_TYPO_CHANCE):
            self._ins_typo(typo_for(ch))
            self.root.after(int(random.uniform(220, 360)),
                            self._intro_fix)
            return
        self._just_fixed = False
        self._ins(ch)
        self._intro_i += 1
        self.root.after(self._char_delay(ch), self._intro_step)
 
    def _intro_fix(self):
        self._undo_typo()
        self._just_fixed = True       # type the real char next, no re-slip
        self.root.after(int(random.uniform(90, 160)), self._intro_step)
 
    def _finish_intro(self):
        self.bar_load.config(value=100)
        self._intro_active = False
        self.entry.config(state=tk.NORMAL)
        self.send.config(state=tk.NORMAL, text="Send")
        self.entry.focus_set()
        self.root.after(600, self.bar_load.pack_forget)
        for args in self._pending:    # flush any buffered System msgs
            self._append(*args)
        self._pending = []
 
    # ---- Events ----
    def _set_busy(self, busy):
        self.send.config(state=tk.DISABLED if busy else tk.NORMAL,
                         text="..." if busy else "Send")
        self.entry.config(state=tk.DISABLED if busy else tk.NORMAL)
        if not busy:
            self.entry.focus_set()
 
    def _on_npc_change(self, *args):
        self.history.clear()
        self.chat.config(state=tk.NORMAL)
        self.chat.delete("1.0", tk.END)
        self.chat.config(state=tk.DISABLED)
        self._append("System",
                     f"--- Switched to {self.npc.get()} ---", "System")
 
    def _on_send(self, event=None):
        if str(self.send["state"]) == tk.DISABLED:
            return "break"
        text = self.entry.get("1.0", tk.END).strip()
        if not text:
            return "break"
        self._append("You", text, "User")
        self.history.append({"role": "user", "content": text})
        self.entry.delete("1.0", tk.END)
        self._set_busy(True)
        threading.Thread(target=self._request, daemon=True).start()
        return "break"
 
    # ---- LLM request (worker thread) ----
    def _messages(self):
        profile = self.profiles[self.npc.get()]
        content = profile_core(profile) + ANTI_LOOP
        last_user = next((m["content"] for m in reversed(self.history)
                          if m["role"] == "user"), "")
        facts = retrieve_knowledge(profile, last_user)
        if facts:
            content += ("\n\nRelevant background for this reply (weave "
                        "in only what fits naturally; do not list it):\n- "
                        + "\n- ".join(facts))
        return [{"role": "system", "content": content}] \
            + self.history[-HISTORY_LIMIT:]
 
    def _request(self):
        """Worker: call the LLM and show the reply."""
        name = self.npc.get()
        speaker = name.split(":")[0].strip() or name
        try:
            reply = self._call_api({"model": MODEL_NAME,
                                    "messages": self._messages()})
            self.history.append({"role": "assistant",
                                 "content": reply})
            self._ui(speaker, reply, "NPC")
            if TTS_ENABLED:
                self._queue_tts(speaker, reply)
        except Exception as e:           # noqa: BLE001
            self._ui("System", f"Network error on {API_URL}: {e}",
                     "System")
        finally:
            self.root.after(0, self._set_busy, False)
 
    def _call_api(self, body):
        """POST to the LLM and return the reply text."""
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            API_URL, data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        msg = payload["choices"][0].get("message", {})
        text = (msg.get("content") or "").strip()
        if not text:
            text = (msg.get("reasoning_content") or "").strip()
        return strip_think(text) or "(The character stays silent.)"
 
    # ---- TTS (worker thread) ----
    def _queue_tts(self, speaker, text):
        ts = datetime.datetime.now().strftime("%H%M%S")
        tag = "".join(c for c in speaker if c.isalnum()) or "npc"
        fname = f"reply_{tag}_{self.stamp}_{ts}.mp3"
        self.tts_q.put((text, os.path.join(self.audio_dir, fname)))
 
    def _tts_worker(self):
        """Load TTS libs (slow), then synthesize queued replies.
 
        The numpy/lameenc/kokoro/torch imports happen here, off the UI
        thread, so the window is never blocked by torch's multi-second
        import at startup. If anything is missing, TTS stays off and
        the queue is drained so senders never block.
        """
        global np, lameenc, KPipeline, torch
        pipe = None
        try:
            import numpy as np
            import lameenc
            from kokoro import KPipeline
            try:
                import torch
            except Exception:            # noqa: BLE001
                torch = None
            pipe = self._make_pipeline()
        except Exception as e:           # noqa: BLE001
            self._ui("System", "TTS off (need: pip install kokoro "
                     f"lameenc numpy + espeak-ng): {e}", "System", False)
        while True:
            item = self.tts_q.get()
            try:
                if item is not None and pipe is not None:
                    self._synthesize(pipe, *item)
            finally:
                self.tts_q.task_done()
 
    @staticmethod
    def _make_pipeline():
        """Build a CPU-bound Kokoro pipeline."""
        try:
            return KPipeline(lang_code=TTS_LANG, device="cpu")
        except TypeError:
            return KPipeline(lang_code=TTS_LANG)
 
    def _synthesize(self, pipe, text, path):
        try:
            chunks = [to_numpy(res) for res in
                      pipe(text, voice=TTS_VOICE, speed=TTS_SPEED)]
            if chunks:
                write_mp3(np.concatenate(chunks), path)
                self._ui("System", f"Saved {os.path.basename(path)}",
                         "System", False)
        except Exception as e:           # noqa: BLE001
            self._ui("System", f"TTS error: {e}", "System", False)
 
 
def main():
    root = tk.Tk()
    ChatApp(root)
    root.mainloop()
 
 
if __name__ == "__main__":
    main()
