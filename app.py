"""
AI Music Board - Flask 백엔드
--------------------------------
- 인증: Firebase Auth (프론트에서 발급한 ID 토큰을 Authorization: Bearer <token> 헤더로 전달받아 검증)
- 데이터: Firestore (posts, posts/{id}/comments 서브컬렉션)
- 음원 생성: Hugging Face Inference Providers 경유 Stable Audio 3
- 오디오 파일 저장: 로컬 static/generated/ 폴더 (파일 경로만 Firestore에 저장)
"""

import os
import re
import json
import uuid
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, request, jsonify, render_template, send_from_directory, abort
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials, auth as firebase_auth, firestore

load_dotenv()

# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GENERATED_AUDIO_DIR = os.path.join(BASE_DIR, "static", "generated")
os.makedirs(GENERATED_AUDIO_DIR, exist_ok=True)

HF_TOKEN = os.environ.get("HF_TOKEN")
# Stable Audio 3(stabilityai/stable-audio-3-medium)는 fal(fal-ai) 프로바이더로 서빙되며,
# HF 라우터를 통해 fal 의 경로를 그대로 호출하면 된다. 응답은 오디오 바이너리가 아니라
# {"audio": {"url": "..."}} 형태의 JSON 이다.
HF_MODEL_PATH = os.environ.get(
    "HF_STABLE_AUDIO_MODEL", "fal-ai/stable-audio-3/medium/text-to-audio"
)
HF_API_URL = f"https://router.huggingface.co/fal-ai/{HF_MODEL_PATH}"

FIREBASE_SERVICE_ACCOUNT = os.environ.get(
    "FIREBASE_SERVICE_ACCOUNT_PATH", os.path.join(BASE_DIR, "serviceAccountKey.json")
)

# ---------------------------------------------------------------------------
# OpenAI (오케스트라 악보 생성: 사용자 입력 -> MusicXML)
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

_openai_client = None


def get_openai_client():
    """openai SDK 클라이언트를 지연 초기화한다. 키가 없으면 None."""
    global _openai_client
    if not OPENAI_API_KEY or OPENAI_API_KEY.startswith("sk-xxx"):
        return None
    if _openai_client is None:
        from openai import OpenAI  # 지연 임포트: 미설치 상태에서도 앱은 뜬다

        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def _chat_completion(client, *, max_tokens, temperature=0.7, **kwargs):
    """client.chat.completions.create() 래퍼.

    모델마다 파라미터 요구사항이 달라서 (예: gpt-6-astra 같은 추론형 모델은 `max_tokens` 대신
    `max_completion_tokens` 를 쓰고 `temperature` 커스텀 값을 지원하지 않으며, 모델별 completion
    토큰 상한도 다르다 — gpt-4o 는 16384, gpt-6-astra 는 128000), 모델명에 상관없이 동작하도록
    400 에러가 나면 문제된 파라미터만 제거/치환/축소해서 재시도한다.
    """
    from openai import BadRequestError

    params = dict(model=OPENAI_MODEL, max_tokens=max_tokens, temperature=temperature, **kwargs)
    for _ in range(6):
        try:
            return client.chat.completions.create(**params)
        except BadRequestError as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            param = body.get("param")
            code = body.get("code")
            message = body.get("message") or ""

            if param == "temperature" and "temperature" in params:
                params.pop("temperature")
                continue

            token_param = "max_completion_tokens" if "max_completion_tokens" in params else "max_tokens"
            if param == token_param:
                if code == "unsupported_parameter" and token_param == "max_tokens":
                    params["max_completion_tokens"] = params.pop("max_tokens")
                    continue
                if code == "invalid_value":
                    # "This model supports at most N completion tokens" 형태 메시지에서 상한을 뽑아낸다.
                    m = re.search(r"at most (\d+)", message)
                    if m:
                        params[token_param] = int(m.group(1))
                        continue
            raise
    raise RuntimeError(f"Could not call model '{OPENAI_MODEL}' with compatible parameters.")


# Orchestra instrument catalog (ids must match static/js/instruments.js on the frontend)
# gm: General MIDI program number (0-127). clef: MusicXML clef. range: playable range (concert pitch,
# C4 = middle C) that the composer prompt asks the model to stay within.
ORCHESTRA_INSTRUMENTS = {
    "violin": {"name": "Violin", "gm": 40, "clef": "treble", "range": "G3-A6"},
    "viola": {"name": "Viola", "gm": 41, "clef": "alto", "range": "C3-E6"},
    "cello": {"name": "Cello", "gm": 42, "clef": "bass", "range": "C2-A5"},
    "contrabass": {"name": "Contrabass", "gm": 43, "clef": "bass", "range": "E1-D4"},
    "harp": {"name": "Harp", "gm": 46, "clef": "treble", "range": "C2-C7"},
    "flute": {"name": "Flute", "gm": 73, "clef": "treble", "range": "C4-C7"},
    "piccolo": {"name": "Piccolo", "gm": 72, "clef": "treble", "range": "D5-C8"},
    "oboe": {"name": "Oboe", "gm": 68, "clef": "treble", "range": "Bb3-A6"},
    "clarinet": {"name": "Clarinet", "gm": 71, "clef": "treble", "range": "D3-Bb6"},
    "bassoon": {"name": "Bassoon", "gm": 70, "clef": "bass", "range": "Bb1-Eb5"},
    "trumpet": {"name": "Trumpet", "gm": 56, "clef": "treble", "range": "F#3-Bb5"},
    "french_horn": {"name": "French Horn", "gm": 60, "clef": "treble", "range": "B1-F5"},
    "trombone": {"name": "Trombone", "gm": 57, "clef": "bass", "range": "E2-Bb4"},
    "tuba": {"name": "Tuba", "gm": 58, "clef": "bass", "range": "D1-F4"},
    "timpani": {"name": "Timpani", "gm": 47, "clef": "bass", "range": "D2-A3"},
    "piano": {"name": "Piano", "gm": 0, "clef": "treble", "range": "C2-C7"},
}

