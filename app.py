import os
import re
import json
import tempfile
import subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import streamlit as st
import requests

st.set_page_config(page_title="ClipForge AI", page_icon="🎬", layout="wide")

st.markdown("""
<style>
:root { color-scheme: dark; }
.stApp { background: radial-gradient(circle at 15% 0%, #202342 0, #10111b 38%, #0b0c12 100%); }
.block-container { max-width: 1120px; padding-top: 2rem; }
.hero { padding: 26px; border: 1px solid #34364d; border-radius: 22px;
        background: linear-gradient(135deg,#222642,#171927 65%,#241b36); margin-bottom: 18px; }
.hero h1 { margin: 0; font-size: 2.3rem; letter-spacing: -1px; }
.hero p { color: #b8bdd3; margin: 8px 0 0 0; }
.panel { padding: 18px; border: 1px solid #303247; border-radius: 18px; background: #151722; }
.smallmuted { color: #a4a9bf; font-size: .9rem; }
div.stButton > button { border-radius: 12px; min-height: 44px; font-weight: 650; }
</style>
<div class="hero">
  <h1>🎬 ClipForge <span style="color:#a99cff">AI</span></h1>
  <p>Find the strongest moments. Create social-ready clips. Keep control of every edit.</p>
</div>
""", unsafe_allow_html=True)

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-2500:] or "Video processing failed.")
    return p.stdout

def ffmpeg_available():
    try:
        run(["ffmpeg", "-version"])
        return True
    except Exception:
        return False

def get_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(out.strip())

def fetch_direct_video(url, target):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Please enter a valid http/https video URL.")
    # Only accept direct media responses, not platform pages or HTML.
    with requests.get(url, stream=True, timeout=30, headers={"User-Agent": "ClipForge/1.0"}) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "").lower()
        if not (ctype.startswith("video/") or url.lower().split("?")[0].endswith((".mp4", ".mov", ".webm", ".m4v"))):
            raise ValueError("That link did not return a direct video file. Paste a direct .mp4/.mov/.webm link or upload the video.")
        total = 0
        limit = 700 * 1024 * 1024
        with open(target, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    total += len(chunk)
                    if total > limit:
                        raise ValueError("Video is larger than the 700 MB limit.")
                    f.write(chunk)

def get_youtube_id(url):
    """Return a YouTube video ID for common public watch/short/embed URLs."""
    try:
        parsed = urlparse(url.strip())
        host = (parsed.netloc or "").lower().split(":")[0]
        video_id = None
        if host in ("youtu.be", "www.youtu.be"):
            video_id = parsed.path.strip("/").split("/")[0]
        elif host.endswith("youtube.com"):
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [None])[0]
            elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
                parts = parsed.path.strip("/").split("/")
                if len(parts) > 1:
                    video_id = parts[1]
        if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return video_id
    except Exception:
        pass
    return None

def transcribe(path, model_name, language):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    kwargs = {}
    if language != "Auto-detect":
        kwargs["language"] = language
    segments, info = model.transcribe(str(path), vad_filter=True, **kwargs)
    result = []
    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            result.append({"start": float(seg.start), "end": float(seg.end), "text": text})
    return result, info.language

def score_text(text):
    t = text.lower()
    cues = [
        "wow", "what", "wait", "no way", "amazing", "incredible", "crazy",
        "important", "secret", "finally", "actually", "because", "but then",
        "you won't believe", "the best", "worst", "never", "always",
        "πραγματικά", "απίστευτο", "περίμενε", "όχι", "τέλειο", "γιατί",
        "αλλά", "τελικά", "σημαντικό", "προσέξτε"
    ]
    score = min(len(t) / 180, 1.5) + sum(1.0 for cue in cues if cue in t)
    score += min(text.count("!") * .35, 1.2) + min(text.count("?") * .15, .6)
    return score

