import streamlit as st
import cv2, numpy as np, subprocess, shutil, tempfile, os, json, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="Exotic Drive AI Auto Clipper", page_icon="🏁", layout="wide")
st.title("🏁 EXOTIC DRIVE — FREE AI AUTO CLIPPER")
st.caption("Local video analysis • Auto highlight • Vertical clips • No paid API required")

with st.sidebar:
    st.header("Pengaturan")
    clip_len = st.slider("Durasi setiap clip (detik)", 10, 60, 25, 5)
    number_clips = st.slider("Jumlah highlight per video", 1, 8, 3)
    aspect = st.selectbox("Format output", ["9:16 Reels / Shorts / TikTok", "16:9 Landscape"])
    watermark = st.checkbox("Watermark EXOTIC DRIVE", True)
    st.info("Gratis: analisis berjalan di laptop/PC. HP Android membuka dashboard melalui browser pada jaringan Wi-Fi yang sama.")

def ffmpeg_path():
    return shutil.which("ffmpeg")

def probe_duration(path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    try:
        return float(subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip())
    except Exception:
        return 0

def analyze_video(path):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total / fps if fps else 0
    if duration <= 0:
        cap.release()
        return [], 0
    samples = []
    prev = None
    # Sample at roughly 2 frames per second for a more useful motion estimate.
    step = max(1, int(fps / 2))
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok: break
        if idx % step == 0:
            small = cv2.resize(frame, (160, 90))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            motion = 0.0 if prev is None else float(np.mean(cv2.absdiff(gray, prev)))
            # Scene-change / visual-impact signal
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0,1], None, [16,16], [0,180,0,256])
            cv2.normalize(hist, hist)
            scene = 0.0 if not samples else float(cv2.compareHist(hist, samples[-1]["hist"], cv2.HISTCMP_BHATTACHARYYA))
            samples.append({"t": idx / fps, "motion": motion, "scene": scene, "hist": hist})
            prev = gray
        idx += 1
    cap.release()
    if not samples: return [], duration
    # Smooth into windows. Motion + scene changes are heuristic signals, not semantic AI.
    times = np.array([s["t"] for s in samples])
    m = np.array([s["motion"] for s in samples], dtype=float)
    sc = np.array([s["scene"] for s in samples], dtype=float)
    def norm(a):
        p95 = np.percentile(a, 95) if len(a) else 1
        return np.clip(a / (p95 if p95 > 1e-6 else 1), 0, 1)
    score = 0.78 * norm(m) + 0.22 * norm(sc)
    # Window score around each sample; prefer high-action clusters.
    results = []
    half = 2.5
    for i,t in enumerate(times):
        mask = (times >= t-half) & (times <= t+half)
        s = float(np.mean(score[mask])) if np.any(mask) else float(score[i])
        results.append((max(0, t), s))
    return results, duration

def make_watermark(path, w=900, h=160):
    img = Image.new("RGBA", (w,h), (0,0,0,0))
    d = ImageDraw.Draw(img)
    try: font = ImageFont.truetype("arial.ttf", 54)
    except: font = ImageFont.load_default()
    text = "EXOTIC DRIVE"
    bbox = d.textbbox((0,0), text, font=font, stroke_width=2)
    x = w - (bbox[2]-bbox[0]) - 25
    y = h - (bbox[3]-bbox[1]) - 20
    d.text((x,y), text, font=font, fill=(255,255,255,210), stroke_width=2, stroke_fill=(0,0,0,180))
    img.save(path)