DIFFICULTY_GUIDE = {
    "beginner": (
        "Beginner (new to the instrument): mostly whole, half and quarter notes, stepwise motion, "
        "minimal leaps, no syncopation, range within about one octave. Sustaining instruments get long, simple notes."
    ),
    "intermediate": (
        "Intermediate (a few years of playing): eighth notes and simple syncopation allowed, moderate leaps, "
        "some rhythmic contrast between parts, range about 1.5-2 octaves."
    ),
    "advanced": (
        "Advanced (long-time player): sixteenth notes, dotted rhythms, syncopation, wide range, "
        "independent melodic lines and counterpoint per part, but still idiomatic and playable."
    ),
}

# ---------------------------------------------------------------------------
# 실제 작곡가 악보 참고 (music21 에 내장된 퍼블릭 도메인 코퍼스에서 발췌)
# 주의: 코퍼스에 있는 건 대부분 현악4중주/코랄 등 실내악이다 (전곡 오케스트라 악보 X).
# 그래도 실제 해당 작곡가가 쓴 진짜 악보라서, 리듬감·선율 윤곽·화성적 특징의 "참고 자료"로 쓴다.
# ---------------------------------------------------------------------------
REFERENCE_WORKS = {
    "beethoven": {
        "path": "beethoven/opus18no1/movement1",
        "label": "Beethoven — String Quartet No. 1 (Op. 18 No. 1), 1st movement",
        "keywords": ["beethoven"],
    },
    "beethoven_late": {
        "path": "beethoven/opus132",
        "label": "Beethoven — String Quartet No. 15 (Op. 132)",
        "keywords": ["grand", "solemn", "majestic", "heroic", "epic"],
    },
    "mozart": {
        "path": "mozart/k458/movement1",
        "label": "Mozart — String Quartet K.458 \"The Hunt\", 1st movement",
        "keywords": ["mozart", "elegant", "courtly", "graceful"],
    },
    "haydn": {
        "path": "haydn/opus74no1/movement1",
        "label": "Haydn — String Quartet Op. 74 No. 1, 1st movement",
        "keywords": ["haydn", "cheerful", "lively", "bright", "crisp", "fresh"],
    },
    "bach": {
        "path": "bach/bwv1.6",
        "label": "Bach — Chorale BWV 1.6",
        "keywords": ["bach", "baroque", "solemn", "reverent", "devotional"],
    },
    "handel": {
        "path": "handel/rinaldo/Lascia_chio_pianga",
        "label": "Handel — \"Lascia ch'io pianga\" from the opera Rinaldo",
        "keywords": ["handel", "plaintive", "sorrowful", "elegy", "tearful", "mournful"],
    },
    "folk": {
        "path": "essenFolksong/ballad10",
        "label": "European folk melody (Essen Folksong Collection)",
        "keywords": ["folk", "fairy tale", "rustic", "simple", "pastoral"],
    },
}

_reference_excerpt_cache = {}
_M21_DUR_CODE = {
    "whole": "w", "half": "h", "quarter": "q", "eighth": "e",
    "16th": "s", "32nd": "t", "64th": "x",
}


def _summarize_m21_part(part, max_measures=8):
    """music21 Part 를 '마디: 음이름+길이코드' 형태의 압축 텍스트로 요약한다."""
    lines = []
    count = 0
    for m in part.getElementsByClass("Measure"):
        if count >= max_measures:
            break
        toks = []
        for n in m.notesAndRests:
            code = _M21_DUR_CODE.get(n.duration.type, "q")
            if n.isRest:
                toks.append(f"R{code}")
            elif n.isChord:
                toks.append("+".join(p.nameWithOctave for p in n.pitches) + code)
            else:
                toks.append(n.nameWithOctave + code)
        if toks:
            lines.append(f"m{m.number}: " + " ".join(toks))
        count += 1
    return " | ".join(lines)


def _get_reference_excerpt(style_id, max_measures=8):
    """실제 코퍼스 작품에서 멜로디/베이스 파트를 뽑아 GPT 프롬프트에 넣을 텍스트로 만든다."""
    if style_id not in REFERENCE_WORKS:
        return None
    if style_id in _reference_excerpt_cache:
        return _reference_excerpt_cache[style_id]
    try:
        from music21 import corpus  # 지연 임포트: 무거운 라이브러리라 요청 시에만 로드

        info = REFERENCE_WORKS[style_id]
        score = corpus.parse(info["path"])
        parts = list(getattr(score, "parts", []) or [score])
        melody = _summarize_m21_part(parts[0], max_measures)
        bass = _summarize_m21_part(parts[-1], max_measures) if len(parts) > 1 else ""
        text = f"[{info['label']}] (real excerpt, note+duration code: w=whole h=half q=quarter e=eighth s=16th, R=rest)\n"
        text += f"Melody: {melody}"
        if bass and bass != melody:
            text += f"\nBass: {bass}"
        _reference_excerpt_cache[style_id] = text
        return text
    except Exception as exc:  # noqa: BLE001
        print("[Reference excerpt extraction failed]", style_id, exc)
        return None


def _match_reference_style(client, prompt):
    """분위기 프롬프트에 어울리는 실제 참고 작품을 고른다 (키워드 우선, 없으면 GPT)."""
    if not prompt:
        return None
    for style_id, info in REFERENCE_WORKS.items():
        if any(kw.lower() in prompt.lower() for kw in info["keywords"]):
            return style_id
    try:
        options = ", ".join(f"{sid}({info['label']})" for sid, info in REFERENCE_WORKS.items())
        resp = _chat_completion(
            client,
            temperature=0.2,
            max_tokens=60,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "사용자가 원하는 곡 분위기와 가장 잘 어울리는 참고 작품을 목록에서 고른다. "
                        '뚜렷하게 어울리는 게 없으면 null. JSON 으로만 답한다: {"style": "id 또는 null"}'
                    ),
                },
                {"role": "user", "content": f"목록: {options}\n\n분위기: {prompt}"},
            ],
        )
        data = json.loads(resp.choices[0].message.content)
        style = data.get("style")
        return style if style in REFERENCE_WORKS else None
    except Exception as exc:  # noqa: BLE001
        print("[참고 스타일 매칭 실패]", exc)
        return None


app = Flask(__name__)

