"""Cached English-to-Spanish translation of the five displayed items per source."""
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path
from datetime import datetime

MODEL_URL = "https://argos-net.com/v1/translate-en_es-1_0.argosmodel"
MODEL_VERSION = "argos-en-es-1.0"
CACHE = Path(__file__).resolve().parents[1] / ".cache" / "news-translation"

def fingerprint(row):
    return hashlib.sha256(json.dumps([row.get("title", ""), row.get("desc", "")], ensure_ascii=False).encode()).hexdigest()

def load_model():
    import ctranslate2
    import sentencepiece
    root = CACHE / "en_es"
    if not (root / "model" / "model.bin").is_file() or not (root / "sentencepiece.model").is_file():
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "Mozilla/5.0 (GasData Argentina)"})
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
        CACHE.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            # The model is data only; exclude training/runtime files we don't use.
            for name in archive.namelist():
                if name.startswith("en_es/model/") or name in ("en_es/sentencepiece.model", "en_es/metadata.json"):
                    target = (CACHE / name).resolve()
                    if not target.is_relative_to(CACHE.resolve()): raise ValueError("Invalid model archive path")
                    if not name.endswith("/"): archive.extract(name, CACHE)
    tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(root / "sentencepiece.model"))
    translator = ctranslate2.Translator(str(root / "model"), device="cpu", compute_type="int8", inter_threads=1, intra_threads=2)
    return tokenizer, translator

def translate_news(d, iso):
    selected = []
    counts = {}
    def timestamp(row):
        try: return datetime.fromisoformat(row.get("publishedAt", "")).timestamp()
        except (ValueError, TypeError): return 0
    for row in sorted(d.get("news", []), key=timestamp, reverse=True):
        if row.get("edition") != "international" or row.get("dateType") == "unknown": continue
        source = row.get("source", "")
        if counts.get(source, 0) >= 5: continue
        counts[source] = counts.get(source, 0) + 1
        selected.append(row)
    pending = [row for row in selected if row.get("translationHash") != fingerprint(row) or not row.get("titleEs")]
    state = d.setdefault("newsTranslation", {})
    if not pending:
        state.update(checkedAt=iso(), status="unchanged", translated=0, available=len(selected), error=None)
        return
    try:
        tokenizer, translator = load_model()
        for row in pending:
            originals = [row.get("title", ""), row.get("desc", "")]
            parts = [re.split(r"(?<=[.!?])\s+(?=[A-Z])", value) if value else [] for value in originals]
            sentences = [sentence for group in parts for sentence in group]
            outputs = translator.translate_batch(
                [tokenizer.encode(value, out_type=str) for value in sentences],
                beam_size=4, replace_unknowns=True, max_decoding_length=256,
                length_penalty=0.2,
            )
            translated = [tokenizer.decode(result.hypotheses[0]).strip() for result in outputs]
            pos = 0
            values = []
            for group in parts:
                values.append(" ".join(translated[pos:pos+len(group)]))
                pos += len(group)
            if not values[0]: raise ValueError("Empty translated title")
            row.update(titleEs=values[0], descEs=values[1], translatedAt=iso(),
                       translationHash=fingerprint(row), translationEngine=MODEL_VERSION)
        state.update(checkedAt=iso(), status="updated", translated=len(pending), available=len(selected), error=None)
    except Exception as error:
        # A transient model/download failure never discards original news or cached translations.
        state.update(checkedAt=iso(), status="pending", error=str(error)[:220],
                     available=sum(bool(row.get("titleEs")) for row in selected))
