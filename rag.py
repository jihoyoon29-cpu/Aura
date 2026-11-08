"""Small RAG layer for the orchestra generator.

The knowledge base lives in ``knowledge/*.json`` (paraphrased facts with source URLs):
  - instruments.json          : Philharmonia Orchestra instrument guides (range, timbre, role per instrument)
  - musicxml_midi_part.json   : W3C MusicXML 4.0 tutorial, "The MIDI-compatible part"

Two ways to use it:
  - ``instrument_notes(ids)``  : tag-based lookup for the instruments the user selected (no API call)
  - ``search(client, query)``  : semantic search (OpenAI embeddings, cached on disk in knowledge/index.json)

If embeddings are unavailable the search falls back to simple keyword overlap, so the site keeps working.
"""
import hashlib
import json
import os
import re
import threading

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge")
INDEX_PATH = os.path.join(KNOWLEDGE_DIR, "index.json")
EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")

_lock = threading.Lock()
_chunks = None  # list of dicts, loaded once
_vectors = {}  # chunk id -> embedding (list[float])


def _load_json(name):
    with open(os.path.join(KNOWLEDGE_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def chunks():
    """All knowledge chunks: {id, scope, instrument, topic, text, source, url}."""
    global _chunks
    if _chunks is not None:
        return _chunks
    with _lock:
        if _chunks is not None:
            return _chunks
        out = []
        try:
            inst = _load_json("instruments.json")
            for iid, item in inst["instruments"].items():
                for c in item["chunks"]:
                    out.append({
                        "id": f"inst:{iid}:{c['topic']}",
                        "scope": "instrument",
                        "instrument": iid,
                        "topic": c["topic"],
                        "text": f"{item['name']} ({c['topic']}): {c['text']}",
                        "source": inst["source"],
                        "url": item["url"],
                    })
            xml = _load_json("musicxml_midi_part.json")
            for c in xml["chunks"]:
                out.append({
                    "id": f"xml:{c['topic']}",
                    "scope": "musicxml",
                    "instrument": None,
                    "topic": c["topic"],
                    "text": f"MusicXML ({c['topic']}): {c['text']}",
                    "source": xml["source"],
                    "url": xml["url"],
                })
        except (OSError, KeyError, ValueError):
            out = []
        _chunks = out
        return _chunks


def instrument_notes(instrument_ids, topics=("timbre", "role")):
    """Knowledge for specific instruments, without any API call. Returns [chunk, ...]."""
    wanted = set(instrument_ids)
    return [c for c in chunks() if c["scope"] == "instrument" and c["instrument"] in wanted and c["topic"] in topics]


def _hash(text):
    return hashlib.sha256((EMBED_MODEL + "\n" + text).encode("utf-8")).hexdigest()[:16]


def _ensure_vectors(client):
    """Embed every chunk that is not cached yet (one batched call) and persist the cache."""
    with _lock:
        if _vectors:
            return True
        cache = {}
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                cache = json.load(f).get("vectors", {})
        except (OSError, ValueError):
            pass
        allc = chunks()
        todo = [c for c in allc if cache.get(c["id"], {}).get("h") != _hash(c["text"])]
        if todo:
            try:
                resp = client.embeddings.create(model=EMBED_MODEL, input=[c["text"] for c in todo])
            except Exception:  # noqa: BLE001 - search falls back to keywords
                return False
            for c, d in zip(todo, resp.data):
                cache[c["id"]] = {"h": _hash(c["text"]), "v": d.embedding}
            try:
                with open(INDEX_PATH, "w", encoding="utf-8") as f:
                    json.dump({"model": EMBED_MODEL, "vectors": cache}, f)
            except OSError:
                pass
        for c in allc:
            if c["id"] in cache:
                _vectors[c["id"]] = cache[c["id"]]["v"]
        return bool(_vectors)


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _tokens(text):
    return set(re.findall(r"[a-z]{3,}", text.lower()))


def search(client, query, k=6, scope=None):
    """Top-k chunks for a query (semantic if embeddings work, otherwise keyword overlap)."""
    pool = [c for c in chunks() if scope is None or c["scope"] == scope]
    if not pool or not query.strip():
        return []
    if client is not None and _ensure_vectors(client):
        try:
            q = client.embeddings.create(model=EMBED_MODEL, input=[query]).data[0].embedding
            scored = [(_cosine(q, _vectors[c["id"]]), c) for c in pool if c["id"] in _vectors]
            scored.sort(key=lambda t: t[0], reverse=True)
            return [c for _, c in scored[:k]]
        except Exception:  # noqa: BLE001
            pass
    qt = _tokens(query)
    scored = sorted(((len(qt & _tokens(c["text"])), c) for c in pool), key=lambda t: t[0], reverse=True)
    return [c for s, c in scored[:k] if s > 0]


def format_notes(chunk_list, max_chars=2500):
    """Compact bullet text for a prompt (stops at max_chars)."""
    lines, total = [], 0
    for c in chunk_list:
        line = "- " + c["text"]
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def sources(chunk_list):
    """Unique {source, url} pairs for attribution."""
    seen, out = set(), []
    for c in chunk_list:
        if c["url"] not in seen:
            seen.add(c["url"])
            out.append({"source": c["source"], "url": c["url"]})
    return out