# ---------------------------------------------------------------------------
# Firebase Admin 초기화 (Auth 토큰 검증 + Firestore)
# ---------------------------------------------------------------------------
if not firebase_admin._apps:
    if os.path.exists(FIREBASE_SERVICE_ACCOUNT):
        cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
        firebase_admin.initialize_app(cred)
    else:
        # 서비스 계정 키가 없으면 앱은 뜨지만 인증/DB 관련 API 는 500 을 반환한다.
        # README 안내에 따라 serviceAccountKey.json 을 준비할 것.
        print(
            f"[경고] Firebase 서비스 계정 키를 찾을 수 없습니다: {FIREBASE_SERVICE_ACCOUNT}\n"
            "        회원가입/로그인 검증, Firestore 저장 기능이 동작하지 않습니다."
        )

db = firestore.client() if firebase_admin._apps else None


# ---------------------------------------------------------------------------
# 인증 헬퍼
# ---------------------------------------------------------------------------
def get_current_user():
    """Authorization: Bearer <idToken> 헤더를 검증하고 uid/email/name 을 반환한다."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    id_token = header.split("Bearer ", 1)[1].strip()
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        return {
            "uid": decoded.get("uid"),
            "email": decoded.get("email"),
            "name": decoded.get("name") or (decoded.get("email", "").split("@")[0]),
        }
    except Exception as exc:  # noqa: BLE001
        print("[Token verification failed]", exc)
        return None


def require_login():
    user = get_current_user()
    if not user:
        abort(401, description="Login required.")
    return user


# ---------------------------------------------------------------------------
# 페이지 라우트 (화면 5종)
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/signup")
def signup_page():
    return render_template("signup.html")


@app.route("/write")
def write_page():
    return render_template("write.html")


@app.route("/orchestra")
def orchestra_page():
    return render_template("orchestra.html")


@app.route("/post/<post_id>")
def detail_page(post_id):
    return render_template("detail.html", post_id=post_id)


# ---------------------------------------------------------------------------
# API: Posts
# ---------------------------------------------------------------------------
@app.route("/api/posts", methods=["GET"])
def list_posts():
    if db is None:
        return jsonify({"error": "Server configuration error (Firestore not initialized)"}), 500

    docs = (
        db.collection("posts")
        .order_by("createdAt", direction=firestore.Query.DESCENDING)
        .stream()
    )
    posts = []
    for d in docs:
        data = d.to_dict()
        data["id"] = d.id
        # Drop the (potentially large) MusicXML body in list view; keep only a presence flag.
        data["hasScore"] = bool(data.pop("musicXml", None))
        posts.append(data)
    return jsonify(posts)


@app.route("/api/posts/<post_id>", methods=["GET"])
def get_post(post_id):
    if db is None:
        return jsonify({"error": "Server configuration error (Firestore not initialized)"}), 500

    doc = db.collection("posts").document(post_id).get()
    if not doc.exists:
        return jsonify({"error": "Post not found."}), 404

    post = doc.to_dict()
    post["id"] = doc.id

    comments_docs = (
        db.collection("posts")
        .document(post_id)
        .collection("comments")
        .order_by("createdAt")
        .stream()
    )
    post["comments"] = []
    for c in comments_docs:
        cd = c.to_dict()
        cd["id"] = c.id
        post["comments"].append(cd)

    return jsonify(post)


@app.route("/api/posts", methods=["POST"])
def create_post():
    user = require_login()
    if db is None:
        return jsonify({"error": "Server configuration error (Firestore not initialized)"}), 500

    body = request.get_json(force=True) or {}
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    prompt = (body.get("prompt") or "").strip()
    audio_url = body.get("audioUrl")
    youtube_url = (body.get("youtubeUrl") or "").strip() or None
    music_xml = body.get("musicXml") or None

    if not title:
        return jsonify({"error": "Please enter a title."}), 400
    if not audio_url and not youtube_url and not music_xml:
        return jsonify({"error": "You need at least one of: AI audio, a YouTube link, or an orchestra score."}), 400
    if music_xml and len(music_xml) > 900_000:
        return jsonify({"error": "The score data is too large."}), 400

    doc_ref = db.collection("posts").document()
    doc_ref.set(
        {
            "title": title,
            "content": content,
            "prompt": prompt,
            "audioUrl": audio_url,
            "youtubeUrl": youtube_url,
            "musicXml": music_xml,
            "authorUid": user["uid"],
            "authorName": user["name"],
            "createdAt": firestore.SERVER_TIMESTAMP,
            "commentCount": 0,
        }
    )
    return jsonify({"id": doc_ref.id}), 201


@app.route("/api/posts/<post_id>/comments", methods=["POST"])
def create_comment(post_id):
    user = require_login()
    if db is None:
        return jsonify({"error": "Server configuration error (Firestore not initialized)"}), 500

    body = request.get_json(force=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Please enter a comment."}), 400

    post_ref = db.collection("posts").document(post_id)
    if not post_ref.get().exists:
        return jsonify({"error": "Post not found."}), 404

    comment_ref = post_ref.collection("comments").document()
    comment_ref.set(
        {
            "text": text,
            "authorUid": user["uid"],
            "authorName": user["name"],
            "createdAt": firestore.SERVER_TIMESTAMP,
        }
    )
    post_ref.update({"commentCount": firestore.Increment(1)})
    return jsonify({"id": comment_ref.id}), 201


# ---------------------------------------------------------------------------
# API: AI audio generation (Stable Audio 3 / Hugging Face Inference Providers)
# ---------------------------------------------------------------------------
@app.route("/api/generate-audio", methods=["POST"])
def generate_audio():
    user = require_login()

    if not HF_TOKEN:
        return jsonify({"error": "The server's HF_TOKEN environment variable is not set."}), 500

    body = request.get_json(force=True) or {}
    prompt = (body.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"error": "Please enter a prompt."}), 400

    headers = {"Authorization": f"Bearer {HF_TOKEN}"}

    try:
        res = requests.post(
            HF_API_URL,
            headers=headers,
            json={"prompt": prompt},
            timeout=300,
        )
    except requests.RequestException as exc:
        return jsonify({"error": f"Audio generation request failed: {exc}"}), 502

    if res.status_code != 200:
        try:
            detail = res.json()
        except ValueError:
            detail = res.text
        return jsonify({"error": "Audio generation failed", "detail": detail}), res.status_code

    try:
        remote_audio_url = res.json()["audio"]["url"]
    except (ValueError, KeyError) as exc:
        return jsonify({"error": f"Couldn't parse the audio generation response: {exc}"}), 502

    try:
        audio_resp = requests.get(remote_audio_url, timeout=60)
        audio_resp.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": f"Failed to download the generated audio: {exc}"}), 502

    ext = "mp3" if remote_audio_url.lower().endswith(".mp3") else "wav"
    filename = f"{user['uid']}_{uuid.uuid4().hex}_{int(time.time())}.{ext}"
    filepath = os.path.join(GENERATED_AUDIO_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(audio_resp.content)

    audio_url = f"/static/generated/{filename}"
    return jsonify({"audioUrl": audio_url})


@app.route("/static/generated/<path:filename>")
def serve_generated_audio(filename):
    return send_from_directory(GENERATED_AUDIO_DIR, filename)


# ---------------------------------------------------------------------------
# API: Orchestra score generation
# GPT only writes a compact text notation (a handful of tokens per measure, e.g. "C4q D4q E4h");
# this server expands it into MusicXML deterministically. That keeps the model's output tiny
# (fast, long scores possible) and the XML always well-formed with exact measure lengths.
# ---------------------------------------------------------------------------
def _strip_code_fence(text: str) -> str:
    """Strip a ```...``` fence if the model wrapped its answer in one."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            body = re.sub(r"^[a-zA-Z]*\n", "", parts[1], count=1)
            text = body.strip()
    return text


