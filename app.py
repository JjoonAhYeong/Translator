import io

import streamlit as st
from gtts import gTTS

from services import get_config, summarize, translate

st.set_page_config(
    page_title="문서 번역기",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="collapsed",
)

MINT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
  font-family: 'Noto Sans KR', sans-serif;
}

.stApp {
  background: #f4faf8;
}

.block-container {
  padding-top: 1.5rem;
  max-width: 960px;
}

.mint-header {
  background: rgba(255,255,255,0.9);
  border: 1px solid #d4ebe3;
  border-radius: 16px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1.25rem;
  box-shadow: 0 1px 3px rgba(26,46,40,0.06);
}

.mint-header h1 {
  margin: 0;
  font-size: 1.35rem;
  color: #1a2e28;
}

.mint-header p {
  margin: 0.25rem 0 0;
  color: #7a948c;
  font-size: 0.9rem;
}

.badge {
  display: inline-block;
  padding: 0.2rem 0.65rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 500;
  margin-top: 0.5rem;
}

.badge-ok {
  background: #d8f3ec;
  color: #2f7a67;
  border: 1px solid #b8e8db;
}

.badge-fallback {
  background: #eef8f4;
  color: #3d9a82;
  border: 1px solid #d4ebe3;
}

.summary-box {
  background: #fff;
  border: 1px solid #d4ebe3;
  border-radius: 16px;
  padding: 1rem 1.25rem;
  margin-top: 1rem;
}

.summary-line {
  display: flex;
  gap: 0.6rem;
  padding: 0.55rem 0;
  border-bottom: 1px solid #eef8f4;
  color: #4a635c;
  line-height: 1.7;
}

.summary-line:last-child { border-bottom: none; }

.summary-num {
  width: 1.4rem;
  height: 1.4rem;
  border-radius: 50%;
  background: #b8e8db;
  color: #2f7a67;
  font-size: 0.7rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 0.15rem;
}

div[data-testid="stTextArea"] textarea {
  background: #fff;
  border: 1px solid #d4ebe3;
  border-radius: 12px;
}

.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #6bc9b0, #4db89c);
  color: white;
  border: none;
  border-radius: 12px;
  font-weight: 500;
}

.stButton > button[kind="secondary"] {
  background: #f0faf7;
  color: #2f7a67;
  border: 1px solid #d4ebe3;
  border-radius: 12px;
}
</style>
"""

st.markdown(MINT_CSS, unsafe_allow_html=True)


def load_secrets() -> dict:
    try:
        return dict(st.secrets)
    except Exception:
        return {}


def render_header(config: dict) -> None:
    badge = (
        '<span class="badge badge-ok">Gemini 준비됨 · ' + config["model"] + "</span>"
        if config["gemini_ready"]
        else '<span class="badge badge-fallback">기본 번역 모드 (Gemini 키 없음)</span>'
    )
    st.markdown(
        f"""
        <div class="mint-header">
          <h1>🌿 문서 번역기</h1>
          <p>외국어 문서를 한국어로 번역하고, 5줄 요약을 음성(TTS)으로 들을 수 있습니다.</p>
          {badge}
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_tts_audio(text: str) -> bytes:
    buffer = io.BytesIO()
    gTTS(text=text, lang="ko").write_to_fp(buffer)
    buffer.seek(0)
    return buffer.read()


def render_summary(lines: list[str]) -> None:
    rows = "".join(
        f'<div class="summary-line"><span class="summary-num">{i}</span><span>{line}</span></div>'
        for i, line in enumerate(lines, 1)
    )
    st.markdown(f'<div class="summary-box"><strong>5줄 요약</strong>{rows}</div>', unsafe_allow_html=True)


