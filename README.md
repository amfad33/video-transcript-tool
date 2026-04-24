# Video Transcript Tool

Local CLI for getting transcripts from YouTube, Google Drive, direct video URLs, or local audio/video files.

It tries captions first, including YouTube auto-captions. If no usable captions exist, it downloads the audio with `yt-dlp` and transcribes locally with `faster-whisper`, so it can still handle videos that do not have subtitles.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Use

```powershell
python .\transcript_tool.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Outputs go to `transcripts/` as `.txt`, `.srt`, and `.json` by default.

Google Drive public/shared videos work the same way:

```powershell
python .\transcript_tool.py "https://drive.google.com/file/d/FILE_ID/view?usp=sharing"
```

Local files also work:

```powershell
python .\transcript_tool.py "C:\path\to\video.mp4"
```

## Useful Options

Use Whisper even when captions exist:

```powershell
python .\transcript_tool.py --force-whisper "VIDEO_URL"
```

Hint the spoken language:

```powershell
python .\transcript_tool.py --language fa "VIDEO_URL"
```

Use a faster or more accurate model:

```powershell
python .\transcript_tool.py --model base "VIDEO_URL"
python .\transcript_tool.py --model medium "VIDEO_URL"
```

Use NVIDIA GPU if CUDA is set up:

```powershell
python .\transcript_tool.py --device cuda --model medium "VIDEO_URL"
```

For private videos that your browser can access:

```powershell
python .\transcript_tool.py --cookies-from-browser chrome "VIDEO_URL"
```

Or use a cookies file:

```powershell
python .\transcript_tool.py --cookies-file .\cookies.txt "VIDEO_URL"
```

## Notes

- This is free to run locally, but the first Whisper run downloads the selected model.
- `small` is the default model. Use `base` for speed or `medium`/`large-v3` for better accuracy.
- Transcripts from speech-to-text can contain mistakes, especially with poor audio, overlapping voices, music, or long silences.
- Only transcribe videos you have the right to access and process.
