CLIPFORGE AI — UPDATED BUILD

FEATURES
- Mobile-friendly Streamlit interface
- Recognizes and previews common YouTube watch, youtu.be, Shorts, live and embed links using YouTube's official embedded player
- Upload MP4, MOV, M4V, WEBM or MKV videos for editing
- Load direct public video-file URLs (subject to access/CORS/server restrictions)
- Transcribe speech using open-source Whisper
- Suggest multiple highlight clips automatically
- Choose 9:16, 1:1 or 16:9
- Burn subtitles into exported MP4 clips
- Review and adjust clip start/end times before export

IMPORTANT YOUTUBE LIMITATION
A YouTube watch URL is not a downloadable video file. The app can preview the link, but cannot legally/technically use the watch page itself as the source media for clipping. To create clips, upload the original video file that you own or have permission to edit, or use an authorized direct media source. This app does not bypass YouTube restrictions, logins, DRM or platform controls.

RUN LOCALLY
1. Install Python 3.10 or newer.
2. Install FFmpeg and make sure `ffmpeg` and `ffprobe` are on PATH.
3. In this folder run: pip install -r requirements.txt
4. Run: streamlit run app.py
5. Open the local URL shown by Streamlit.

DEPLOY ON STREAMLIT COMMUNITY CLOUD
1. Upload these four files to the root of your GitHub repository.
2. Create an app at https://share.streamlit.io/
3. Select your repository, branch `main`, and main file `app.py`.
4. Deploy. Free hosting has CPU, memory, runtime and upload limits. Whisper model downloads can take time.