COMPOSE_MAX_TOKENS = 64000  # reasoning models spend hidden tokens too; auto-capped per model
PLAN_MAX_TOKENS = 12000
MAX_BRIEF_CHARS = 1500

# divisions = 4 per quarter note, so a sixteenth = 1 unit
DUR_UNITS = {"w": 16, "h": 8, "q": 4, "e": 2, "s": 1}
TYPE_BY_UNITS = {
    24: ("whole", True), 16: ("whole", False), 12: ("half", True), 8: ("half", False),
    6: ("quarter", True), 4: ("quarter", False), 3: ("eighth", True), 2: ("eighth", False),
    1: ("16th", False),
}
REST_FILL_UNITS = [24, 16, 12, 8, 6, 4, 3, 2, 1]
CLEF_MAP = {"treble": ("G", 2), "bass": ("F", 4), "alto": ("C", 3)}
_PITCH_RE = re.compile(r"^([A-Ga-g])(##|bb|#|b|n)?(-?\d)$")
_TOKEN_RE = re.compile(r"^(.*?)([whqes]\.?)(~?)$")
_ACCIDENTAL_ALTER = {None: 0, "n": 0, "#": 1, "##": 2, "b": -1, "bb": -2}
_MARK_RE = re.compile(r"^!(pp|p|mp|mf|f|ff|cresc|dim)$")
_TEMPO_RE = re.compile(r"^!t(\d{2,3})$")
_METER_RE = re.compile(r"^\(\s*(\d{1,2})\s*/\s*(2|4|8)\s*\)\s*")
WORD_MARKS = {"cresc": "cresc.", "dim": "dim."}

# ---- User-adjustable variation controls -------------------------------------------------
VARIATION_DEFAULTS = {
    "repetition": "balanced",   # faithful | balanced | varied
    "dynamics": "expressive",   # none | subtle | expressive | dramatic
    "tempoChanges": False,
    "meterChanges": False,
    "plan": True,               # plan the overall form (sections) before composing
}
REPETITION_GUIDE = {
    "faithful": (
        "Repetition is welcome: restate themes almost literally, use refrains, ostinatos and the % "
        "repeat marker freely (up to about half of the measures). Keep variation modest."
    ),
    "balanced": (
        "Balance repetition and variation: the main theme should return a few times, but every return "
        "must be changed (different octave, harmony, rhythm, ending or instrument). Never use % more "
        "than twice in a row, and never let a 2-measure idea repeat more than twice unchanged."
    ),
    "varied": (
        "Keep developing: do NOT repeat a measure exactly within the same part (use % only for a "
        "tacet or pedal/ostinato figure). Every return of the theme must be transformed (sequence, "
        "inversion, rhythmic displacement, fragmentation, new instrumentation or register). Introduce "
        "genuinely new material at least every 8 measures."
    ),
}
DYNAMICS_GUIDE = {
    "none": "",
    "subtle": "Use a few gentle dynamics (mostly !p to !mf), only where the level really changes.",
    "expressive": (
        "Use the full dynamic range pp-ff with phrase-level shaping: a dynamic at the start of every "
        "instrument's first measure and at each section/phrase change, plus !cresc / !dim where the music "
        "builds or relaxes. Leave a clear quiet passage and a clear loud climax."
    ),
    "dramatic": (
        "Use extreme, dramatic contrasts: sudden !pp after !ff, long !cresc build-ups to an ff climax, "
        "fully different dynamic levels in consecutive sections."
    ),
}
# Average share of measures that duplicate an earlier measure in the same part; above this the
# piece is asked to be rewritten once.
REPETITION_DUP_LIMIT = {"faithful": None, "balanced": 0.45, "varied": 0.25}


def _clean_variation(raw):
    raw = raw if isinstance(raw, dict) else {}
    v = dict(VARIATION_DEFAULTS)
    if raw.get("repetition") in REPETITION_GUIDE:
        v["repetition"] = raw["repetition"]
    if raw.get("dynamics") in DYNAMICS_GUIDE:
        v["dynamics"] = raw["dynamics"]
    for key in ("tempoChanges", "meterChanges", "plan"):
        if key in raw:
            v[key] = bool(raw[key])
    return v


def _key_scale(fifths):
    """Spelled major scale for a key signature, e.g. 1 -> ['G','A','B','C','D','E','F#']."""
    order = ["C", "D", "E", "F", "G", "A", "B"]
    sharps = ["F", "C", "G", "D", "A", "E", "B"]
    flats = ["B", "E", "A", "D", "G", "C", "F"]
    tonic = ["C", "G", "D", "A", "E", "B", "F"][fifths % 7]
    start = order.index(tonic)
    letters = [order[(start + k) % 7] for k in range(7)]
    acc = {}
    if fifths > 0:
        acc = {letter: "#" for letter in sharps[:fifths]}
    elif fifths < 0:
        acc = {letter: "b" for letter in flats[: -fifths]}
    return [letter + acc.get(letter, "") for letter in letters]


