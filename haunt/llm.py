"""The Ollama layer: one client, zero retries, template fallback.

haunt's contract is that the whisper must never block or fail a commit.
Everything here returns `None` on any failure; the caller swaps in a
deterministic template. No retry loops, no backoff — a hook that talks to a
local model is better off silent than slow.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import Config

CONTEXT_TOKENS = 4096          # explicit: Ollama's default 2048 clips silently
KEEP_ALIVE = "30m"             # keep the model resident between commits
PROBE_TIMEOUT = 2.0


@dataclass
class Probe:
    status: str  # "ok" | "missing_model" | "down"
    model: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class Ghost:
    """Client for the local model. Never raises — call, time out, fall back."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    # ----------------------------------------------------------------- probe

    def probe(self) -> Probe:
        """Check server and model availability once per run.

        trust_env=False keeps OS proxy variables from intercepting
        localhost traffic — a local-first tool must always talk straight
        to 127.0.0.1.
        """
        try:
            with httpx.Client(timeout=PROBE_TIMEOUT, trust_env=False) as client:
                client.get(f"{self.cfg.host}/")
        except (httpx.HTTPError, OSError):
            return Probe(status="down", model=self.cfg.model)
        try:
            with httpx.Client(timeout=PROBE_TIMEOUT, trust_env=False) as client:
                response = client.post(
                    f"{self.cfg.host}/api/show", json={"model": self.cfg.model}
                )
        except (httpx.HTTPError, OSError):
            return Probe(status="down", model=self.cfg.model)
        if response.status_code == 404:
            return Probe(status="missing_model", model=self.cfg.model)
        if response.status_code >= 400:
            return Probe(status="down", model=self.cfg.model)
        return Probe(status="ok", model=self.cfg.model)

    def hint(self, probe: Probe) -> str | None:
        model = probe.model or self.cfg.model
        if probe.status == "down":
            return f"(haunt: no response from Ollama at {self.cfg.host} — start it, or haunt falls back to template whispers)"
        if probe.status == "missing_model":
            return f"(haunt: model {model} not pulled — run `ollama pull {model}`, or haunt falls back to templates)"
        return None

    # -------------------------------------------------------------- generate

    def generate(
        self,
        *,
        system: str,
        prompt: str,
        max_tokens: int = 120,
        temperature: float = 0.9,
        timeout: float = 8.0,
    ) -> str | None:
        """One attempt at `/api/generate`. Returns text or None. No retries."""
        payload = {
            "model": self.cfg.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
                "num_ctx": CONTEXT_TOKENS,
            },
        }
        try:
            with httpx.Client(
                timeout=httpx.Timeout(connect=2.0, read=timeout, write=5.0, pool=2.0),
                trust_env=False,
            ) as client:
                response = client.post(
                    f"{self.cfg.host}/api/generate", json=payload
                )
        except (httpx.HTTPError, OSError):
            return None
        if response.status_code != 200:
            return None
        try:
            text = response.json().get("response", "")
        except ValueError:
            return None
        text = (text or "").strip()
        return text or None

    # ------------------------------------------------------------------ warm

    def warm(self) -> bool:
        """Best-effort model pre-load so the first real whisper fits its timeout."""
        text = self.generate(
            system=".",
            prompt=".",
            max_tokens=1,
            temperature=0.0,
            timeout=60.0,
        )
        return text is not None