def choose_clips(segments, duration, clip_len, count):
    if not segments:
        raise ValueError("No speech was detected. Try another video or use manual timestamps.")
    candidates = []
    step = max(4.0, clip_len * .35)
    starts = []
    x = 0.0
    while x < max(1.0, duration - clip_len + 1):
        starts.append(x)
        x += step
    if not starts:
        starts = [0.0]
    for start in starts:
        end = min(duration, start + clip_len)
        relevant = [s for s in segments if s["end"] > start and s["start"] < end]
        if not relevant:
            continue
        text = " ".join(s["text"] for s in relevant)
        coverage = sum(max(0, min(s["end"], end) - max(s["start"], start)) for s in relevant)
        score = score_text(text) + min(coverage / clip_len, 1.0)
        candidates.append((score, start, end, text))
    candidates.sort(reverse=True, key=lambda x: x[0])
    selected = []
    for c in candidates:
        if all(abs(c[1] - s[1]) > clip_len * .65 for s in selected):
            selected.append(c)
        if len(selected) >= count:
            break
    return sorted(selected, key=lambda x: x[1])

def make_srt(segments, start, end, output):
    def stamp(sec):
        ms = int(round(sec * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    rows = []
    idx = 1
    for seg in segments:
        a, b = max(seg["start"], start), min(seg["end"], end)
        if b <= a:
            continue
        rows.append(f"{idx}\n{stamp(a-start)} --> {stamp(b-start)}\n{seg['text']}\n")
        idx += 1
    Path(output).write_text("\n".join(rows), encoding="utf-8")

def export_clip(source, start, end, output, aspect, captions, segments):
    duration = end - start
    vf = []
    if aspect == "9:16":
        vf.append("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
    elif aspect == "1:1":
        vf.append("scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080")
    else:
        vf.append("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
    srt_path = str(Path(output).with_suffix(".srt"))
    if captions:
        make_srt(segments, start, end, srt_path)
        escaped = srt_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        vf.append(f"subtitles='{escaped}'")
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{duration:.3f}",
           "-vf", ",".join(vf), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output)]
    run(cmd)

if "source_path" not in st.session_state:
    st.session_state.source_path = None
if "clips" not in st.session_state:
    st.session_state.clips = []
if "transcript" not in st.session_state:
    st.session_state.transcript = []

left, right = st.columns([1.15, .85], gap="large")
with left:
    st.markdown("### 1 · Add your video")
    youtube_url = st.text_input(
        "Paste a YouTube link (preview)",
        placeholder="https://www.youtube.com/watch?v=...",
        help="YouTube links can be previewed here. YouTube does not provide this app with a downloadable video file."
    )
    yt_id = get_youtube_id(youtube_url) if youtube_url.strip() else None
    if youtube_url.strip():
        if yt_id:
            st.caption("YouTube link recognized. Preview below.")
            st.components.v1.iframe(f"https://www.youtube-nocookie.com/embed/{yt_id}", height=315, scrolling=False)
            st.info("To create clips, upload the original video file that you own or have permission to edit. The YouTube link alone cannot be used as the editing source.")
        else:
            st.warning("That doesn't look like a supported YouTube video link. Try a standard watch, youtu.be, Shorts, or live URL.")

    upload = st.file_uploader(
        "Upload the video file to be clipped",
        type=["mp4", "mov", "m4v", "webm", "mkv"],
        help="Upload the original video file you own or are authorized to edit. This is the file the AI will process."
    )
    url = st.text_input("Or paste a direct video-file link", placeholder="https://example.com/video.mp4")
    st.caption("A YouTube watch link is for preview only. Direct .mp4/.mov/.webm links may be processed if publicly accessible and permitted.")
    if st.button("Load video for AI clipping", use_container_width=True):
        try:
            if not ffmpeg_available():
                st.error("FFmpeg is missing on this server. See the setup instructions.")
            elif upload is not None:
                suffix = Path(upload.name).suffix or ".mp4"
                temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                temp.write(upload.getbuffer())
                temp.close()
                st.session_state.source_path = temp.name
                st.session_state.clips = []
                st.session_state.transcript = []
                st.success(f"Loaded {upload.name} for AI clipping.")
            elif url.strip():
                temp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                temp.close()
                fetch_direct_video(url.strip(), temp.name)
                st.session_state.source_path = temp.name
                st.session_state.clips = []
                st.session_state.transcript = []
                st.success("Direct video file loaded.")
            elif youtube_url.strip() and yt_id:
                st.warning("YouTube preview is ready, but the video file is still needed for AI clipping. Upload the original video file above.")
            else:
                st.warning("Upload a video file or paste a direct video-file link first.")
        except Exception as e:
            st.error(str(e))

    if st.session_state.source_path and Path(st.session_state.source_path).exists():
        try:
            dur = get_duration(st.session_state.source_path)
            st.video(st.session_state.source_path)
            st.caption(f"Video ready for AI processing · duration: {dur/60:.1f} minutes")
        except Exception as e:
            st.error(f"Could not read this video: {e}")

with right:
    st.markdown("### 2 · AI clipping settings")
    clip_len = st.slider("Target clip length", 15, 90, 35, 5)
    clip_count = st.slider("Number of clips", 1, 10, 5)
    aspect = st.selectbox("Export format", ["9:16", "1:1", "16:9"])
    model_name = st.selectbox("Speech recognition model", ["tiny", "base", "small"], index=1,
                              help="Small is more accurate but slower. Models download on first use.")
    language = st.selectbox("Spoken language", ["Auto-detect", "en", "el", "es", "fr", "de", "it", "pt"])
    captions = st.checkbox("Burn subtitles into the video", value=True)
    st.markdown('<div class="smallmuted">The highlight finder scores transcript sections for useful, expressive and information-rich moments. Review the suggested clips before exporting.</div>', unsafe_allow_html=True)
    go = st.button("✨ Find my best moments", type="primary", use_container_width=True, disabled=not bool(st.session_state.source_path))

if go:
    try:
        with st.spinner("Listening to the video and finding highlight moments… This can take a while on a free server."):
            duration = get_duration(st.session_state.source_path)
            transcript, detected = transcribe(st.session_state.source_path, model_name, language)
            st.session_state.transcript = transcript
            st.session_state.detected_language = detected
            st.session_state.clips = choose_clips(transcript, duration, clip_len, clip_count)
        st.success(f"Found {len(st.session_state.clips)} suggested clips · detected language: {detected}")
    except Exception as e:
        st.error(f"AI clipping failed: {e}")

if st.session_state.clips:
    st.markdown("---")
    st.markdown("### 3 · Review and export your clips")
    for i, clip in enumerate(st.session_state.clips, 1):
        score, start, end, text = clip
        with st.expander(f"Clip {i} · {int(start//60):02}:{int(start%60):02} – {int(end//60):02}:{int(end%60):02}", expanded=(i == 1)):
            st.write(text[:650] + ("…" if len(text) > 650 else ""))
            col1, col2 = st.columns(2)
            with col1:
                new_start = st.number_input(f"Start seconds · clip {i}", min_value=0.0,
                                            max_value=float(get_duration(st.session_state.source_path)),
                                            value=float(start), step=0.5, key=f"s{i}")
            with col2:
                new_end = st.number_input(f"End seconds · clip {i}", min_value=0.5,
                                          max_value=float(get_duration(st.session_state.source_path)),
                                          value=float(end), step=0.5, key=f"e{i}")
            if st.button(f"Export clip {i}", key=f"export{i}", use_container_width=True):
                try:
                    if new_end <= new_start:
                        st.error("End time must be after start time.")
                    else:
                        out = tempfile.NamedTemporaryFile(delete=False, suffix=f"_clip{i}.mp4").name
                        with st.spinner("Rendering your clip…"):
                            export_clip(st.session_state.source_path, new_start, new_end, out,
                                        aspect, captions, st.session_state.transcript)
                        data = Path(out).read_bytes()
                        st.video(data)
                        st.download_button("⬇ Download MP4", data=data,
                                           file_name=f"clipforge_clip_{i}.mp4",
                                           mime="video/mp4", key=f"dl{i}")
                except Exception as e:
                    st.error(f"Export failed: {e}")

st.markdown("---")
with st.expander("About links, privacy and limitations"):
    st.write("""
    - YouTube links are recognized and previewed using YouTube's official embedded player.
    - A YouTube watch link alone cannot be used as a video-editing source here. Upload the original video file you own or are authorized to edit, or provide an accessible direct video-file URL.
    - This app does not download videos from YouTube, TikTok, Instagram or other watch pages, and does not bypass logins, DRM or platform restrictions.
    - Speech recognition runs with the open-source Whisper model on the server. First use downloads the selected model.
    - Highlight ranking is an automated transcript-based first pass, not a guarantee that every suggested moment is viral or interesting. Review clips before posting.
    - Uploaded videos are processed temporarily by the server. Do not upload private or sensitive footage to a server you do not control.
    """)
