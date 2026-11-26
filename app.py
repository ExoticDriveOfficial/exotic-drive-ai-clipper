
import os
import json
import math
import shutil
import subprocess
import tempfile
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
        "X-Upload-Content-Type": mime_type
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

        scores = []
        previous = None

        for frame in files:

            image = Image.open(frame).convert("L")

            if previous is None:
                score = 0
            else:
                difference = ImageChops.difference(
                    previous,
                    image
                )

                score = (
                    sum(ImageStat.Stat(difference).mean)
                    / 255
                )

            scores.append(score)
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

        for start in range(
            0,
            max_start + 1,
            max(1, length // 4)
        ):

            end = min(
                len(scores),
                start + length
            )

            values = scores[
                max(1, start + 1):end
            ]

            if not values:
                continue

            average = sum(values) / len(values)
            peak = max(values)

            total = (
                0.75 * average
                + 0.25 * peak
            )

            candidates.append((
                total,
                start,
                min(duration, start + length)
            ))

        candidates.sort(reverse=True)

        selected = []

        for score, start, end in candidates:

            if all(
                end <= item[1]
                or start >= item[2]
                for item in selected
            ):

                selected.append((
                    score,
                    start,
                    end
                ))

            if len(selected) >= 3:
                break

        selected.sort(key=lambda item: item[1])

        return [
            {
                "start": float(start),
                "end": float(end),
                "score": max(
                    1,
                    min(99, round(score * 100))
                ),
                "reason": (
                    "Perubahan visual relatif tinggi. "
                    "Periksa apakah adegan benar-benar "
                    "menampilkan aksi Trophy Truck."
                )
            }
            for score, start, end in selected
        ]

    finally:
        shutil.rmtree(
            temp,
            ignore_errors=True
        )


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
        "Mode gratis menggunakan analisis "
        "perubahan visual, bukan prediksi viral."
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

    st.write(
        "Caption: Big action. Big machines. "
        "Pure off-road adrenaline!"
    )

    st.write(
        "#ExoticDrive #TrophyTruck "
        "#OffRoad #DesertRacing"
    )

    for index, clip in enumerate(
        analysis["clips"]
    ):

        start = clip["start"]
        end = clip["end"]

        st.markdown(
            f"**Highlight {index + 1}**"
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Skor aktivitas",
            str(clip["score"]) + "/100"
        )

        col2.write(
            f"{start:.1f}s – {end:.1f}s"
        )

        col3.write(
            clip["reason"]
        )

        if st.button(
            f"✂️ BUAT REELS {index + 1}",
            key=f"render_{index}"
        ):

            destination = OUT / (
                Path(analysis["name"]).stem
                + f"_reel_{index + 1}.mp4"
            )

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

                st.success(
                    "Reels berhasil dibuat!"
                )

                st.video(
                    str(destination)
                )

                with open(destination, "rb") as file:

                    st.download_button(
                        "⬇️ DOWNLOAD REELS",
                        data=file,
                        file_name=destination.name,
                        mime="video/mp4",
                        key=f"download_{index}"
                    )

            except Exception as error:

                st.error(
                    "Gagal membuat Reels: "
                    + str(error)
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
    "Catatan: Skor aktivitas bukan prediksi viral. "
    "Video 8K asli tidak dijamin; output saat ini "
    "adalah 1080 × 1920."
)
