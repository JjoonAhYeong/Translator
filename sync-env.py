"""프로젝트 루트 .env → config.local.js 동기화 (브라우저에서 바로 사용)"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "config.local.js"

load_dotenv(ROOT / ".env", encoding="utf-8-sig")

api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
model = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()

if not api_key:
    raise SystemExit(".env에 GEMINI_API_KEY가 없습니다.")

config = {"apiKey": api_key, "model": model}
OUT.write_text(
    "window.GEMINI_CONFIG = " + json.dumps(config, ensure_ascii=False) + ";\n",
    encoding="utf-8",
)
print(f"생성 완료: {OUT.name}")