def _measure_units(beats, beat_type):
    return beats * 16 // beat_type


def _parse_token(token):
    """'F#5e.' / 'C4+E4+G4h~' / 'Rq' -> note dict, or None if it can't be parsed."""
    m = _TOKEN_RE.match(token)
    if not m:
        return None
    pitch_part, dur, tie = m.groups()
    units = DUR_UNITS[dur[0]]
    if dur.endswith("."):
        if units == 1:
            return None
        units = units * 3 // 2
    if units not in TYPE_BY_UNITS:
        return None
    if pitch_part in ("R", "r"):
        return {"rest": True, "units": units, "pitches": [], "tie": False}
    pitches = []
    for p in pitch_part.split("+"):
        pm = _PITCH_RE.match(p.strip())
        if not pm:
            return None
        step, acc, octave = pm.groups()
        if not 0 <= int(octave) <= 8:
            return None
        pitches.append((step.upper(), _ACCIDENTAL_ALTER[acc], int(octave)))
    return {"rest": False, "units": units, "pitches": pitches, "tie": bool(tie)}


def _rest_fill(units):
    out = []
    for u in REST_FILL_UNITS:
        while units >= u:
            out.append({"rest": True, "units": u, "pitches": [], "tie": False})
            units -= u
    return out


def _whole_rest(measure_units):
    return [{"rest": True, "units": measure_units, "pitches": [], "tie": False, "whole": True}]


def _notes_only(items):
    return [n for n in items if "units" in n]


def _parse_measure(text, measure_units, marks_ok):
    """Parse one measure's tokens (notes + optional !markers) and force it to total measure_units."""
    toks = text.split()
    if not toks or toks == ["R"] or toks == ["r"]:
        return _whole_rest(measure_units)
    items, total, full = [], 0, False
    for t in toks:
        if full:
            break
        if t.startswith("!"):
            m = _MARK_RE.match(t)
            if marks_ok and m:
                items.append({"mark": m.group(1)})
            continue
        n = _parse_token(t)
        if not n:
            continue
        if total + n["units"] > measure_units:
            full = True
            continue
        items.append(n)
        total += n["units"]
    if total < measure_units:
        items.extend(_rest_fill(measure_units - total))
    if all(n["rest"] for n in _notes_only(items)):
        return _whole_rest(measure_units)
    return items


def _measures_from_segments(segments, units_list, count, marks_ok):
    measures = []
    for i, seg in enumerate(segments[:count]):
        seg = seg.strip()
        if seg == "%":
            prev = _notes_only(measures[-1]) if measures else []
            if prev and sum(n["units"] for n in prev) == units_list[i]:
                measures.append([dict(n) for n in prev])
            else:
                measures.append(_whole_rest(units_list[i]))
        else:
            measures.append(_parse_measure(seg, units_list[i], marks_ok))
    while len(measures) < count:
        measures.append(_whole_rest(units_list[len(measures)]))
    return measures


def _global_events(segments, instrument_ids, count, base_meter, base_tempo, variation):
    """Meter / tempo changes are score-wide: collect them across instruments (first instrument that
    states one wins), and return segments with the meter prefix removed."""
    meters, tempos = [], {}
    cleaned = {iid: list(segments.get(iid, [])) for iid in instrument_ids}
    current = base_meter
    current_tempo = base_tempo
    for i in range(count):
        found_meter = None
        for iid in instrument_ids:
            segs = cleaned[iid]
            if i >= len(segs):
                continue
            m = _METER_RE.match(segs[i].strip())
            if m:
                if found_meter is None:
                    found_meter = (int(m.group(1)), int(m.group(2)))
                segs[i] = segs[i].strip()[m.end():]
            if i > 0 and variation["tempoChanges"] and i not in tempos:
                for tok in segs[i].split():
                    tm = _TEMPO_RE.match(tok)
                    if tm:
                        bpm = max(30, min(int(tm.group(1)), 240))
                        if bpm != current_tempo:
                            tempos[i] = bpm
                            current_tempo = bpm
                        break
        if found_meter and variation["meterChanges"] and 1 <= found_meter[0] <= 12:
            current = found_meter
        meters.append(current)
    return meters, tempos, cleaned


def _repetition_stats(parts_measures):
    """Share of (non-rest) measures that exactly duplicate an earlier measure of the same part."""
    per, dup_total, total = {}, 0, 0
    for iid, measures in parts_measures.items():
        seen, dup, n = set(), 0, 0
        for m in measures:
            notes = _notes_only(m)
            if all(x["rest"] for x in notes):
                continue
            sig = tuple((x["rest"], tuple(x["pitches"]), x["units"]) for x in notes)
            n += 1
            if sig in seen:
                dup += 1
            seen.add(sig)
        per[iid] = dup / n if n else 0.0
        dup_total += dup
        total += n
    return {"dup": dup_total / total if total else 0.0, "per": per}


def _parse_notation(text, instrument_ids):
    """Split the model's answer into {instrument_id: [measure text, ...]}."""
    blocks, current = {}, None
    for line in _strip_code_fence(text).splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^@\s*([A-Za-z_]+)\s*:?\s*(.*)$", line)
        if m:
            current = m.group(1).lower()
            blocks.setdefault(current, [])
            if m.group(2):
                blocks[current].append(m.group(2))
        elif current:
            blocks[current].append(line)
    result = {}
    for iid in instrument_ids:
        if not blocks.get(iid):
            continue
        joined = re.sub(r"\bm?\d+\s*:", " ", " ".join(blocks[iid]))
        segments = [s.strip() for s in joined.split("|")]
        while segments and not segments[0]:
            segments.pop(0)
        while segments and not segments[-1]:
            segments.pop()
        result[iid] = segments
    return result


