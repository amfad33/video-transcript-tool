from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[\.,]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[\.,]\d{1,3})"
)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class TranscriptSegment:
    start: float | None
    end: float | None
    text: str


@dataclass
class TranscriptResult:
    source: str
    title: str
    method: str
    language: str | None
    language_probability: float | None
    segments: list[TranscriptSegment]


def slugify(value: str, fallback: str = "transcript") -> str:
    value = html.unescape(value)
    value = re.sub(r"[^\w\s.-]+", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return value[:120] or fallback


def seconds_to_srt(value: float) -> str:
    millis = int(round(value * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def seconds_to_vtt(value: float) -> str:
    return seconds_to_srt(value).replace(",", ".")


def caption_time_to_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def strip_caption_text(line: str) -> str:
    line = TAG_RE.sub("", line)
    line = html.unescape(line)
    return re.sub(r"\s+", " ", line).strip()


def parse_vtt_or_srt(text: str) -> list[TranscriptSegment]:
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n{2,}", text)
    segments: list[TranscriptSegment] = []

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if lines[0].upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue

        timestamp_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timestamp_index is None:
            continue

        match = TIMESTAMP_RE.search(lines[timestamp_index])
        if not match:
            continue

        text_lines = [strip_caption_text(line) for line in lines[timestamp_index + 1 :]]
        cue_text = " ".join(line for line in text_lines if line)
        if not cue_text:
            continue

        if segments and segments[-1].text == cue_text:
            continue

        segments.append(
            TranscriptSegment(
                start=caption_time_to_seconds(match.group("start")),
                end=caption_time_to_seconds(match.group("end")),
                text=cue_text,
            )
        )

    return segments


def parse_json3(text: str) -> list[TranscriptSegment]:
    data = json.loads(text)
    segments: list[TranscriptSegment] = []
    for event in data.get("events", []):
        text_parts = [part.get("utf8", "") for part in event.get("segs", [])]
        cue_text = strip_caption_text("".join(text_parts))
        if not cue_text:
            continue
        start = event.get("tStartMs")
        duration = event.get("dDurationMs", 0)
        start_seconds = start / 1000 if start is not None else None
        end_seconds = (start + duration) / 1000 if start is not None else None
        if segments and segments[-1].text == cue_text:
            continue
        segments.append(TranscriptSegment(start_seconds, end_seconds, cue_text))
    return segments


def transcript_text(segments: Iterable[TranscriptSegment]) -> str:
    return "\n".join(segment.text for segment in segments if segment.text).strip() + "\n"


def write_outputs(result: TranscriptResult, output_dir: Path, formats: set[str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / slugify(result.title)
    written: list[Path] = []

    if "txt" in formats:
        path = base.with_suffix(".txt")
        path.write_text(transcript_text(result.segments), encoding="utf-8")
        written.append(path)

    if "srt" in formats:
        path = base.with_suffix(".srt")
        lines: list[str] = []
        for index, segment in enumerate(result.segments, start=1):
            if segment.start is None or segment.end is None:
                continue
            lines.extend(
                [
                    str(index),
                    f"{seconds_to_srt(segment.start)} --> {seconds_to_srt(segment.end)}",
                    segment.text,
                    "",
                ]
            )
        path.write_text("\n".join(lines), encoding="utf-8")
        written.append(path)

    if "vtt" in formats:
        path = base.with_suffix(".vtt")
        lines = ["WEBVTT", ""]
        for segment in result.segments:
            if segment.start is None or segment.end is None:
                continue
            lines.extend(
                [
                    f"{seconds_to_vtt(segment.start)} --> {seconds_to_vtt(segment.end)}",
                    segment.text,
                    "",
                ]
            )
        path.write_text("\n".join(lines), encoding="utf-8")
        written.append(path)

    if "json" in formats:
        path = base.with_suffix(".json")
        path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)

    return written


def import_yt_dlp():
    try:
        import yt_dlp
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: yt-dlp. Install with: python -m pip install -r requirements.txt"
        ) from exc
    return yt_dlp


def import_faster_whisper():
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: faster-whisper. Install with: python -m pip install -r requirements.txt"
        ) from exc
    return WhisperModel


def cookie_options(args: argparse.Namespace) -> dict:
    options: dict = {}
    if args.cookies_file:
        options["cookiefile"] = args.cookies_file
    if args.cookies_from_browser:
        browser, _, profile = args.cookies_from_browser.partition(":")
        options["cookiesfrombrowser"] = (browser, profile or None, None, None)
    return options


def yt_dlp_base_options(args: argparse.Namespace, quiet: bool = True) -> dict:
    return {
        "quiet": quiet,
        "no_warnings": quiet,
        "noplaylist": not args.playlist,
        **cookie_options(args),
    }


def download_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def language_matches(candidate: str, preferred: str) -> bool:
    preferred = preferred.strip()
    if not preferred:
        return False
    if preferred.endswith(".*"):
        return candidate == preferred[:-2] or candidate.startswith(preferred[:-1])
    return candidate == preferred


def pick_caption_track(info: dict, subtitle_langs: list[str]) -> tuple[str, dict, str] | None:
    sources = [("subtitles", "manual-captions"), ("automatic_captions", "auto-captions")]
    preferred_exts = ("vtt", "srt", "json3")

    for source_key, method in sources:
        tracks = info.get(source_key) or {}
        usable_langs = [lang for lang in tracks if lang != "live_chat"]
        ordered_langs: list[str] = []
        for preferred in subtitle_langs:
            ordered_langs.extend(
                lang for lang in usable_langs if lang not in ordered_langs and language_matches(lang, preferred)
            )
        ordered_langs.extend(lang for lang in usable_langs if lang not in ordered_langs)

        for lang in ordered_langs:
            formats = tracks.get(lang) or []
            for ext in preferred_exts:
                track = next((item for item in formats if item.get("ext") == ext and item.get("url")), None)
                if track:
                    return lang, track, method
    return None


def try_caption_transcript(source: str, args: argparse.Namespace) -> TranscriptResult | None:
    yt_dlp = import_yt_dlp()
    with yt_dlp.YoutubeDL(yt_dlp_base_options(args)) as ydl:
        info = ydl.extract_info(source, download=False)

    track_info = pick_caption_track(info, args.subtitle_langs)
    if not track_info:
        return None

    language, track, method = track_info
    raw_text = download_text(track["url"])
    ext = track.get("ext")
    if ext == "json3":
        segments = parse_json3(raw_text)
    else:
        segments = parse_vtt_or_srt(raw_text)

    if not segments:
        return None

    return TranscriptResult(
        source=source,
        title=info.get("title") or info.get("id") or "transcript",
        method=method,
        language=language,
        language_probability=None,
        segments=segments,
    )


def download_media(source: str, args: argparse.Namespace, temp_dir: Path) -> tuple[Path, dict]:
    yt_dlp = import_yt_dlp()
    output_template = str(temp_dir / "%(id)s.%(ext)s")
    options = {
        **yt_dlp_base_options(args, quiet=False),
        "format": "bestaudio/best",
        "outtmpl": output_template,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(source, download=True)

    requested = info.get("requested_downloads") or []
    for download in requested:
        filepath = download.get("filepath")
        if filepath and Path(filepath).exists():
            return Path(filepath), info

    expected = Path(yt_dlp.YoutubeDL(options).prepare_filename(info))
    if expected.exists():
        return expected, info

    candidates = sorted(temp_dir.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0], info
    raise RuntimeError("yt-dlp finished but no downloaded media file was found.")


def transcribe_media(source: str, media_path: Path, title: str, args: argparse.Namespace) -> TranscriptResult:
    WhisperModel = import_faster_whisper()
    compute_type = args.compute_type or ("float16" if args.device == "cuda" else "int8")
    model = WhisperModel(args.model, device=args.device, compute_type=compute_type)
    segments_iter, info = model.transcribe(
        str(media_path),
        beam_size=args.beam_size,
        language=args.language,
        vad_filter=True,
    )
    segments = [
        TranscriptSegment(segment.start, segment.end, segment.text.strip())
        for segment in segments_iter
        if segment.text.strip()
    ]
    return TranscriptResult(
        source=source,
        title=title,
        method="faster-whisper",
        language=getattr(info, "language", None),
        language_probability=getattr(info, "language_probability", None),
        segments=segments,
    )


def process_source(source: str, args: argparse.Namespace) -> TranscriptResult:
    local_path = Path(source)
    if local_path.exists():
        return transcribe_media(source, local_path, local_path.stem, args)

    if not args.force_whisper:
        caption_result = try_caption_transcript(source, args)
        if caption_result:
            return caption_result

    temp_dir = Path(tempfile.mkdtemp(prefix="transcript-tool-"))
    try:
        media_path, info = download_media(source, args, temp_dir)
        title = info.get("title") or info.get("id") or media_path.stem
        result = transcribe_media(source, media_path, title, args)
        if args.keep_media:
            media_dir = args.output_dir / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(media_path, media_dir / media_path.name)
        return result
    finally:
        if not args.keep_temp:
            shutil.rmtree(temp_dir, ignore_errors=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create transcripts from YouTube, Google Drive, direct video URLs, or local media files."
    )
    parser.add_argument("sources", nargs="+", help="One or more URLs or local audio/video files.")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("transcripts"))
    parser.add_argument("--formats", default="txt,srt,json", help="Comma-separated: txt,srt,vtt,json")
    parser.add_argument("--language", help="Spoken language hint for Whisper, such as en, fa, es.")
    parser.add_argument(
        "--subtitle-langs",
        default=None,
        help='Comma-separated subtitle language preference. Default: language.*,language or "en.*,en".',
    )
    parser.add_argument("--force-whisper", action="store_true", help="Ignore available captions and transcribe audio.")
    parser.add_argument("--model", default="small", help="Whisper model: tiny, base, small, medium, large-v3, turbo.")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--compute-type", help="Override faster-whisper compute type, e.g. int8, float16.")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--cookies-file", help="Netscape cookies.txt file for private/login-only videos.")
    parser.add_argument(
        "--cookies-from-browser",
        help='Load browser cookies via yt-dlp, for example "chrome" or "edge:Default".',
    )
    parser.add_argument("--playlist", action="store_true", help="Allow playlist URLs instead of only the single video.")
    parser.add_argument("--keep-media", action="store_true", help="Copy downloaded media into output_dir/media.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary downloads for debugging.")
    args = parser.parse_args(argv)

    formats = {item.strip().lower() for item in args.formats.split(",") if item.strip()}
    allowed_formats = {"txt", "srt", "vtt", "json"}
    unknown_formats = formats - allowed_formats
    if unknown_formats:
        parser.error(f"Unknown output format(s): {', '.join(sorted(unknown_formats))}")
    args.formats = formats or {"txt"}

    if args.subtitle_langs:
        args.subtitle_langs = [item.strip() for item in args.subtitle_langs.split(",") if item.strip()]
    elif args.language:
        args.subtitle_langs = [f"{args.language}.*", args.language]
    else:
        args.subtitle_langs = ["en.*", "en"]

    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    had_error = False

    for source in args.sources:
        print(f"Processing: {source}")
        try:
            result = process_source(source, args)
            written = write_outputs(result, args.output_dir, args.formats)
        except Exception as exc:
            had_error = True
            print(f"  Error: {exc}", file=sys.stderr)
            continue

        print(f"  Method: {result.method}")
        if result.language:
            print(f"  Language: {result.language}")
        for path in written:
            print(f"  Wrote: {path}")

    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
