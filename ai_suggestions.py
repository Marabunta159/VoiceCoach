"""
ai_suggestions.py
─────────────────
Verwendet requests direkt (nicht das OpenAI SDK),
genau wie die offizielle OpenRouter-Doku zeigt.
Das OpenAI SDK hat in manchen Versionen Probleme
mit custom default_headers → daher dieser Weg.
"""

import threading
import requests
import json
from config import ACTIVE_API_KEY, ACTIVE_BASE_URL, ACTIVE_MODEL, SYSTEM_PROMPT_FALLBACK


class AISuggester:

    def __init__(self):
        self._callbacks = []

    def register_callback(self, fn):
        self._callbacks.append(fn)

    def request_suggestions(self, transcript_text: str, system_prompt: str = None):
        if not transcript_text.strip():
            return
        threading.Thread(
            target=self._call_api,
            args=(transcript_text, system_prompt),
            daemon=True
        ).start()

    def _call_api(self, transcript_text: str, system_prompt: str = None):
        prompt = system_prompt if system_prompt else SYSTEM_PROMPT_FALLBACK
        try:
            response = requests.post(
                url=ACTIVE_BASE_URL.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {ACTIVE_API_KEY}",
                    "Content-Type":  "application/json",
                    "HTTP-Referer":  "https://localhost/conversation-assistant",
                    "X-Title":       "Conversation Assistant",
                },
                data=json.dumps({
                    "model": ACTIVE_MODEL,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user",   "content": f"Transkript:\n{transcript_text}"}
                    ],
                    "max_tokens":  300,
                    "temperature": 0.7
                }),
                timeout=20
            )
            response.raise_for_status()
            result = response.json()["choices"][0]["message"]["content"].strip()
            self._notify(result)
        except requests.HTTPError as e:
            self._notify(f"[HTTP-Fehler {e.response.status_code}: {e.response.text}]")
        except Exception as e:
            self._notify(f"[Fehler: {e}]")

    def _notify(self, suggestions: str):
        for fn in self._callbacks:
            try:
                fn(suggestions)
            except Exception as e:
                print(f"[AISuggester] Callback-Fehler: {e}")
