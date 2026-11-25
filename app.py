
import streamlit as st
import cv2
import numpy as np
import subprocess
import shutil
import tempfile
import os
import re
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# EXOTIC DRIVE AI STUDIO
# VERSION 1.0
# ==========================================

st.set_page_config(
    page_title="EXOTIC DRIVE AI STUDIO",
    page_icon="🏁",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background-color: #101116;
}
h1, h2, h3 {
    color: white;
}
.stButton button {
    border-radius: 8px;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

st.title("🏁 EXOTIC DRIVE AI STUDIO")
st.caption("AI AUTO CUT • VIDEO EDITOR • TIMELINE • EXPORT HD")

# ==========================================
# SESSION STORAGE
# ==========================================

if "workdir" not in st.session_state:
    st.session_state.workdir = tempfile.mkdtemp(
        prefix="exotic_drive_"
    )

if "results" not in st.session_state:
    st.session_state.results = []

WORK = Path(st.session_state.workdir)
WORK.mkdir(exist_ok=True)

# ==========================================
# SIDEBAR
# ==========================================

with st.sidebar:
    st.header("⚙️ PENGATURAN")

    clip_len = st.slider(
        "Durasi setiap clip",
        10, 60, 25, 5
    )

    number_clips = st.slider(
        "Jumlah highlight",
        1, 8, 3
    )

    aspect = st.selectbox(
        "Format video",
        [
            "9:16 Reels / Shorts / TikTok",
            "16:9 Landscape"
        ]
    )

    resolution = st.selectbox(
        "Resolusi export",
        ["1080p Full HD", "720p HD"]
    )

    watermark = st.checkbox(
        "Watermark EXOTIC DRIVE",
        value=True
    )

    st.divider()

    st.caption("EXOTIC DRIVE AI")
    st.caption("Free Edition • No paid API")

# ==========================================
# FFMPEG
# ==========================================

def ffmpeg_path():
    return shutil.which("ffmpeg")

def ffprobe_path():
    return shutil.which("ffprobe")

def probe_duration(path):
    try:
        cmd = [
            ffprobe_path(),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ]

        return float(
            subprocess.check_output(
                cmd,
                stderr=subprocess.STDOUT
            ).decode().strip()
        )
    except Exception:
        return 0.0

# ==========================================
# WATERMARK
# ==========================================

def make_watermark(path):
    img = Image.new(
        "RGBA",
        (520, 100),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(
            "DejaVuSans-Bold.ttf", 42
        )
    except Exception:
        font = ImageFont.load_default()

    draw.text(
        (15, 20),
        "EXOTIC DRIVE",
        font=font,
        fill=(255, 255, 255, 220),
        stroke_width=2,
        stroke_fill=(0, 0, 0, 180)
    )

    img.save(path)

# ==========================================
# VIDEO ANALYSIS
# ==========================================

def normalize(arr):
    p95 = np.percentile(arr, 95)

    if p95 <= 0.000001:
        return np.zeros_like(arr)

    return np.clip(arr / p95, 0, 1)

def analyze_video(path):
    cap = cv2.VideoCapture(str(path))

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT)

    duration = total / fps if fps else 0

    if duration <= 0:
        cap.release()
        return [], 0

    samples = []
    previous = None

    step = max(1, int(fps / 2))
    idx = 0

    while True:
        ok, frame = cap.read()

        if not ok:
            break

        if idx % step == 0:
            small = cv2.resize(
                frame, (160, 90)
            )

            gray = cv2.cvtColor(
                small, cv2.COLOR_BGR2GRAY
            )

            motion = (
                0 if previous is None
                else float(
                    np.mean(
                        cv2.absdiff(gray, previous)
                    )
                )
            )

            hsv = cv2.cvtColor(
                small, cv2.COLOR_BGR2HSV
            )

            hist = cv2.calcHist(
                [hsv],
                [0, 1],
                None,
                [16, 16],
                [0, 180, 0, 256]
            )

            cv2.normalize(hist, hist)

            scene = (
                0 if not samples
                else float(
                    cv2.compareHist(
                        hist,
                        samples[-1]["hist"],
                        cv2.HISTCMP_BHATTACHARYYA
                    )
                )
            )

            samples.append({
                "t": idx / fps,
                "motion": motion,
                "scene": scene,
                "hist": hist
            })

            previous = gray

        idx += 1

    cap.release()

    if not samples:
        return [], duration

    times = np.array(
        [x["t"] for x in samples]
    )

    motion = normalize(
        np.array([x["motion"] for x in samples])
    )

    scene = normalize(
        np.array([x["scene"] for x in samples])
    )

    score = (
        0.78 * motion +
        0.22 * scene
    )

    results = []

    half = 2.5

    for i, t in enumerate(times):
        mask = (
            (times >= t - half) &
            (times <= t + half)
        )

        value = (
            float(np.mean(score[mask]))
            if np.any(mask)
            else float(score[i])
        )

        results.append((float(t), value))

    return results, duration

# ==========================================
# AUTO CUT ENGINE
# ==========================================

def cut_clip(src, dst, start, length, vertical, wm):
    if vertical:
        vf = (
            "scale=1080:1920:"
            "force_original_aspect_ratio=increase,"
            "crop=1080:1920"
        )
    else:
        vf = (
            "scale=1920:1080:"
            "force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
        )

    args = [
        ffmpeg_path(), "-y",
        "-ss", str(start),
        "-i", str(src),
        "-t", str(length)
    ]

    wm_path = None

    if wm:
        wm_path = str(
            Path(dst).with_suffix(".png")
        )

        make_watermark(wm_path)

        args += ["-i", wm_path]

        args += [
            "-filter_complex",
            f"[0:v]{vf}[base];"
            "[1:v]format=rgba[logo];"
            "[base][logo]overlay="
            "W-w-30:H-h-30[vout]",
            "-map", "[vout]",
            "-map", "0:a?"
        ]

    else:
        args += [
            "-vf", vf,
            "-map", "0:v:0",
            "-map", "0:a?"
        ]

    args += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "160k",
        "-movflags", "+faststart",
        str(dst)
    ]

    subprocess.run(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True
    )

    if wm_path and os.path.exists(wm_path):
        os.remove(wm_path)