def _plan_form(client, *, mood, measures, beats, beat_type, tempo, fifths, difficulty, instrument_ids, variation):
    """Short planning call: sections of the piece (character, dynamics, texture). Optional; None on failure."""
    try:
        names = ", ".join(ORCHESTRA_INSTRUMENTS[i]["name"] for i in instrument_ids)
        user = f"""Plan the large-scale form of an orchestral piece of exactly {measures} measures ({beats}/{beat_type}, about {tempo} BPM).

Brief from the user: {mood}
Key: fixed at the major scale {' '.join(_key_scale(fifths))} for the whole piece - do not plan key changes, modulations or minor-key sections.
Instruments: {names}
Difficulty: {DIFFICULTY_GUIDE[difficulty]}
Repetition preference: {REPETITION_GUIDE[variation['repetition']]}
Dynamics preference: {DYNAMICS_GUIDE[variation['dynamics']] or 'no dynamic markings'}

Reply with JSON only: {{"sections": [{{"name": "A - heroic theme", "length": 8, "character": "short description of melody/mood", "dynamics": "mf", "texture": "who leads, who accompanies, who rests"}}, ...]}}
Rules: sections are consecutive and their lengths add up to exactly {measures}; typical length 4-16 measures; give the piece real contrast and development (new material, a development or transition, a climax, a quiet passage, a final cadence) instead of repeating one idea; vary the texture/instrumentation between sections."""
        resp = _chat_completion(
            client, temperature=0.9, max_tokens=PLAN_MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a composer planning the form of a piece. Reply with JSON only."},
                {"role": "user", "content": user},
            ],
        )
        sections = json.loads(resp.choices[0].message.content).get("sections") or []
        lines, cursor = [], 1
        for s in sections:
            try:
                length = int(s.get("length") or 0)
            except (TypeError, ValueError):
                continue
            if length <= 0 or cursor > measures:
                continue
            length = min(length, measures - cursor + 1)
            lines.append(
                f"m{cursor}-{cursor + length - 1}: {s.get('name', 'Section')} - {s.get('character', '')}; "
                f"dynamics {s.get('dynamics', '')}; texture: {s.get('texture', '')}"
            )
            cursor += length
        if not lines:
            return None
        if cursor <= measures:
            lines.append(f"m{cursor}-{measures}: Ending - resolve to the tonic with a final cadence")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        print("[Form planning failed]", exc)
        return None


def _compose_prompt(mood, beats, beat_type, tempo, fifths, measures, difficulty,
                    instrument_ids, style_reference, variation, plan_text, feedback):
    measure_units = _measure_units(beats, beat_type)
    scale = _key_scale(fifths)
    inst_lines = "\n".join(
        f"- {iid}: {ORCHESTRA_INSTRUMENTS[iid]['name']}, range {ORCHESTRA_INSTRUMENTS[iid]['range']}"
        for iid in instrument_ids
    )
    style_block = ""
    if style_reference:
        style_block = (
            "\nStyle reference (a real excerpt in a similar notation; take its rhythmic feel, melodic "
            "shape and harmonic color as inspiration, never copy it):\n" + style_reference + "\n"
        )
    plan_block = ""
    if plan_text:
        plan_block = (
            "\nForm plan (follow it measure by measure; each section must sound clearly different from the "
            "previous ones in material, dynamics, register or instrumentation):\n" + plan_text + "\n"
        )
    dyn_guide = DYNAMICS_GUIDE[variation["dynamics"]]
    notation_extra = ""
    if variation["dynamics"] != "none":
        notation_extra += (
            "- Dynamics: put a marker before the note where it starts: !pp !p !mp !mf !f !ff; !cresc / !dim print "
            "\"cresc.\" / \"dim.\". A dynamic stays in effect until the next one in that instrument.\n"
        )
    if variation["tempoChanges"]:
        notation_extra += (
            "- Tempo change: !t<bpm> as a token in a measure (e.g. !t96), written in the FIRST instrument's block only; "
            "it applies to all instruments from that measure on (30-240 BPM). The user turned tempo changes ON, so "
            "actually use them at section boundaries: e.g. slower for a quiet passage, faster for a climax"
            f"{', at least 2-3 changes' if measures >= 24 else ', at least one change'}.\n"
        )
    if variation["meterChanges"]:
        notation_extra += (
            "- Meter change: start a measure with (N/D), e.g. (3/4) C4q D4q E4q. It stays in effect until the next "
            "change; write it in EVERY instrument's block at that measure; N is 1-12, D is 2, 4 or 8; the measure must "
            "then total N*16/D units. The user turned meter changes ON, so actually use at least one for contrast "
            "(e.g. a passage in 3/4 or 6/8 or 2/4), and say it in every block.\n"
        )
    feedback_block = f"\nREVISION NOTE: {feedback}\n" if feedback else ""
    return f"""Compose an orchestral piece.

Brief from the user (may contain several requirements; follow all of them):
{mood}

Time signature: {beats}/{beat_type}  (one measure = {measure_units} units; w=16 h=8 q=4 e=2 s=1)
Tempo: quarter note = {tempo} BPM
Key: major scale {' '.join(scale)} (key signature has {abs(fifths)} {'sharps' if fifths > 0 else 'flats' if fifths < 0 else 'accidentals'})
Length: exactly {measures} measures
Difficulty: {DIFFICULTY_GUIDE[difficulty]}

Instruments (one block each, in this order; keep every note inside the instrument's range):
{inst_lines}
{style_block}{plan_block}
Variation: {REPETITION_GUIDE[variation['repetition']]}
Dynamics: {dyn_guide or 'Do not write any dynamic markings.'}

Musical requirements:
- Write a real piece, not scales: clear phrases (4 or 8 bars), a memorable theme, contrast between sections when the piece is long, and a proper ending (final cadence on the tonic, last note held).
- Give each instrument a role (melody, countermelody, harmony, bass, rhythm). Instruments may rest when they are not needed, and parts should interlock rather than all move in unison.
- Chords and harmonies must fit together; bass instruments outline the harmony.
- Never copy a measure and only change one note; when something returns, really transform it.
{feedback_block}
Notation (plain text only, no markdown, no explanations):
@<instrument_id>
<measure 1> | <measure 2> | ... | <measure {measures}>

- A measure is space-separated tokens. Note: <letter><accidental?><octave><duration>, e.g. C4q  F#5e  Bb3h.  (C4 = middle C)
- Chord: join pitches with + and put the duration last, e.g. C4+E4+G4h
- Rest: R<duration>, e.g. Rq. A bare R is a rest for the whole measure.
- Duration letters: w whole, h half, q quarter, e eighth, s sixteenth; a trailing . dots it (x1.5). No triplets.
- Tie: append ~ to a note to tie it to the next note of the same pitch, e.g. C4h~ C4q
- A measure consisting only of % repeats the previous measure of the same instrument.
{notation_extra}- Pitches are absolute: ALWAYS write # or b explicitly for sharps/flats (in this key: {' '.join(scale)}), and no accidental means natural.
- Every measure must add up to exactly the measure length in units.

Example for 4/4 (violin, 2 measures):
@violin
{'!mf ' if variation['dynamics'] != 'none' else ''}C5q D5q E5e F5e G5q | A5h. Rq"""


