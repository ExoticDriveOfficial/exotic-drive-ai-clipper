
if analysis:

    st.divider()

    st.subheader(
        "3. Pilihan Hook dan Highlight"
    )

    st.write(
        "Video: " + analysis["name"]
    )

    st.info(
        "Activity Score menunjukkan peringkat aktivitas visual "
        "relatif di dalam video ini. Skor tinggi membantu memilih "
        "bagian paling aktif, tetapi bukan jaminan viral."
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
            "Activity Score (relatif)",
            str(clip["score"]) + "/100"
        )

        col2.write(
            f"{start:.1f}s – {end:.1f}s"
        )

        col3.write(
            clip["reason"]
        )

        st.markdown("**Caption unik untuk Reels ini**")
        st.text_area(
            "Caption siap salin",
            value=clip.get("caption", make_reel_caption(
                index, clip["score"], analysis["name"]
            )),
            height=125,
            key=f"caption_{index}"
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
    "Catatan: Activity Score adalah peringkat relatif, bukan prediksi viral. "
    "Video 8K asli tidak dijamin; output saat ini "
    "adalah 1080 × 1920."
)
