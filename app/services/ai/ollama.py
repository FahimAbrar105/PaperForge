"""Local Ollama server (optional). Nothing leaves the user's computer."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

from app.services.ai.base import AIBadResponse, AIProvider, AIUnavailable, extract_json


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = self.last_model = model.strip()
        self._reachable: bool | None = None

    def _valid_url(self) -> bool:
        parsed = urllib.parse.urlparse(self.base_url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def available(self) -> bool:
        if not self.model or not self._valid_url():
            return False
        if self._reachable is None:
            try:
                with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=2) as resp:
                    self._reachable = resp.status == 200
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, http.client.HTTPException):
                self._reachable = False
        return self._reachable

    def generate_json(self, system: str, prompt: str, timeout_s: int = 180) -> dict:
        if not self.available():
            raise AIUnavailable(f"Ollama is not running at {self.base_url}")
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        req = urllib.request.Request(f"{self.base_url}/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise AIUnavailable(f"Ollama model '{self.model}' is not installed (run: ollama pull {self.model})") from None
            raise AIUnavailable(f"Ollama HTTP error {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AIUnavailable(f"Ollama unreachable ({exc.__class__.__name__})") from None
        except http.client.HTTPException as exc:
            raise AIBadResponse(f"Ollama's answer was incomplete ({exc.__class__.__name__})") from None
        except ValueError:  # not JSON, or not UTF-8
            raise AIBadResponse("Ollama returned a non-JSON HTTP body") from None
        message = payload.get("message") if isinstance(payload, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise AIBadResponse("Unexpected Ollama response shape")
        return extract_json(text)
