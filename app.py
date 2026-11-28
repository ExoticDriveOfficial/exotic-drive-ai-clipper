
import os
import json
import math
import shutil
import subprocess
import tempfile
import zipfile
import requests
import streamlit as st

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageStat
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import streamlit.components.v1 as components


# =====================================================
# EXOTIC DRIVE AI 2.0
# Direct Google Drive Resumable Upload
# =====================================================

st.set_page_config(
    page_title="EXOTIC DRIVE AI",
    page_icon="🏁",
    layout="wide"
)

BASE = Path(__file__).parent
WORK = BASE / "work"
OUT = BASE / "outputs"

WORK.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

FOLDER_NAME = "EXOTIC DRIVE AI UPLOADS"


# =====================================================
# GOOGLE DRIVE CONNECTION
# =====================================================

@st.cache_resource
def get_drive():

    if "google_drive" not in st.secrets:
        raise RuntimeError("Google Drive Secrets belum diatur.")

    raw = st.secrets["google_drive"]["token_json"]

    info = json.loads(raw)

    creds = Credentials.from_authorized_user_info(
        info,
        scopes=SCOPES
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds.valid:
        raise RuntimeError(
            "Token Google Drive tidak valid. Periksa OAuth."
        )

    service = build(
        "drive",
        "v3",
        credentials=creds,
        cache_discovery=False
    )

    return service, creds


def get_folder(service):

    query = (
        "name='" + FOLDER_NAME + "' "
        "and mimeType='application/vnd.google-apps.folder' "
        "and trashed=false"
    )

    result = service.files().list(
        q=query,
        fields="files(id,name)",
        pageSize=20
    ).execute()

    folders = result.get("files", [])

    if folders:
        return folders[0]["id"]

    folder = service.files().create(
        body={
            "name": FOLDER_NAME,
            "mimeType": "application/vnd.google-apps.folder"
        },
        fields="id,name"
    ).execute()

    return folder["id"]


# =====================================================
# FACEBOOK PAGE CONNECTION & REELS PUBLISHING
# =====================================================

def get_facebook_config():
    if "facebook" not in st.secrets:
        raise RuntimeError(
            "Facebook Secrets belum ditemukan."
        )

    config = st.secrets["facebook"]

    page_id = str(config.get("page_id", "")).strip()
    page_token = str(
        config.get("page_access_token", "")
    ).strip()
    version = str(
        config.get("graph_api_version", "v27.0")
    ).strip()

    if not page_id or not page_token:
        raise RuntimeError(
            "Page ID atau Page Access Token belum diatur."
        )

    return page_id, page_token, version


def facebook_request_check(response, action):
    try:
        data = response.json()
    except Exception:
        raise RuntimeError(
            action + ": respons Facebook tidak dapat dibaca."
        )

    if not response.ok or "error" in data:
        error = data.get("error", {})
        message = error.get(
            "message",
            response.text[:1000]
        )
        raise RuntimeError(
            action + " gagal: " + str(message)
        )

    return data


def test_facebook_connection():
    page_id, token, version = get_facebook_config()

    url = (
        f"https://graph.facebook.com/"
        f"{version}/{page_id}"
    )

    response = requests.get(
        url,
        params={
            "fields": "id,name",
            "access_token": token
        },
        timeout=30
    )

    return facebook_request_check(
        response,
        "Pemeriksaan Facebook"
    )


def publish_facebook_reel(video_path, caption):
    page_id, token, version = get_facebook_config()

    video_path = Path(video_path)

    if not video_path.exists():
        raise RuntimeError(
            "File Reels tidak ditemukan."
        )

    file_size = video_path.stat().st_size

    if file_size <= 0:
        raise RuntimeError(
            "File Reels kosong."
        )

    endpoint = (
        f"https://graph.facebook.com/"
        f"{version}/{page_id}/video_reels"
    )

    # TAHAP 1: Memulai sesi upload Reels
    start_response = requests.post(
        endpoint,
        data={
            "upload_phase": "START",
            "access_token": token
        },
        timeout=60
    )

    start_data = facebook_request_check(
        start_response,
        "Memulai upload Reels"
    )

    video_id = start_data.get("video_id")
    upload_url = start_data.get("upload_url")

    if not video_id or not upload_url:
        raise RuntimeError(
            "Facebook tidak memberikan video_id "
            "atau upload_url."
        )

    # TAHAP 2: Mengirim file video ke Facebook
    headers = {
        "Authorization": "OAuth " + token,
        "offset": "0",
        "file_size": str(file_size),
        "Content-Type": "application/octet-stream"
    }

    with open(video_path, "rb") as video_file:
        upload_response = requests.post(
            upload_url,
            headers=headers,
            data=video_file,
            timeout=(60, 900)
        )

    upload_data = facebook_request_check(
        upload_response,
        "Mengunggah file video"
    )

    if upload_data.get("success") is False:
        raise RuntimeError(
            "Facebook menolak file video."
        )

    # TAHAP 3: Menyelesaikan upload dan menerbitkan Reel
    finish_response = requests.post(
        endpoint,
        data={
            "upload_phase": "FINISH",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": caption,
            "access_token": token
        },
        timeout=120
    )

    finish_data = facebook_request_check(
        finish_response,
        "Menerbitkan Reels"
    )

    if finish_data.get("success") is not True:
        raise RuntimeError(
            "Facebook belum mengonfirmasi publikasi. "
            + str(finish_data)
        )

    return {
        "success": True,
        "video_id": video_id,
        "post_id": finish_data.get("post_id")
    }

# =====================================================
# CREATE RESUMABLE UPLOAD SESSION
# =====================================================


def create_upload_session(
    creds,
    folder_id,
    filename,
    mime_type
):

    url = (
        "https://www.googleapis.com/upload/drive/v3/files"
        "?uploadType=resumable"
        "&fields=id,name,size,mimeType,webViewLink"
    )

    metadata = {
        "name": Path(filename).name,
        "mimeType": mime_type,
        "parents": [folder_id]
    }

    headers = {
        "Authorization": "Bearer " + creds.token,
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": mime_type,
        "Origin": "https://exotic-drive-official.streamlit.app"
    }

    response = requests.post(
        url,
        headers=headers,
        json=metadata,
        timeout=60
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(
            "Gagal membuat sesi upload: "
            + response.text[:1000]
        )

    upload_url = response.headers.get("Location")

    if not upload_url:
        raise RuntimeError(
            "Google tidak memberikan alamat upload."
        )

    return upload_url


# =====================================================
# BROWSER DIRECT UPLOAD
# =====================================================

def upload_widget(upload_url):

    safe_url = json.dumps(upload_url)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
    <style>
    body {
        font-family: Arial, sans-serif;
        background: transparent;
        color: inherit;
    }

    .panel {
        border: 1px solid #777;
        border-radius: 12px;
        padding: 16px;
    }

    button {
        background: #16834a;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 12px 20px;
        margin-top: 12px;
        cursor: pointer;
        font-weight: bold;
    }

    progress {
        width: 100%;
        height: 18px;
        margin-top: 15px;
    }

    #status {
        margin-top: 12px;
        font-size: 14px;
        overflow-wrap: anywhere;
    }
    </style>
    </head>

    <body>

    <div class="panel">

        <h3>🏁 EXOTIC DRIVE VIDEO UPLOAD</h3>

        <p>
        Pilih video dari HP atau komputer.
        Video akan dikirim langsung ke Google Drive
        secara bertahap.
        </p>

        <input
            type="file"
            id="file"
            accept="video/mp4,video/quicktime,video/x-m4v,video/x-matroska"
        />

        <br>

        <button id="upload">
            MULAI UPLOAD
        </button>

        <progress
            id="progress"
            value="0"
            max="100"
        ></progress>

        <div id="status">
            Menunggu video...
        </div>

    </div>

    <script>

    const uploadURL = """ + safe_url + """;

    const input = document.getElementById("file");
    const button = document.getElementById("upload");
    const progress = document.getElementById("progress");
    const status = document.getElementById("status");

    const CHUNK = 8 * 1024 * 1024;

    button.onclick = async function() {

        const file = input.files[0];

        if (!file) {
            status.innerText = "Pilih video terlebih dahulu.";
            return;
        }

        if (!file.type.startsWith("video/")) {
            status.innerText = "File harus berupa video.";
            return;
        }

        button.disabled = true;

        let start = 0;

        try {

            while (start < file.size) {

                const end = Math.min(
                    start + CHUNK,
                    file.size
                );

                const chunk = file.slice(start, end);

                status.innerText =
                    "Mengunggah " +
                    (start / 1024 / 1024).toFixed(1) +
                    " MB dari " +
                    (file.size / 1024 / 1024).toFixed(1) +
                    " MB";

                const response = await fetch(
                    uploadURL,
                    {
                        method: "PUT",

                        headers: {
                            "Content-Type": file.type,
                            "Content-Range":
                                "bytes " +
                                start +
                                "-" +
                                (end - 1) +
                                "/" +
                                file.size
                        },

                        body: chunk
                    }
                );

                if (
                    response.status === 200 ||
                    response.status === 201
                ) {

                    const data = await response.json();

                    progress.value = 100;

                    status.innerText =
                        "UPLOAD BERHASIL! " +
                        data.name +
                        " | ID: " +
                        data.id;

                    button.disabled = false;
                    return;
                }

                if (response.status !== 308) {

                    const errorText =
                        await response.text();

                    throw new Error(
                        "Google Drive: " +
                        response.status +
                        " " +
                        errorText
                    );
                }

                start = end;

                progress.value =
                    (start / file.size) * 100;
            }

        } catch (error) {

            status.innerText =
                "UPLOAD GAGAL: " + error.message;

        }

        button.disabled = false;
    };

    </script>

    </body>
    </html>
    """

    components.html(
        html,
        height=310,
        scrolling=True
    )


# =====================================================
# GOOGLE DRIVE FILE LIST
# =====================================================

def list_videos(service, folder_id):

    result = service.files().list(
        q=(
            "'" + folder_id + "' in parents "
            "and trashed=false"
        ),
        fields="files(id,name,size,mimeType,createdTime)",
        pageSize=100,
        orderBy="createdTime desc"
    ).execute()

    return [
        f for f in result.get("files", [])
        if f.get("mimeType", "").startswith("video/")
    ]


# =====================================================
# DOWNLOAD FROM GOOGLE DRIVE TO SERVER DISK
# =====================================================

def download_drive_file(service, file_id, destination):

    request = service.files().get_media(
        fileId=file_id
    )

    with open(destination, "wb") as file:

        downloader = MediaIoBaseDownload(
            file,
            request,
            chunksize=8 * 1024 * 1024
        )

        done = False

        while not done:
            _, done = downloader.next_chunk()


# =====================================================
# VIDEO TOOLS
# =====================================================

def run_command(cmd):

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr[-2000:]
        )

    return result.stdout.strip()


def probe_duration(path):

    value = run_command([
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ])

    return float(value)


# =====================================================
# FREE LOCAL HIGHLIGHT ANALYSIS
# =====================================================

def analyze_video(video, duration, clip_seconds=20):

    temp = Path(
        tempfile.mkdtemp(dir=WORK)
    )

    try:

        # Ambil satu frame per detik pada resolusi kecil agar
        # analisis gratis tetap relatif ringan untuk server.
        run_command([
            "ffmpeg",
            "-y",
            "-i", str(video),
            "-vf",
            "fps=1,scale=320:180",
            "-q:v", "5",
            str(temp / "frame_%06d.jpg")
        ])

        files = sorted(
            temp.glob("frame_*.jpg")
        )

        if len(files) < 2:
            raise RuntimeError(
                "Frame video tidak dapat dibaca."
            )

        # Ukur dua hal:
        # 1) Rata-rata perubahan piksel.
        # 2) Persentase area gambar yang berubah cukup jelas.
        # Gabungan ini menjadi indikator aktivitas visual.
        motion_values = []
        previous = None

        for frame in files:

            image = Image.open(frame).convert("L")

            if previous is None:
                motion = 0.0
            else:
                difference = ImageChops.difference(
                    previous,
                    image
                )

                mean_change = (
                    ImageStat.Stat(difference).mean[0] / 255.0
                )

                changed = difference.point(
                    lambda pixel: 255 if pixel >= 20 else 0
                )

                histogram = changed.histogram()
                total_pixels = max(1, image.width * image.height)
                changed_ratio = (
                    sum(histogram[1:]) / total_pixels
                )

                motion = (
                    0.70 * mean_change
                    + 0.30 * changed_ratio
                )

            motion_values.append(motion)
            previous = image

        length = max(
            5,
            min(
                int(clip_seconds),
                int(math.ceil(duration))
            )
        )

        candidates = []

        max_start = max(
            0,
            int(duration) - length
        )

        step = max(1, length // 4)

        for start in range(
            0,
            max_start + 1,
            step
        ):

            end_index = min(
                len(motion_values),
                start + length
            )

            values = motion_values[
                max(1, start + 1):end_index
            ]

            if not values:
                continue

            average_motion = sum(values) / len(values)
            peak_motion = max(values)

            # Nilai gabungan memberi bobot lebih besar pada
            # gerakan yang konsisten, dengan bonus untuk momen puncak.
            activity = (
                0.80 * average_motion
                + 0.20 * peak_motion
            )

            candidates.append({
                "activity": activity,
                "average_motion": average_motion,
                "peak_motion": peak_motion,
                "start": float(start),
                "end": float(min(duration, start + length))
            })

        candidates.sort(
            key=lambda item: item["activity"],
            reverse=True
        )

        selected = []

        for candidate in candidates:

            start_time = candidate["start"]
            end_time = candidate["end"]

            # Hindari klip-klip yang saling tumpang tindih.
            if all(
                end_time <= item["start"]
                or start_time >= item["end"]
                for item in selected
            ):
                selected.append(candidate)

            # Tidak ada batas 3 klip: tampilkan semua kandidat
            # yang tidak saling tumpang tindih.

        results = []

        for item in selected:

            # Skor absolut berbasis intensitas perubahan visual,
            # bukan angka peringkat buatan seperti 100, 96, 92.
            # Skor tetap indikator visual, bukan pengenal aksi/viral.
            activity_score = round(
                100 * (
                    1 - math.exp(-5 * item["activity"])
                )
            )

            activity_score = max(
                0,
                min(100, activity_score)
            )

            results.append({
                "start": item["start"],
                "end": item["end"],
                "score": activity_score,
                "average_motion": round(
                    item["average_motion"], 4
                ),
                "peak_motion": round(
                    item["peak_motion"], 4
                ),
                "reason": (
                    "Skor dihitung dari rata-rata perubahan visual "
                    "dan puncak gerakan pada klip ini."
                )
            })

        return results

    finally:
        shutil.rmtree(
            temp,
            ignore_errors=True
        )


# =====================================================
# UNIQUE CAPTIONS FOR EACH REEL
# =====================================================

def make_reel_caption(clip_index, activity_score, video_name):
    """
    Membuat caption berbeda untuk setiap klip.
    Caption bersifat generik karena analisis gratis saat ini
    mengukur gerakan visual, bukan memahami objek/aksi secara semantik.
    """
    captions = [
        (
            "When the dirt flies, the adrenaline takes over! "
            "Which moment was your favorite? 🏁🔥",
            "#TrophyTruck #OffRoadAction #DirtFlying"
        ),
        (
            "Full throttle, raw power, and pure off-road excitement! "
            "Would you ride along? 🚙💨",
            "#OffRoadRacing #TruckAction #FullThrottle"
        ),
        (
            "This is what unstoppable off-road energy looks like! "
            "Turn up the volume and enjoy the ride! 🔥",
            "#OffRoadLife #RaceTruck #AdrenalineRush"
        ),
        (
            "Big tires. Wild terrain. Nothing but serious action! "
            "Who else loves this? 🤘",
            "#BigTires #OffRoadAdventure #TruckLife"
        ),
        (
            "The terrain is tough, but the action is even tougher! "
            "Rate this run from 1 to 10! 🏁",
            "#DesertRacing #OffRoadFans #Motorsports"
        ),
        (
            "A little dirt, a lot of horsepower, and endless excitement! "
            "Share this with an off-road fan! 💥",
            "#Horsepower #TrophyTruckRacing #OffRoadCommunity"
        ),
        (
            "No smooth roads needed when the adventure is this good! "
            "Would you take on this course? 🌵",
            "#RoughTerrain #DesertTruck #AdventureRacing"
        ),
        (
            "The kind of off-road action that keeps you watching! "
            "Stay until the end! 👀🔥",
            "#ActionReplay #OffRoadVideo #RaceDay"
        ),
        (
            "Power meets dirt in this wild off-road moment! "
            "Drop a 🏁 if you want more! 🚀",
            "#OffRoadPower #TruckRacing #DirtAction"
        ),
        (
            "Real machines. Rugged terrain. Unforgettable moments! "
            "Which truck would you choose? 🛻",
            "#MonsterTruck #OffRoadWorld #MotorsportFans"
        ),
        (
            "Every second brings another dose of off-road adrenaline! "
            "Follow for more action! 🔥🏁",
            "#AdrenalineJunkies #OffRoadClips #RacingAction"
        ),
        (
            "Built for the rough stuff and made for moments like this! "
            "Let us know what you think! 💪",
            "#BuiltForOffRoad #TrophyTrucks #ExtremeTerrain"
        ),
    ]

    # Seed berdasarkan nama video supaya variasi tetap konsisten
    # ketika dashboard dirender ulang.
    seed = sum(ord(char) for char in str(video_name))
    choice = (seed + int(clip_index)) % len(captions)
    caption, hashtags = captions[choice]

    score_line = (
        "High-activity moment!" if activity_score >= 90
        else "A strong off-road moment!" if activity_score >= 75
        else "A great off-road moment!"
    )

    return f"{caption}\n\n{score_line}\n\n#ExoticDrive {hashtags}"


# =====================================================
# WATERMARK
# =====================================================

def create_watermark(path):

    image = Image.new(
        "RGBA",
        (900, 110),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype(
            "DejaVuSans-Bold.ttf",
            48
        )
    except Exception:
        font = ImageFont.load_default()

    draw.text(
        (18, 15),
        "EXOTIC DRIVE",
        font=font,
        fill=(255, 255, 255, 225),
        stroke_width=2,
        stroke_fill=(0, 0, 0, 180)
    )

    image.save(path)


# =====================================================
# RENDER VERTICAL REELS
# =====================================================

def render_reel(
    source,
    start,
    end,
    destination,
    watermark=True
):

    command = [
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-i", str(source),
        "-t", str(max(1, end - start))
    ]

    if watermark:

        watermark_path = WORK / "watermark.png"

        create_watermark(watermark_path)

        command += [
            "-i", str(watermark_path),
            "-filter_complex",
            (
                "[0:v]scale=1080:1920:"
                "force_original_aspect_ratio=increase,"
                "crop=1080:1920,setsar=1[v];"
                "[v][1:v]overlay=40:40[vout]"
            ),
            "-map", "[vout]",
            "-map", "0:a?"
        ]

    else:

        command += [
            "-vf",
            (
                "scale=1080:1920:"
                "force_original_aspect_ratio=increase,"
                "crop=1080:1920,setsar=1"
            )
        ]

    command += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "21",
        "-c:a", "aac",
        "-b:a", "160k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(destination)
    ]

    run_command(command)


# =====================================================
# MAIN DASHBOARD
# =====================================================

st.title("🏁 EXOTIC DRIVE AI")

st.caption(
    "Direct Google Drive Upload • Free Auto Cut "
    "• Hook Finder • Reels 9:16"
)

try:

    service, credentials = get_drive()
    folder_id = get_folder(service)

    st.success(
        "Google Drive berhasil terhubung."
    )

except Exception as error:

    st.error(
        "Koneksi Google Drive gagal: "
        + str(error)
    )

    st.stop()


# =====================================================
# SIDEBAR
# =====================================================

with st.sidebar:

    st.header("⚙️ Pengaturan")

    clip_seconds = st.slider(
        "Durasi Reels",
        10,
        30,
        20
    )

    add_watermark = st.checkbox(
        "Watermark EXOTIC DRIVE",
        value=True
    )

    st.info(
        "Mode gratis mengukur perubahan visual. "
        "Caption tiap Reels dibuat bervariasi; skor "
        "dibandingkan dengan bagian lain dalam video."
    )


# =====================================================
# UPLOAD SECTION
# =====================================================

st.subheader("1. Upload Video Besar")

st.write(
    "Pilih nama video terlebih dahulu. "
    "Setelah itu gunakan pemilih file di bawah."
)

filename = st.text_input(
    "Nama file video",
    placeholder="contoh: trophy_truck_race.mp4"
)

if st.button(
    "Buat Sesi Upload",
    type="primary",
    use_container_width=True
):

    if not filename.strip():

        st.error("Masukkan nama file.")

    else:

        try:

            upload_url = create_upload_session(
                credentials,
                folder_id,
                filename,
                "video/mp4"
            )

            st.session_state["upload_url"] = upload_url

            st.success(
                "Sesi upload berhasil dibuat. "
                "Pilih video dengan nama yang sama."
            )

        except Exception as error:

            st.error(str(error))


if st.session_state.get("upload_url"):

    st.warning(
        "Pilih file video dengan nama yang sama "
        "dengan nama yang didaftarkan sebelumnya."
    )

    upload_widget(
        st.session_state["upload_url"]
    )

    st.caption(
        "Jika upload berhasil, tekan tombol "
        "Perbarui Daftar Video di bawah."
    )


# =====================================================
# DRIVE VIDEO LIST
# =====================================================

st.divider()

st.subheader("2. Video di Google Drive")

if st.button(
    "🔄 Perbarui Daftar Video"
):

    st.session_state["refresh_files"] = True


try:

    videos = list_videos(
        service,
        folder_id
    )

except Exception as error:

    st.error(str(error))
    videos = []


if not videos:

    st.info(
        "Belum ada video di folder upload."
    )

else:

    options = {
        f"{item['name']} | "
        f"{int(item.get('size', 0)) / 1024 / 1024:.1f} MB":
        item["id"]
        for item in videos
    }

    selected_label = st.selectbox(
        "Pilih video untuk Auto Cut",
        list(options.keys())
    )

    selected_id = options[selected_label]

    selected_file = next(
        item for item in videos
        if item["id"] == selected_id
    )

    size_mb = (
        int(selected_file.get("size", 0))
        / 1024 / 1024
    )

    st.write(
        f"Ukuran video: {size_mb:.1f} MB"
    )


    # =================================================
    # ANALYZE SELECTED VIDEO
    # =================================================

    if st.button(
        "🔎 ANALISIS HOOK & HIGHLIGHT",
        type="primary",
        use_container_width=True
    ):

        try:

            source = WORK / (
                selected_id + "_" +
                Path(selected_file["name"]).name
            )

            with st.spinner(
                "Mengunduh video dari Google Drive..."
            ):

                download_drive_file(
                    service,
                    selected_id,
                    source
                )

            with st.spinner(
                "Menganalisis aktivitas video..."
            ):

                duration = probe_duration(source)

                clips = analyze_video(
                    source,
                    duration,
                    clip_seconds
                )

                # Caption berbeda untuk setiap klip/Reels.
                for clip_index, clip in enumerate(clips):
                    clip["caption"] = make_reel_caption(
                        clip_index,
                        clip["score"],
                        selected_file["name"]
                    )

            st.session_state["analysis"] = {
                "source": str(source),
                "name": selected_file["name"],
                "duration": duration,
                "clips": clips
            }

            st.success(
                "Analisis selesai!"
            )

        except Exception as error:

            st.error(
                "Gagal menganalisis video: "
                + str(error)
            )


# =====================================================
# RESULTS & RENDER
# =====================================================

analysis = st.session_state.get("analysis")

if analysis:

    st.divider()

    st.subheader(
        "3. Pilihan Hook dan Highlight"
    )

    st.write(
        "Video: " + analysis["name"]
    )

    st.success(
        f"Semua hasil highlight ditampilkan: "
        f"{len(analysis['clips'])} klip. "
        "Daftar diurutkan dari Activity Score tertinggi."
    )

    st.info(
        "Activity Score dihitung dari perubahan piksel dan area gambar "
        "yang berubah. Skor membantu membandingkan intensitas visual, "
        "tetapi gerakan kamera juga dapat memengaruhi nilai dan "
        "skor bukan jaminan viral."
    )

    # Render semua highlight sekaligus dan kemas hasilnya ke ZIP.
    st.markdown("### 🎬 Proses semua highlight sekaligus")
    st.caption(
        "Semua klip di bawah akan dibuat dalam format MP4 vertikal 9:16. "
        "Setelah selesai, hasilnya bisa diunduh dalam satu file ZIP."
    )

    if st.button(
        f"🎬 BUAT SEMUA REELS ({len(analysis['clips'])} KLIP)",
        type="primary",
        use_container_width=True,
        key="render_all_reels"
    ):
        source_path = Path(analysis["source"])
        if not source_path.exists():
            st.error(
                "File sumber tidak ditemukan di server. "
                "Silakan jalankan analisis video kembali."
            )
        else:
            created_files = []
            failures = []
            progress = st.progress(0)
            status = st.empty()

            for batch_index, batch_clip in enumerate(analysis["clips"]):
                batch_destination = OUT / (
                    Path(analysis["name"]).stem
                    + f"_reel_{batch_index + 1}.mp4"
                )
                status.write(
                    f"Membuat Reels {batch_index + 1} dari "
                    f"{len(analysis['clips'])}..."
                )
                try:
                    render_reel(
                        source_path,
                        batch_clip["start"],
                        batch_clip["end"],
                        batch_destination,
                        add_watermark
                    )
                    created_files.append(batch_destination)
                except Exception as batch_error:
                    failures.append(
                        f"Reels {batch_index + 1}: {batch_error}"
                    )

                progress.progress(
                    (batch_index + 1) / len(analysis["clips"])
                )

            if created_files:
                zip_path = OUT / (
                    Path(analysis["name"]).stem + "_ALL_REELS.zip"
                )
                with zipfile.ZipFile(
                    zip_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    for video_path in created_files:
                        archive.write(
                            video_path,
                            arcname=video_path.name
                        )

                st.session_state["all_reels_zip"] = str(zip_path)
                st.success(
                    f"Selesai! {len(created_files)} dari "
                    f"{len(analysis['clips'])} Reels berhasil dibuat."
                )
                if failures:
                    st.warning("Beberapa klip gagal dibuat:\n" + "\n".join(failures))
            else:
                st.error(
                    "Tidak ada Reels yang berhasil dibuat. "
                    + " | ".join(failures)
                )

    saved_zip = st.session_state.get("all_reels_zip")
    if saved_zip and Path(saved_zip).exists():
        zip_file = Path(saved_zip)
        with open(zip_file, "rb") as zip_data:
            st.download_button(
                "⬇️ DOWNLOAD SEMUA REELS (ZIP)",
                data=zip_data,
                file_name=zip_file.name,
                mime="application/zip",
                key="download_all_reels_zip",
                use_container_width=True
            )

    
    st.divider()
    st.markdown("### Pilih dan buat Reels satu per satu")

    for index, clip in enumerate(analysis["clips"]):

        start = clip["start"]
        end = clip["end"]

        destination = OUT / (
            Path(analysis["name"]).stem
            + f"_reel_{index + 1}.mp4"
        )

        caption_key = f"caption_{index}"
        approval_key = f"approve_facebook_{index}"
        published_key = (
            "facebook_published_"
            + Path(analysis["name"]).stem
            + f"_{index + 1}"
        )

        st.markdown(f"**Highlight {index + 1}**")

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Activity Score (0–100)",
            str(clip["score"]) + "/100"
        )

        col2.write(f"{start:.1f}s – {end:.1f}s")

        col3.write(clip["reason"])

        st.caption(
            "Rata-rata gerakan visual: "
            + str(clip.get("average_motion", 0))
            + " | Puncak: "
            + str(clip.get("peak_motion", 0))
        )

        st.markdown("**Caption Reels Facebook**")

        caption_value = st.text_area(
            "Edit caption sebelum publikasi",
            value=clip.get(
                "caption",
                make_reel_caption(
                    index,
                    clip["score"],
                    analysis["name"]
                )
            ),
            height=125,
            key=caption_key
        )

        if st.button(
            f"✂️ BUAT REELS {index + 1}",
            key=f"render_{index}"
        ):

            try:
                with st.spinner(
                    "Membuat video vertikal 9:16..."
                ):
                    render_reel(
                        analysis["source"],
                        start,
                        end,
                        destination,
                        add_watermark
                    )

                st.success("Reels berhasil dibuat!")

            except Exception as error:
                st.error(
                    "Gagal membuat Reels: " + str(error)
                )

        # Tampilkan preview jika file sudah tersedia.
        if destination.exists():

            st.video(str(destination))

            with open(destination, "rb") as video_file:
                st.download_button(
                    "⬇️ DOWNLOAD REELS",
                    data=video_file,
                    file_name=destination.name,
                    mime="video/mp4",
                    key=f"download_{index}"
                )

            st.divider()
            st.markdown("**Publikasikan ke Facebook Page Exotic Drive**")

            # Tampilkan status publikasi jika sudah berhasil.
            if st.session_state.get(published_key):

                publish_result = st.session_state[published_key]

                st.success(
                    "Reels ini sudah berhasil dikirim ke Facebook!"
                )

                st.write(
                    "Facebook Video ID: "
                    + str(publish_result.get("video_id", "-"))
                )

            else:

                st.warning(
                    "Periksa video dan caption terlebih dahulu. "
                    "Publikasi hanya dilakukan setelah Anda menyetujui."
                )

                st.checkbox(
                    "Saya sudah memeriksa video dan caption, "
                    "serta menyetujui publikasi ke Facebook Exotic Drive.",
                    key=approval_key
                )

                if st.button(
                    f"🚀 SETUJUI & PUBLISH REELS {index + 1}",
                    type="primary",
                    use_container_width=True,
                    key=f"publish_facebook_{index}",
                    disabled=not st.session_state.get(approval_key, False)
                ):

                    try:
                        with st.spinner(
                            "Mengirim Reels ke Facebook. "
                            "Mohon jangan tutup dashboard..."
                        ):

                            result = publish_facebook_reel(
                                destination,
                                caption_value
                            )

                        st.session_state[published_key] = result

                        st.success(
                            "BERHASIL! Reels sudah diterbitkan "
                            "ke Facebook Page Exotic Drive."
                        )

                        st.write(
                            "Facebook Video ID: "
                            + str(result.get("video_id", "-"))
                        )

                    except Exception as error:

                        st.error(
                            "Publikasi gagal: " + str(error)
                        )

        else:

            st.info(
                "Buat Reels terlebih dahulu agar preview "
                "dan tombol publikasi tersedia."
            )

# =====================================================
# FOOTER
# =====================================================

st.divider()

st.caption(
    "EXOTIC DRIVE AI | Google Drive Storage "
    "| Free Motion Analysis | Vertical 9:16"
)

st.caption(
    "Catatan: Activity Score mengukur perubahan visual, bukan prediksi viral. "
    "Video 8K asli tidak dijamin; output saat ini "
    "adalah 1080 × 1920."
)
