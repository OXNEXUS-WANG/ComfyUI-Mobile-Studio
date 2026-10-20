# MIT License
# Independent, permissive sentence-boundary shim for Argos Translate.
# This is NOT the upstream MiniSBD project and contains no upstream code.
import re


class SBDetect:
    def __init__(self, lang=None, use_gpu=False):
        self.lang = lang
        self.use_gpu = bool(use_gpu)

    def sentences(self, text):
        text = str(text or "")
        if not text.strip():
            return []
        # Split after common Chinese/English sentence punctuation.
        parts = re.split(r"(?<=[。！？!?；;\.])\s*", text)
        out = []
        for part in parts:
            part = part.strip()
            if part:
                out.append(part)
        return out or [text]


class _Models:
    cache_dir = ""

    def list_models(self):
        return ["zh", "zh-hans", "zh-hant", "en", "ja", "ko"]


models = _Models()