def main() -> None:
    config = get_config(load_secrets())
    render_header(config)

    if "translation" not in st.session_state:
        st.session_state.translation = ""
    if "summary_lines" not in st.session_state:
        st.session_state.summary_lines = []
    if "source_lang_name" not in st.session_state:
        st.session_state.source_lang_name = "자동 감지"
    if "provider" not in st.session_state:
        st.session_state.provider = ""

    uploaded = st.file_uploader(
        "파일 업로드 (.txt, .md, .csv, .json, .html)",
        type=["txt", "md", "csv", "json", "html", "xml", "log", "rst"],
    )

    if uploaded is not None:
        content = uploaded.read().decode("utf-8", errors="replace")
        st.session_state.source_text = content
        st.success(f'"{uploaded.name}" 파일을 불러왔습니다.')

    source_text = st.text_area(
        "원문",
        height=220,
        placeholder="번역할 텍스트를 입력하거나 붙여넣으세요...",
        key="source_text",
        label_visibility="collapsed",
    )

    col_info, _ = st.columns([2, 1])
    with col_info:
        if source_text:
            words = len(source_text.split())
            st.caption(f"{len(source_text):,}자 · 약 {words:,}단어 · {st.session_state.source_lang_name}")

    btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
    with btn_col1:
        do_translate = st.button("▶ 번역 시작", type="primary", use_container_width=True)
    with btn_col2:
        do_summary_tts = st.button("▶ 번역+5줄요약(TTS)", type="secondary", use_container_width=True)
    with btn_col3:
        if st.button("전체 초기화", use_container_width=True):
            st.session_state.translation = ""
            st.session_state.summary_lines = []
            st.session_state.source_lang_name = "자동 감지"
            st.session_state.provider = ""
            st.session_state.source_text = ""
            st.rerun()

    col_src, col_dst = st.columns(2)
    with col_src:
        st.markdown("**원문**")
    with col_dst:
        st.markdown("**번역 결과**")

    with col_dst:
        st.text_area(
            "번역 결과",
            value=st.session_state.translation,
            height=220,
            disabled=True,
            label_visibility="collapsed",
        )
        if st.session_state.translation:
            st.download_button(
                "결과 다운로드",
                data=st.session_state.translation,
                file_name="translated_ko.txt",
                mime="text/plain",
                use_container_width=True,
            )

    if do_translate or do_summary_tts:
        if not source_text or not source_text.strip():
            st.warning("번역할 텍스트를 입력하거나 파일을 업로드해 주세요.")
        else:
            with st.spinner("번역 중..."):
                try:
                    result = translate(source_text.strip(), config)
                    st.session_state.translation = result["translation"]
                    st.session_state.source_lang_name = result["source_lang_name"]
                    st.session_state.provider = result["provider"]
                    st.session_state.summary_lines = []

                    provider_label = "기본 번역" if result["provider"] == "fallback" else "Gemini 번역"
                    if result["already_korean"]:
                        st.info("원문이 이미 한국어입니다.")
                    elif do_translate:
                        if result["provider"] == "fallback":
                            st.info(f"{provider_label}으로 완료했습니다. (요약·TTS는 Gemini API 필요)")
                        else:
                            st.success(f"{provider_label}이 완료되었습니다.")
                except Exception as exc:
                    st.error(str(exc))

    if do_summary_tts and st.session_state.translation:
        if not config["gemini_ready"]:
            st.warning("번역은 완료되었습니다. 5줄 요약·TTS는 Gemini API 키가 필요합니다.")
        else:
            with st.spinner("5줄 요약 생성 중..."):
                try:
                    lines = summarize(st.session_state.translation, config)
                    st.session_state.summary_lines = lines
                except Exception as exc:
                    st.warning(f"번역은 완료되었습니다. 요약·TTS 실패: {exc}")

    if st.session_state.summary_lines:
        render_summary(st.session_state.summary_lines)
        summary_text = "\n".join(st.session_state.summary_lines)
        try:
            audio_bytes = build_tts_audio(summary_text)
            st.audio(audio_bytes, format="audio/mp3")
            st.caption("5줄 요약 TTS — 위 플레이어로 재생하세요.")
        except Exception as exc:
            st.warning(f"TTS 생성 실패: {exc}")

    st.caption("입력 텍스트는 번역·요약에만 사용되며 저장되지 않습니다.")


if __name__ == "__main__":
    main()