# ==========================================
# MERGE VIDEO
# ==========================================

def merge_clips(clips, output):
    list_file = Path(output).with_name(
        "concat_list.txt"
    )

    with open(
        list_file, "w", encoding="utf-8"
    ) as f:

        for clip in clips:
            path = Path(clip).resolve().as_posix()
            path = path.replace("'", "'\\''")

            f.write(f"file '{path}'\n")

    try:
        subprocess.run(
            [
                ffmpeg_path(), "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output)
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True
        )
    finally:
        if list_file.exists():
            list_file.unlink()

# ==========================================
# TEXT OVERLAY
# ==========================================

def make_text_image(text, path, vertical):
    w, h = (
        (1080, 1920)
        if vertical
        else (1920, 1080)
    )

    img = Image.new(
        "RGBA", (w, h), (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(
            "DejaVuSans-Bold.ttf", 54
        )
    except Exception:
        font = ImageFont.load_default()

    draw.text(
        (w // 2, int(h * 0.14)),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        anchor="mm",
        stroke_width=3,
        stroke_fill=(0, 0, 0, 220)
    )

    img.save(path)

# ==========================================
# FINAL RENDER
# ==========================================

def final_render(
    base,
    output,
    music=None,
    music_volume=0.5,
    text_overlay="",
    vertical=True
):
    args = [
        ffmpeg_path(), "-y",
        "-i", str(base)
    ]

    music_index = None
    text_index = None
    temp_text = None

    if music:
        music_index = 1

        args += [
            "-stream_loop", "-1",
            "-i", str(music)
        ]

    if text_overlay.strip():
        temp_text = WORK / "text_overlay.png"

        make_text_image(
            text_overlay,
            temp_text,
            vertical
        )

        text_index = len(
            [x for x in [music_index] if x is not None]
        ) + 1

        args += ["-i", str(temp_text)]

    if text_index is not None:
        args += [
            "-filter_complex",
            f"[0:v][{text_index}:v]"
            "overlay=0:0[vout]",
            "-map", "[vout]"
        ]
    else:
        args += ["-map", "0:v:0"]

    if music_index is not None:
        args += [
            "-map", f"{music_index}:a:0",
            "-af", f"volume={music_volume}",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest"
        ]
    else:
        args += [
            "-map", "0:a?",
            "-c:a", "copy"
        ]

    if text_index is not None:
        args += [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p"
        ]
    else:
        args += ["-c:v", "copy"]

    args += [
        "-movflags", "+faststart",
        str(output)
    ]

    subprocess.run(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True
    )

    if temp_text and temp_text.exists():
        temp_text.unlink()

# ==========================================
# CHECK FFMPEG
# ==========================================

if not ffmpeg_path() or not ffprobe_path():
    st.error(
        "FFmpeg atau FFprobe belum tersedia. "
        "Periksa instalasi FFmpeg."
    )
    st.stop()

# ==========================================
# UPLOAD VIDEO
# ==========================================

st.header("📁 1. UPLOAD VIDEO")

uploads = st.file_uploader(
    "Pilih video untuk diedit",
    type=["mp4", "mov", "mkv", "avi", "webm"],
    accept_multiple_files=True
)

col1, col2 = st.columns(2)

with col1:
    analyze_button = st.button(
        "🔎 ANALISIS & CARI HIGHLIGHT",
        type="primary",
        use_container_width=True
    )

with col2:
    if st.button(
        "🗑️ RESET PROJECT",
        use_container_width=True
    ):
        st.session_state.results = []

        for key in list(st.session_state.keys()):
            if key.startswith(("made_", "final_")):
                del st.session_state[key]

        st.rerun()

if analyze_button:
    if not uploads:
        st.warning("Silakan upload video terlebih dahulu.")

    else:
        st.session_state.results = []

        progress = st.progress(0)

        for n, up in enumerate(uploads):
            safe_name = re.sub(
                r"[^a-zA-Z0-9_-]",
                "_",
                Path(up.name).stem
            )

            src = WORK / (
                f"source_{n}_{safe_name}"
                f"{Path(up.name).suffix.lower()}"
            )

            src.write_bytes(up.getbuffer())

            with st.spinner(
                f"Menganalisis {up.name}..."
            ):
                scores, duration = analyze_video(src)

            if not scores:
                st.warning(
                    f"Tidak dapat membaca {up.name}"
                )
                continue

            length = min(
                float(clip_len),
                float(duration)
            )

            candidates = sorted(
                scores,
                key=lambda x: x[1],
                reverse=True
            )

            chosen = []

            for t, score in candidates:
                start = max(
                    0,
                    min(
                        t - length / 2,
                        duration - length
                    )
                )

                end = start + length

                if all(
                    end <= a or start >= b
                    for a, b, _ in chosen
                ):
                    chosen.append(
                        (start, end, score)
                    )

                if len(chosen) >= number_clips:
                    break

            chosen.sort()

            st.session_state.results.append({
                "name": up.name,
                "src": str(src),
                "clips": chosen,
                "duration": duration
            })

            progress.progress(
                (n + 1) / len(uploads)
            )

        st.success("Analisis selesai!")

# ==========================================
# RESULTS
# ==========================================

if st.session_state.results:

    st.divider()
    st.header("🎯 2. HASIL AI HIGHLIGHT")

    for vi, item in enumerate(
        st.session_state.results
    ):

        with st.expander(
            f"🏁 {item['name']}",
            expanded=True
        ):

            st.write(
                f"Durasi sumber: "
                f"{item['duration']:.1f} detik"
            )

            for ci, (start, end, score) in enumerate(
                item["clips"], 1
            ):
                st.write(
                    f"**Highlight {ci}** — "
                    f"{start:.1f}s sampai {end:.1f}s "
                    f"— Skor visual {score*100:.0f}/100"
                )

            clip_key = f"made_{vi}"

            if st.button(
                "✂️ BUAT SEMUA CLIP",
                key=f"create_{vi}",
                type="primary",
                use_container_width=True
            ):

                folder = WORK / f"clips_{vi}"
                folder.mkdir(exist_ok=True)

                made = []

                vertical = aspect.startswith("9:16")

                bar = st.progress(0)

                for ci, (start, end, score) in enumerate(
                    item["clips"], 1
                ):

                    dst = folder / (
                        f"ExoticDrive_Hook_{ci}.mp4"
                    )

                    try:
                        cut_clip(
                            item["src"],
                            dst,
                            start,
                            end - start,
                            vertical,
                            watermark
                        )

                        made.append(str(dst))

                    except Exception as e:
                        st.error(
                            f"Gagal membuat clip {ci}: {e}"
                        )

                    bar.progress(
                        ci / len(item["clips"])
                    )

                st.session_state[clip_key] = made

                st.success(
                    f"{len(made)} clip berhasil dibuat."
                )

            made = st.session_state.get(
                clip_key, []
            )

            if made:

                st.divider()
                st.header("🎬 3. VIDEO TIMELINE EDITOR")

                edited = []

                for ci, clip_path in enumerate(made):
                    duration = probe_duration(clip_path)

                    if duration <= 0:
                        continue

                    st.markdown(
                        f"### 🎞️ VIDEO TRACK {ci+1}"
                    )

                    st.video(clip_path)

                    start_trim, end_trim = st.slider(
                        f"Potong durasi klip {ci+1}",
                        min_value=0.0,
                        max_value=float(duration),
                        value=(0.0, float(duration)),
                        step=0.1,
                        key=f"trim_{vi}_{ci}"
                    )

                    order = st.number_input(
                        f"Urutan klip {ci+1}",
                        min_value=1,
                        max_value=len(made),
                        value=ci+1,
                        step=1,
                        key=f"order_{vi}_{ci}"
                    )

                    edited.append({
                        "path": clip_path,
                        "start": start_trim,
                        "end": end_trim,
                        "order": int(order)
                    })

                    st.caption(
                        f"Durasi edit: "
                        f"{end_trim-start_trim:.1f} detik"
                    )

                st.divider()

                st.header("🎵 4. MUSIK DAN TEKS")

                music_upload = st.file_uploader(
                    "Upload musik MP3 / WAV (opsional)",
                    type=["mp3", "wav", "m4a", "aac"],
                    key=f"music_{vi}"
                )

                music_path = None

                if music_upload:
                    music_path = WORK / (
                        f"music_{vi}_"
                        + re.sub(
                            r"[^a-zA-Z0-9_.-]",
                            "_",
                            music_upload.name
                        )
                    )

                    music_path.write_bytes(
                        music_upload.getbuffer()
                    )

                music_volume = st.slider(
                    "Volume musik",
                    0.0, 1.0, 0.5, 0.1,
                    key=f"volume_{vi}"
                )

                text_overlay = st.text_input(
                    "Tulisan pada video (opsional)",
                    placeholder="FULL THROTTLE! 🏁",
                    key=f"text_{vi}"
                )

                st.caption(
                    "Jika musik dipilih, musik akan "
                    "menggantikan audio asli video."
                )

                st.divider()

                if st.button(
                    "🚀 RENDER FINAL VIDEO",
                    type="primary",
                    use_container_width=True,
                    key=f"render_{vi}"
                ):

                    valid = (
                        len(edited) == len(made)
                        and len(set(
                            x["order"] for x in edited
                        )) == len(edited)
                        and all(
                            x["end"] > x["start"]
                            for x in edited
                        )
                    )

                    if not valid:
                        st.error(
                            "Periksa durasi dan urutan klip."
                        )

                    else:
                        folder = WORK / f"render_{vi}"
                        folder.mkdir(exist_ok=True)

                        rendered = []

                        try:
                            ordered = sorted(
                                edited,
                                key=lambda x: x["order"]
                            )

                            bar = st.progress(0)

                            for n, clip in enumerate(
                                ordered, 1
                            ):

                                dst = folder / (
                                    f"Timeline_{n}.mp4"
                                )

                                subprocess.run(
                                    [
                                        ffmpeg_path(), "-y",
                                        "-i", clip["path"],
                                        "-ss", str(clip["start"]),
                                        "-t", str(
                                            clip["end"] -
                                            clip["start"]
                                        ),
                                        "-map", "0:v:0",
                                        "-map", "0:a?",
                                        "-c:v", "libx264",
                                        "-preset", "veryfast",
                                        "-crf", "23",
                                        "-pix_fmt", "yuv420p",
                                        "-c:a", "aac",
                                        "-b:a", "160k",
                                        str(dst)
                                    ],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE,
                                    check=True
                                )

                                rendered.append(dst)

                                bar.progress(
                                    n / len(ordered)
                                )

                            base = folder / "base.mp4"

                            merge_clips(
                                rendered,
                                base
                            )

                            final = folder / (
                                "EXOTIC_DRIVE_FINAL.mp4"
                            )

                            final_render(
                                base,
                                final,
                                music=music_path,
                                music_volume=music_volume,
                                text_overlay=text_overlay,
                                vertical=aspect.startswith("9:16")
                            )

                            st.session_state[
                                f"final_{vi}"
                            ] = str(final)

                            st.success(
                                "Video berhasil dirender!"
                            )

                        except Exception as e:
                            st.error(
                                f"Render gagal: {e}"
                            )

                final_path = st.session_state.get(
                    f"final_{vi}"
                )

                if final_path and Path(final_path).exists():

                    st.divider()
                    st.header("🏆 5. HASIL AKHIR")

                    st.video(final_path)

                    with open(final_path, "rb") as f:
                        video_bytes = f.read()

                    st.download_button(
                        "⬇️ DOWNLOAD FINAL VIDEO",
                        data=video_bytes,
                        file_name="EXOTIC_DRIVE_FINAL.mp4",
                        mime="video/mp4",
                        use_container_width=True,
                        key=f"download_{vi}"
                    )

                    st.success(
                        "Video siap diperiksa dan diupload!"
                    )

else:
    st.info(
        "Upload video, lalu tekan "
        "ANALISIS & CARI HIGHLIGHT."
    )

# ==========================================
# FOOTER
# ==========================================

st.divider()

st.markdown("""
<center>
🏁 <b>EXOTIC DRIVE AI STUDIO</b><br>
Free Video Editing • AI Auto Cut • Timeline Editor<br>
<small>Built for Trophy Truck & Offroad Content</small>
</center>
""", unsafe_allow_html=True)