def cut_clip(src, dst, start, length, vertical, wm):
    args = [
        "ffmpeg", "-y",
        "-ss", f"{start:.2f}",
        "-i", str(src),
        "-t", f"{length:.2f}"
    ]

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

    if wm:
        wm_path = str(Path(dst).with_suffix(".png"))
        make_watermark(wm_path)

        args += ["-i", wm_path]

        args += [
            "-filter_complex",
            f"[0:v]{vf}[base];"
            "[1:v]format=rgba[logo];"
            "[base][logo]overlay="
            "W-w-30:H-h-30:format=auto[vout]",
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

    if wm:
        try:
            os.remove(wm_path)
        except OSError:
            pass

if not ffmpeg_path() or not shutil.which("ffprobe"):
    st.error("FFmpeg belum terpasang / belum masuk PATH. Ikuti petunjuk instalasi di README.txt, lalu jalankan ulang dashboard.")
    st.stop()

uploads = st.file_uploader("Pilih satu atau beberapa video", type=["mp4","mov","mkv","avi","webm"], accept_multiple_files=True)
if uploads:
    out_root = Path("hasil_exotic_drive")
    out_root.mkdir(exist_ok=True)
    if st.button("🔎 ANALISIS & CARI HOOK", type="primary", use_container_width=True):
        st.session_state["results"] = []
        progress = st.progress(0)
        for n, up in enumerate(uploads):
            safe_name = Path(up.name).stem.replace(" ", "_")
            src = out_root / f"source_{n}_{safe_name}{Path(up.name).suffix}"
            src.write_bytes(up.getbuffer())
            with st.spinner(f"Menganalisis {up.name}..."):
                scores, duration = analyze_video(src)
            if not scores:
                st.warning(f"Tidak dapat membaca video: {up.name}")
                continue
            # Greedy non-overlapping top windows
            candidates = sorted(scores, key=lambda x:x[1], reverse=True)
            chosen = []
            for t, s in candidates:
                start = max(0, min(t - clip_len/2, max(0, duration-clip_len)))
                end = start + min(clip_len, duration)
                if all(end <= a or start >= b for a,b,_ in chosen):
                    chosen.append((start,end,s))
                if len(chosen) >= number_clips: break
            chosen.sort()
            st.session_state["results"].append({"name":up.name, "src":str(src), "clips":chosen, "duration":duration})
            progress.progress((n+1)/len(uploads))
        st.success("Analisis selesai. Periksa daftar momen dan buat clip.")

if st.session_state.get("results"):
    st.subheader("🎯 Momen yang ditemukan")
    for vi, item in enumerate(st.session_state["results"]):
        with st.expander(f"{item['name']} — {len(item['clips'])} kandidat", expanded=True):
            for ci, (start,end,score) in enumerate(item["clips"], 1):
                st.write(f"**Hook {ci}** · {start:.1f}s – {end:.1f}s · Skor daya tarik visual: {score*100:.0f}/100")
            if st.button(f"✂️ BUAT CLIP: {item['name']}", key=f"cut_{vi}", type="primary"):
                folder = out_root / f"clips_{vi}"
                folder.mkdir(exist_ok=True)
                vertical = aspect.startswith("9:16")
                made = []
                bar = st.progress(0)
                for ci,(start,end,score) in enumerate(item["clips"],1):
                    dst = folder / f"ExoticDrive_Hook_{ci}.mp4"
                    try:
                        cut_clip(item["src"], dst, start, end-start, vertical, watermark)
                        made.append(dst)
                    except Exception as e:
                        st.error(f"Gagal membuat clip {ci}: {e}")
                    bar.progress(ci/len(item["clips"]))
                for p in made:
                    st.video(str(p))
                    st.download_button(f"⬇️ Download {p.name}", p.read_bytes(), file_name=p.name, mime="video/mp4", key=f"dl_{vi}_{p.name}")
                st.info("Caption contoh: Full throttle, no fear! 🏁🔥 #ExoticDrive #TrophyTruck #OffRoadRacing #DesertRacing")
                st.caption("Periksa hasil sebelum upload. Tool ini menyiapkan file; upload ke Facebook/Instagram/TikTok dilakukan oleh Anda.")
else:
    st.info("Mulai dengan mengunggah video, lalu tekan ANALISIS & CARI HOOK.")
st.divider()
st.caption("EXOTIC DRIVE • Free local edition • Tidak menjamin viral. Selalu pastikan Anda memiliki hak untuk menggunakan video dan audio.")