def _compose_notation(client, *, instrument_ids, measures, **prompt_args):
    """Ask the model for the compact notation; returns {instrument_id: [measure text, ...]}."""
    prompt = _compose_prompt(measures=measures, instrument_ids=instrument_ids, **prompt_args)
    last_error = None
    for _ in range(2):
        resp = _chat_completion(
            client,
            temperature=0.9,
            max_tokens=COMPOSE_MAX_TOKENS,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert orchestral composer and arranger. You write scores in a compact "
                        "plain-text notation exactly as specified by the user and output nothing else."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        choice = resp.choices[0]
        segments = _parse_notation(choice.message.content or "", instrument_ids)
        missing = [i for i in instrument_ids if len(segments.get(i, [])) < max(1, measures // 2)]
        if not missing:
            return segments
        if choice.finish_reason == "length":
            last_error = "The response was cut off. Try fewer instruments or measures."
        else:
            names = ", ".join(ORCHESTRA_INSTRUMENTS[i]["name"] for i in missing)
            last_error = f"Didn't receive usable parts for: {names}."
    raise ValueError(last_error + " Please try again.")


def _time_xml(beats, beat_type):
    return f"<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>"


def _tempo_xml(bpm):
    return (
        '<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
        f'<per-minute>{bpm}</per-minute></metronome></direction-type><sound tempo="{bpm}"/></direction>'
    )


def _build_musicxml(instrument_ids, parts_measures, meters, tempos, fifths, tempo):
    score_parts, part_xml = [], []
    for idx, iid in enumerate(instrument_ids):
        meta = ORCHESTRA_INSTRUMENTS[iid]
        pid = f"P{idx + 1}"
        score_parts.append(
            f'<score-part id="{pid}"><part-name>{meta["name"]}</part-name>'
            f'<score-instrument id="{pid}-I1"><instrument-name>{meta["name"]}</instrument-name></score-instrument>'
            f'<midi-instrument id="{pid}-I1"><midi-channel>{min(idx + 1, 16)}</midi-channel>'
            f'<midi-program>{meta["gm"] + 1}</midi-program></midi-instrument></score-part>'
        )
        clef_sign, clef_line = CLEF_MAP[meta["clef"]]
        open_ties = set()
        measures_xml = []
        for m_idx, items in enumerate(parts_measures[iid], start=1):
            frags = []
            beats, beat_type = meters[m_idx - 1]
            if m_idx == 1:
                frags.append(
                    "<attributes><divisions>4</divisions>"
                    f"<key><fifths>{fifths}</fifths><mode>major</mode></key>{_time_xml(beats, beat_type)}"
                    f"<clef><sign>{clef_sign}</sign><line>{clef_line}</line></clef></attributes>"
                )
                if idx == 0:
                    frags.append(_tempo_xml(tempo))
            else:
                if meters[m_idx - 1] != meters[m_idx - 2]:
                    frags.append(f"<attributes>{_time_xml(beats, beat_type)}</attributes>")
                if idx == 0 and (m_idx - 1) in tempos:
                    frags.append(_tempo_xml(tempos[m_idx - 1]))
            for n in items:
                if "mark" in n:
                    mark = n["mark"]
                    if mark in WORD_MARKS:
                        frags.append(
                            '<direction placement="below"><direction-type>'
                            f'<words font-style="italic">{WORD_MARKS[mark]}</words></direction-type></direction>'
                        )
                    else:
                        frags.append(
                            '<direction placement="below"><direction-type>'
                            f"<dynamics><{mark}/></dynamics></direction-type></direction>"
                        )
                    continue
                type_name, dotted = TYPE_BY_UNITS[n["units"]]
                dot = "<dot/>" if dotted else ""
                if n["rest"]:
                    open_ties = set()
                    if n.get("whole"):
                        frags.append(f'<note><rest measure="yes"/><duration>{n["units"]}</duration></note>')
                    else:
                        frags.append(f'<note><rest/><duration>{n["units"]}</duration><type>{type_name}</type>{dot}</note>')
                    continue
                next_open = set()
                for p_idx, pitch in enumerate(n["pitches"]):
                    step, alter, octave = pitch
                    tie_stop = pitch in open_ties
                    tie_start = n["tie"]
                    if tie_start:
                        next_open.add(pitch)
                    xml = "<note>" + ("<chord/>" if p_idx else "")
                    xml += f"<pitch><step>{step}</step>" + (f"<alter>{alter}</alter>" if alter else "")
                    xml += f"<octave>{octave}</octave></pitch><duration>{n['units']}</duration>"
                    xml += ('<tie type="stop"/>' if tie_stop else "") + ('<tie type="start"/>' if tie_start else "")
                    xml += f"<type>{type_name}</type>{dot}"
                    if tie_stop or tie_start:
                        xml += "<notations>" + ('<tied type="stop"/>' if tie_stop else "")
                        xml += ('<tied type="start"/>' if tie_start else "") + "</notations>"
                    frags.append(xml + "</note>")
                open_ties = next_open
            measures_xml.append(f'<measure number="{m_idx}">{"".join(frags)}</measure>')
        part_xml.append(f'<part id="{pid}">{"".join(measures_xml)}</part>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">'
        f'<score-partwise version="3.1"><part-list>{"".join(score_parts)}</part-list>{"".join(part_xml)}</score-partwise>'
    )


@app.route("/api/orchestra/recommend", methods=["POST"])
def orchestra_recommend():
    """분위기 프롬프트를 받아 어울리는 악기 id 목록과 한 줄 이유를 돌려준다."""
    require_login()
    client = get_openai_client()
    if client is None:
        return jsonify({"error": "The server's OPENAI_API_KEY is not set."}), 500

    body = request.get_json(force=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"recommended": [], "reason": ""})

    catalog = ", ".join(f"{k}({v['name']})" for k, v in ORCHESTRA_INSTRUMENTS.items())
    try:
        resp = _chat_completion(
            client,
            temperature=0.4,
            max_tokens=400,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an orchestration advisor. Read the mood the user wants for their piece, "
                        "and pick the instruments from the given list that best fit that mood. "
                        'Reply with JSON only: {"recommended": ["id", ...], "reason": "one English sentence explaining why"}. '
                        "recommended must only contain ids from the allowed list below."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Allowed ids: {catalog}\n\n"
                        f"Desired mood: {prompt}\n\n"
                        "Put 3-8 instruments that fit this mood in recommended, and explain why in one sentence in reason."
                    ),
                },
            ],
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Failed to generate recommendations: {exc}"}), 502

    recommended = [
        i for i in (data.get("recommended") or []) if i in ORCHESTRA_INSTRUMENTS
    ]
    reason = (data.get("reason") or "").strip()
    return jsonify({"recommended": recommended, "reason": reason})


