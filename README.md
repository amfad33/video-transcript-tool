# Video Transcript Tool

A local command-line tool for creating transcripts from videos and audio files.

The tool is designed to be practical first: it uses existing captions when they are available, and falls back to local speech-to-text when captions are missing or unusable.

## What It Does

- Accepts YouTube URLs, Google Drive video links, direct media URLs, and local audio/video files.
- Looks for manual captions first, then YouTube auto-captions.
- Downloads audio with `yt-dlp` when captions are not available.
- Transcribes locally with `faster-whisper`.
- Writes transcript files to `transcripts/`.
- Supports `txt`, `srt`, `vtt`, and `json` output formats.
- Can use browser cookies or a cookies file for private videos you can already access.

## What It Uses

- Python 3.11 or 3.12
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) for video metadata, captions, cookies, and media downloads
- [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) for local Whisper transcription
- CTranslate2 through `faster-whisper` for efficient CPU or CUDA inference
- Python standard library modules for parsing captions, formatting timestamps, and writing outputs
- `unittest` for the included parser tests

No paid transcription API is required. Whisper models are downloaded locally the first time they are used.

## How It Works

1. For URL sources, the tool asks `yt-dlp` for metadata and caption tracks.
2. It prefers manual captions over auto-captions.
3. It parses VTT, SRT, or YouTube `json3` captions when a usable track exists.
4. It cleans repeated rolling auto-caption text.
5. If captions are unavailable, or `--force-whisper` is used, it downloads the media audio.
6. It transcribes that audio with `faster-whisper`.
7. It writes the requested transcript formats into the output directory.

Local files skip the caption lookup and go straight to Whisper transcription.

## Install

Use normal Windows Python 3.11 or 3.12. Avoid MSYS2/Git Bash Python for this project because it can create a `.venv\bin` layout that PowerShell will not activate with `.\.venv\Scripts\Activate.ps1`.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If `py` is not available, install Python 3.12 from python.org and enable "Add python.exe to PATH" during install. Then reopen PowerShell and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you use Conda:

```powershell
conda create -n video-transcript python=3.12 -y
conda activate video-transcript
python -m pip install -r requirements.txt
```

## Basic Use

Transcribe a YouTube video:

```powershell
python .\transcript_tool.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Transcribe a Google Drive video:

```powershell
python .\transcript_tool.py "https://drive.google.com/file/d/FILE_ID/view?usp=sharing"
```

Transcribe a local file:

```powershell
python .\transcript_tool.py "C:\path\to\video.mp4"
```

Process more than one source:

```powershell
python .\transcript_tool.py "VIDEO_URL_1" "VIDEO_URL_2" "C:\path\to\audio.mp3"
```

By default, outputs are written to `transcripts/` as:

- `.txt` plain text
- `.srt` subtitles
- `.json` structured metadata and segments

## Useful Options

Choose output formats:

```powershell
python .\transcript_tool.py --formats txt,srt,vtt,json "VIDEO_URL"
```

Use a custom output directory:

```powershell
python .\transcript_tool.py --output-dir .\out "VIDEO_URL"
```

Use Whisper even when captions exist:

```powershell
python .\transcript_tool.py --force-whisper "VIDEO_URL"
```

Hint the spoken language:

```powershell
python .\transcript_tool.py --language fa "VIDEO_URL"
```

Prefer specific subtitle languages:

```powershell
python .\transcript_tool.py --subtitle-langs fa.*,fa,en "VIDEO_URL"
```

Use a faster or more accurate Whisper model:

```powershell
python .\transcript_tool.py --model base "VIDEO_URL"
python .\transcript_tool.py --model medium "VIDEO_URL"
```

Use NVIDIA GPU if CUDA is set up:

```powershell
python .\transcript_tool.py --device cuda --model medium "VIDEO_URL"
```

Load cookies from a browser for private videos your browser can access:

```powershell
python .\transcript_tool.py --cookies-from-browser chrome "VIDEO_URL"
```

Use a cookies file:

```powershell
python .\transcript_tool.py --cookies-file .\cookies.txt "VIDEO_URL"
```

Allow playlist processing:

```powershell
python .\transcript_tool.py --playlist "PLAYLIST_URL"
```

Keep downloaded media alongside the transcript outputs:

```powershell
python .\transcript_tool.py --keep-media "VIDEO_URL"
```

## Output Details

The JSON output includes:

- original source
- title
- transcription method
- detected or selected language
- language probability when Whisper provides it
- timestamped transcript segments

The SRT and VTT outputs include timestamps when the source data provides them. Plain text output contains only the cleaned transcript text.

## Windows Troubleshooting

Check which Python PowerShell is using:

```powershell
where.exe python
python --version
```

If the first result is under `C:\msys64\...`, install or use normal Windows Python instead:

```powershell
py -3.12 -m venv .venv
```

If activation is blocked by PowerShell execution policy, run this once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

If virtual environment creation fails with a `PermissionError` in a temp folder, set a clean temporary folder for the current PowerShell window and try again:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\python-temp" | Out-Null
$env:TEMP = "$env:USERPROFILE\python-temp"
$env:TMP = "$env:USERPROFILE\python-temp"
py -3.12 -m venv .venv
```

## Run Tests

```powershell
python -m unittest discover -s tests
```

The tests cover caption parsing, timestamp formatting, JSON caption parsing, and auto-caption de-duplication.

## Notes

- `small` is the default Whisper model.
- Use `base` for faster local transcription.
- Use `medium`, `large-v3`, or `turbo` when accuracy matters more than speed.
- CPU transcription works but can be slow for long files.
- Speech-to-text can contain mistakes, especially with noisy audio, overlapping speakers, music, accents, or long silences.
- Only download or transcribe media that you have the right to access and process.
