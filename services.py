import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
TRANSLATOR_DIR = Path(__file__).resolve().parent

for env_path in (ROOT_DIR / ".env", TRANSLATOR_DIR / ".env"):
    if env_path.exists():
        load_dotenv(env_path, encoding="utf-8-sig")

CHUNK_SIZE = 6000
FALLBACK_CHUNK_SIZE = 4500

LANG_NAMES = {
    "en": "영어", "ja": "일본어", "zh": "중국어", "ko": "한국어",
    "es": "스페인어", "fr": "프랑스어", "de": "독일어", "ru": "러시아어",
    "pt": "포르투갈어", "it": "이탈리아어", "vi": "베트남어", "th": "태국어",
    "id": "인도네시아어", "ar": "아랍어", "auto": "자동 감지",
}


def get_config(secrets: dict | None = None) -> dict:
    secrets = secrets or {}
    api_key = (secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    model = (secrets.get("GEMINI_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    return {"api_key": api_key, "model": model, "gemini_ready": bool(api_key)}


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


def gemini_generate(prompt: str, config: dict, temperature: float = 0.2) -> str:
    if not config["gemini_ready"]:
        raise RuntimeError("Gemini API 키가 설정되지 않았습니다.")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config['model']}:generateContent"
    )
    response = requests.post(
        url,
        params={"key": config["api_key"]},
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


def fallback_detect_language(text: str) -> str:
    sample = text[:500]
    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "ko", "dt": "t", "q": sample},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()[2] or "auto"
    except Exception:
        return "auto"


def fallback_translate_chunk(text: str, source_lang: str = "auto") -> str:
    response = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": source_lang or "auto", "tl": "ko", "dt": "t", "q": text},
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError("기본 번역 요청에 실패했습니다.")
    data = response.json()
    return "".join(part[0] for part in data[0] if part and part[0])


def detect_language_gemini(text: str, config: dict) -> str:
    sample = text[:800]
    prompt = (
        "Identify the primary language of the text below.\n"
        "Reply with ONLY the ISO 639-1 code (e.g. en, ja, zh, ko, fr, de).\n\n"
        f"Text:\n{sample}"
    )
    code = gemini_generate(prompt, config, temperature=0.0).lower().strip()
    code = re.sub(r"[^a-z-]", "", code.split()[0] if code else "auto")
    return code or "auto"


def translate_chunk_gemini(text: str, source_lang: str, config: dict) -> str:
    prompt = (
        "You are a professional translator.\n"
        "Translate the following text into natural, fluent Korean.\n"
        "Preserve original formatting, line breaks, lists, and technical terms accurately.\n"
        "If the text is already Korean, return it unchanged.\n"
        "Reply with ONLY the Korean translation. No explanations or notes.\n\n"
        f"Source language hint: {source_lang}\n\n"
        f"Text:\n{text}"
    )
    return gemini_generate(prompt, config)


def translate_gemini(text: str, config: dict) -> dict:
    if korean_ratio(text) >= 0.4:
        return _result(text, "ko", True, 0, "gemini")

    source_lang = detect_language_gemini(text, config)
    if source_lang == "ko":
        return _result(text, "ko", True, 0, "gemini")

    chunks = split_into_chunks(text)
    translated = [translate_chunk_gemini(chunk, source_lang, config) for chunk in chunks]
    return _result("".join(translated), source_lang, False, len(chunks), "gemini")


def translate_fallback(text: str) -> dict:
    if korean_ratio(text) >= 0.4:
        return _result(text, "ko", True, 0, "fallback")

    source_lang = fallback_detect_language(text)
    if source_lang == "ko":
        return _result(text, "ko", True, 0, "fallback")

    chunks = split_into_chunks(text, FALLBACK_CHUNK_SIZE)
    translated = [
        fallback_translate_chunk(chunk, source_lang if source_lang != "auto" else "auto")
        for chunk in chunks
    ]
    return _result("".join(translated), source_lang, False, len(chunks), "fallback")


def translate(text: str, config: dict) -> dict:
    text = text.strip()
    if not text:
        raise ValueError("번역할 텍스트가 비어 있습니다.")

    if config["gemini_ready"]:
        try:
            return translate_gemini(text, config)
        except Exception:
            return translate_fallback(text)
    return translate_fallback(text)


def normalize_summary_to_five_lines(summary: str) -> list[str]:
    lines = [re.sub(r"^[\d\.\-\*•]+\s*", "", line).strip() for line in summary.splitlines()]
    lines = [line for line in lines if line]

    if len(lines) < 2:
        sentences = re.split(r"(?<=[.!?。！？])\s+", summary.strip())
        lines = [s.strip() for s in sentences if s.strip()]

    if len(lines) > 5:
        lines = lines[:5]
    return lines


def summarize(text: str, config: dict) -> list[str]:
    if not config["gemini_ready"]:
        raise RuntimeError("5줄 요약·TTS는 Gemini API 키가 필요합니다.")

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
    raw = gemini_generate(prompt, config, temperature=0.3)
    return normalize_summary_to_five_lines(raw)


def _result(translation: str, source_lang: str, already_korean: bool, chunks: int, provider: str) -> dict:
    return {
        "translation": translation,
        "source_lang": source_lang,
        "source_lang_name": LANG_NAMES.get(source_lang, source_lang),
        "already_korean": already_korean,
        "chunks": chunks,
        "provider": provider,
    }
