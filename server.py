import json
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

ROOT_DIR = Path(__file__).resolve().parent.parent
TRANSLATOR_DIR = Path(__file__).resolve().parent

for env_path in (ROOT_DIR / ".env", TRANSLATOR_DIR / ".env"):
    if env_path.exists():
        load_dotenv(env_path, encoding="utf-8-sig")

API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
CHUNK_SIZE = 6000
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"

app = Flask(__name__, static_folder=".")
CORS(app)

if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY가 설정되지 않았습니다. "
        "프로젝트 루트의 .env 파일을 저장했는지 확인해 주세요."
    )

LANG_NAMES = {
    "en": "영어", "ja": "일본어", "zh": "중국어", "ko": "한국어",
    "es": "스페인어", "fr": "프랑스어", "de": "독일어", "ru": "러시아어",
    "pt": "포르투갈어", "it": "이탈리아어", "vi": "베트남어", "th": "태국어",
    "id": "인도네시아어", "ar": "아랍어", "auto": "자동 감지",
}


def korean_ratio(text: str) -> float:
    if not text.strip():
        return 0.0
    korean = len(re.findall(r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]", text))
    letters = len(re.findall(r"\S", text))
    return korean / letters if letters else 0.0


def split_into_chunks(text: str, max_size: int = CHUNK_SIZE) -> list[str]:
    if len(text) <= max_size:
        return [text]

    chunks: list[str] = []
    paragraphs = re.split(r"(\n\n+)", text)
    current = ""

    for part in paragraphs:
        if len(current + part) <= max_size:
            current += part
        else:
            if current:
                chunks.append(current)
            if len(part) <= max_size:
                current = part
            else:
                sentences = re.split(r"(?<=[.!?。！？\n])\s*", part)
                current = ""
                for sentence in sentences:
                    if len(current + sentence) <= max_size:
                        current += sentence
                    else:
                        if current:
                            chunks.append(current)
                        if len(sentence) <= max_size:
                            current = sentence
                        else:
                            for i in range(0, len(sentence), max_size):
                                chunks.append(sentence[i : i + max_size])
                            current = ""
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def gemini_generate(prompt: str, temperature: float = 0.2) -> str:
    response = requests.post(
        GEMINI_URL,
        params={"key": API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature},
        },
        timeout=120,
    )
    if not response.ok:
        detail = response.text[:300]
        raise RuntimeError(f"Gemini API 오류 ({response.status_code}): {detail}")

    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini 응답 형식을 해석할 수 없습니다.") from exc


def detect_language(text: str) -> str:
    sample = text[:800]
    prompt = (
        "Identify the primary language of the text below.\n"
        "Reply with ONLY the ISO 639-1 code (e.g. en, ja, zh, ko, fr, de).\n\n"
        f"Text:\n{sample}"
    )
    code = gemini_generate(prompt, temperature=0.0).lower().strip()
    code = re.sub(r"[^a-z-]", "", code.split()[0] if code else "auto")
    return code if code else "auto"


def translate_chunk(text: str, source_lang: str) -> str:
    prompt = (
        "You are a professional translator.\n"
        "Translate the following text into natural, fluent Korean.\n"
        "Preserve original formatting, line breaks, lists, and technical terms accurately.\n"
        "If the text is already Korean, return it unchanged.\n"
        "Reply with ONLY the Korean translation. No explanations or notes.\n\n"
        f"Source language hint: {source_lang}\n\n"
        f"Text:\n{text}"
    )
    return gemini_generate(prompt)


def normalize_summary_to_five_lines(summary: str) -> str:
    lines = [re.sub(r"^[\d\.\-\*•]+\s*", "", line).strip() for line in summary.splitlines()]
    lines = [line for line in lines if line]

    if not lines:
        sentences = re.split(r"(?<=[.!?。！？])\s+", summary.strip())
        lines = [s.strip() for s in sentences if s.strip()]

    if len(lines) > 5:
        lines = lines[:5]

    return "\n".join(lines)


def summarize_text(text: str) -> str:
    prompt = (
        "You are a professional summarizer.\n"
        "Summarize the following Korean text in EXACTLY 5 lines.\n"
        "Rules:\n"
        "- Write exactly 5 lines, one key point per line\n"
        "- Each line must be one complete Korean sentence\n"
        "- Keep each line concise and easy to read aloud\n"
        "- No numbering, bullets, titles, or extra explanations\n"
        "- Output only the 5 Korean summary lines separated by newlines\n\n"
        f"Text:\n{text[:12000]}"
    )
    raw = gemini_generate(prompt, temperature=0.3)
    return normalize_summary_to_five_lines(raw)


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "model": MODEL_NAME,
        "provider": "gemini",
    })


@app.route("/api/translate", methods=["POST"])
def translate():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "번역할 텍스트가 비어 있습니다."}), 400

    try:
        if korean_ratio(text) >= 0.4:
            source_lang = "ko"
        else:
            source_lang = detect_language(text)

        if source_lang == "ko":
            return jsonify({
                "translation": text,
                "sourceLang": "ko",
                "sourceLangName": LANG_NAMES["ko"],
                "alreadyKorean": True,
            })

        chunks = split_into_chunks(text)
        translated_parts = [translate_chunk(chunk, source_lang) for chunk in chunks]

        return jsonify({
            "translation": "".join(translated_parts),
            "sourceLang": source_lang,
            "sourceLangName": LANG_NAMES.get(source_lang, source_lang),
            "alreadyKorean": False,
            "chunks": len(chunks),
        })
    except Exception as exc:
        return jsonify({"error": f"번역 중 오류가 발생했습니다: {exc}"}), 500


@app.route("/api/summarize", methods=["POST"])
def summarize():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "요약할 텍스트가 비어 있습니다."}), 400

    try:
        summary = summarize_text(text)
        lines = [line for line in summary.splitlines() if line.strip()]
        return jsonify({"summary": summary, "lines": lines, "lineCount": len(lines)})
    except Exception as exc:
        return jsonify({"error": f"요약 중 오류가 발생했습니다: {exc}"}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"문서 번역기 서버 시작 → http://localhost:{port}")
    print(f"Gemini 모델: {MODEL_NAME}")
    app.run(host="0.0.0.0", port=port, debug=False)