@app.route("/api/orchestra/generate", methods=["POST"])
def orchestra_generate():
    """Settings + instruments + variation controls -> GPT writes compact notation -> server builds MusicXML."""
    require_login()
    client = get_openai_client()
    if client is None:
        return jsonify({"error": "The server's OPENAI_API_KEY is not set."}), 500

    body = request.get_json(force=True) or {}
    prompt = (body.get("prompt") or "").strip()[:MAX_BRIEF_CHARS]
    instrument_ids = list(
        dict.fromkeys(i for i in (body.get("instruments") or []) if i in ORCHESTRA_INSTRUMENTS)
    )
    difficulty = body.get("difficulty") if body.get("difficulty") in DIFFICULTY_GUIDE else "beginner"
    variation = _clean_variation(body.get("variation"))

    try:
        beats = int(body.get("beats", 4))
        beat_type = int(body.get("beatType", 4))
        tempo = int(body.get("tempo", 120))
        fifths = int(body.get("fifths", 0))
        measures = int(body.get("measures", 8))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid settings."}), 400

    if not instrument_ids:
        return jsonify({"error": "Please select at least one instrument."}), 400
    beats = max(1, min(beats, 12))
    beat_type = beat_type if beat_type in (2, 4, 8) else 4
    tempo = max(30, min(tempo, 240))
    fifths = max(-7, min(fifths, 7))
    measures = max(2, min(measures, 120))

    mood = prompt or "No particular request: write something pleasant, natural and musical."

    # Two short, independent preparation calls run in parallel:
    #  - a real composer excerpt (if the brief matches one) as style inspiration
    #  - a form plan for longer pieces, so the model has sections to follow instead of copying measures
    with ThreadPoolExecutor(max_workers=2) as pool:
        style_future = pool.submit(_match_reference_style, client, prompt)
        plan_future = None
        if variation["plan"] and measures >= 12:
            plan_future = pool.submit(
                _plan_form, client, mood=mood, measures=measures, beats=beats, beat_type=beat_type,
                tempo=tempo, fifths=fifths, difficulty=difficulty, instrument_ids=instrument_ids, variation=variation,
            )
        style_id = style_future.result()
        plan_text = plan_future.result() if plan_future else None
    style_reference = _get_reference_excerpt(style_id) if style_id else None

    marks_ok = variation["dynamics"] != "none"

    def compose(feedback=None):
        segments = _compose_notation(
            client,
            instrument_ids=instrument_ids, measures=measures, beats=beats, beat_type=beat_type,
            mood=mood, tempo=tempo, fifths=fifths, difficulty=difficulty,
            style_reference=style_reference, variation=variation, plan_text=plan_text, feedback=feedback,
        )
        meters, tempos, cleaned = _global_events(
            segments, instrument_ids, measures, (beats, beat_type), tempo, variation
        )
        units_list = [_measure_units(b, t) for b, t in meters]
        parts = {
            iid: _measures_from_segments(cleaned.get(iid, []), units_list, measures, marks_ok)
            for iid in instrument_ids
        }
        return meters, tempos, parts, _repetition_stats(parts)

    try:
        meters, tempos, parts_measures, stats = compose()
        retried = False
        limit = REPETITION_DUP_LIMIT[variation["repetition"]]
        if limit is not None and measures >= 16 and stats["dup"] > limit:
            worst = sorted(stats["per"].items(), key=lambda kv: kv[1], reverse=True)[:3]
            feedback = (
                f"Your previous attempt repeated measures too much: about {round(stats['dup'] * 100)}% of the "
                "measures were exact copies of an earlier measure in the same part (worst: "
                + ", ".join(f"{ORCHESTRA_INSTRUMENTS[i]['name']} {round(r * 100)}%" for i, r in worst)
                + "). Write the whole piece again with far more variety: no exact repeated measures, transform "
                "every returning idea, and follow the requested variation level strictly."
            )
            try:
                second = compose(feedback)
                retried = True
                if second[3]["dup"] < stats["dup"]:
                    meters, tempos, parts_measures, stats = second
            except Exception as exc:  # noqa: BLE001 - keep the first result
                print("[Repetition retry failed]", exc)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Score generation request failed: {exc}"}), 502

    final_xml = _build_musicxml(instrument_ids, parts_measures, meters, tempos, fifths, tempo)

    return jsonify(
        {
            "musicXml": final_xml,
            "meta": {
                "instruments": instrument_ids,
                "beats": beats,
                "beatType": beat_type,
                "tempo": tempo,
                "fifths": fifths,
                "measures": measures,
                "difficulty": difficulty,
                "truncated": False,
                "variation": variation,
                "formPlan": plan_text,
                "repeatedMeasureShare": round(stats["dup"], 2),
                "rewroteForVariety": retried,
                "tempoChanges": len(tempos),
                "meterChanges": sum(1 for i in range(1, len(meters)) if meters[i] != meters[i - 1]),
                "referenceWork": REFERENCE_WORKS[style_id]["label"] if style_id and style_reference else None,
            },
        }
    )


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(401)
def unauthorized(e):
    return jsonify({"error": str(e.description) if hasattr(e, "description") else "Login required."}), 401


if __name__ == "__main__":
    app.run(debug=True, port=5000)