from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import certifi
from dotenv import load_dotenv
from openai import OpenAI

from transcript_tool import TranscriptResult, TranscriptSegment, process_source, write_outputs

load_dotenv()
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())


TimingMode = Literal["smart", "strict", "overlap", "resegment"]
TranscriptionProvider = Literal["openai", "local"]

TRANSLATION_MODELS = ["gpt-4.1", "gpt-4o", "gpt-4.1-mini", "gpt-4o-mini"]
TTS_MODELS = ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]
TTS_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "marin", "nova", "onyx", "sage", "shimmer", "verse", "cedar"]
WHISPER_MODELS = ["small", "medium", "large-v3", "turbo"]
OPENAI_TRANSCRIPTION_MODELS = ["whisper-1", "gpt-4o-mini-transcribe", "gpt-4o-transcribe"]
TRANSCRIPTION_PROVIDERS = ["openai", "local"]
TIMING_MODES = ["smart", "overlap", "strict", "resegment"]


@dataclass
class DubSegment:
    start: float | None
    end: float | None
    original_text: str
    translated_text: str
    notes: str = ""


@dataclass
class TimingDiagnostic:
    index: int
    start: float | None
    end: float | None
    slot_duration: float | None
    estimated_duration: float
    required_speed: float | None
    status: str
    message: str


@dataclass
class DubJob:
    job_id: str
    source_path: str
    source_language: str
    target_language: str
    transcription_provider: TranscriptionProvider
    whisper_model: str
    openai_transcription_model: str
    translation_model: str
    tts_model: str
    tts_voice: str
    timing_mode: TimingMode
    output_dir: str
    tts_speed: float = 1.0
    max_speed_adjustment: float = 0.1
    transcript_path: str | None = None
    translation_path: str | None = None
    approved_path: str | None = None
    audio_path: str | None = None
    video_path: str | None = None
    timing_report_path: str | None = None


def safe_stem(path: Path) -> str:
    stem = re.sub(r"[^\w\s.-]+", "", path.stem, flags=re.UNICODE).strip("._ ")
    return stem or "video"


def make_job_id(video_path: Path) -> str:
    return f"{safe_stem(video_path)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg was not found on PATH.")
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe was not found on PATH.")


def client() -> OpenAI:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set. Set it in your shell or a local .env file.")
    return OpenAI()


def save_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_job(path: Path) -> DubJob:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("tts_speed", 1.0)
    data.setdefault("max_speed_adjustment", 0.1)
    data.setdefault("timing_report_path", None)
    if data.get("timing_mode") not in TIMING_MODES:
        data["timing_mode"] = "smart"
    return DubJob(**data)


def save_job(job: DubJob) -> None:
    save_json(Path(job.output_dir) / "job.json", asdict(job))


def transcribe_video(job: DubJob) -> TranscriptResult:
    if job.transcription_provider == "openai":
        return transcribe_video_openai(job)
    return transcribe_video_local(job)


def transcribe_video_local(job: DubJob) -> TranscriptResult:
    from transcript_tool import parse_args

    args = parse_args(
        [
            "--language",
            job.source_language,
            "--model",
            job.whisper_model,
            "--formats",
            "json,srt,txt",
            "--output-dir",
            str(Path(job.output_dir) / "transcript_exports"),
            job.source_path,
        ]
    )
    result = process_source(job.source_path, args)
    transcript_path = Path(job.output_dir) / f"{job.job_id}_transcript.json"
    save_json(transcript_path, asdict(result))
    write_outputs(result, Path(job.output_dir) / "transcript_exports", args.formats)
    job.transcript_path = str(transcript_path)
    save_job(job)
    return result


def transcribe_video_openai(job: DubJob) -> TranscriptResult:
    api = client()
    source = Path(job.source_path)
    audio_path = Path(job.output_dir) / f"{job.job_id}_source_audio.mp3"
    ensure_ffmpeg()
    run(["ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(audio_path)])
    with audio_path.open("rb") as audio_file:
        response = api.audio.transcriptions.create(
            model=job.openai_transcription_model,
            file=audio_file,
            language=job.source_language,
            response_format="verbose_json",
        )

    raw_segments = getattr(response, "segments", None) or []
    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        if isinstance(item, dict):
            text = (item.get("text") or "").strip()
            start = item.get("start")
            end = item.get("end")
        else:
            text = (getattr(item, "text", "") or "").strip()
            start = getattr(item, "start", None)
            end = getattr(item, "end", None)
        if text:
            segments.append(TranscriptSegment(start=start, end=end, text=text))

    if not segments:
        text = (getattr(response, "text", "") or "").strip()
        segments = [TranscriptSegment(start=0.0, end=media_duration(source), text=text)] if text else []
    if not segments:
        raise RuntimeError("OpenAI transcription returned no text.")

    result = TranscriptResult(
        source=job.source_path,
        title=source.stem,
        method=f"openai-{job.openai_transcription_model}",
        language=job.source_language,
        language_probability=None,
        segments=segments,
    )
    transcript_path = Path(job.output_dir) / f"{job.job_id}_transcript.json"
    save_json(transcript_path, asdict(result))
    job.transcript_path = str(transcript_path)
    save_job(job)
    return result


def load_transcript(path: Path) -> TranscriptResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = [TranscriptSegment(**item) for item in data["segments"]]
    return TranscriptResult(
        source=data["source"],
        title=data["title"],
        method=data["method"],
        language=data.get("language"),
        language_probability=data.get("language_probability"),
        segments=segments,
    )


def translate_segments(job: DubJob, transcript: TranscriptResult) -> list[DubSegment]:
    api = client()
    payload = [asdict(segment) for segment in transcript.segments if segment.text.strip()]
    response = api.chat.completions.create(
        model=job.translation_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You translate Persian educational video transcripts into natural English voice-over. "
                    "Preserve meaning, technical terms, and segment order. Write concise spoken English for dubbing, "
                    "not literal subtitles. Prefer natural short sentences that can fit near the source timing. "
                    "If a faithful version is likely too long, make the English more compact and note that choice. "
                    "Return only JSON."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "source_language": job.source_language,
                        "target_language": job.target_language,
                        "segments": payload,
                        "required_schema": {
                            "segments": [
                                {
                                    "start": "number or null",
                                    "end": "number or null",
                                    "original_text": "source text",
                                    "translated_text": "English translation for TTS",
                                    "notes": "short optional warning or empty string",
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    data = json.loads(response.choices[0].message.content or "{}")
    translated = [DubSegment(**item) for item in data.get("segments", [])]
    if len(translated) != len(payload):
        raise RuntimeError("Translation response did not preserve the segment count.")
    translation_path = Path(job.output_dir) / f"{job.job_id}_translation.json"
    save_json(translation_path, [asdict(segment) for segment in translated])
    job.translation_path = str(translation_path)
    save_job(job)
    return translated


def load_dub_segments(path: Path) -> list[DubSegment]:
    return [DubSegment(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def approve_segments(job: DubJob, segments: list[DubSegment]) -> Path:
    approved_path = Path(job.output_dir) / f"{job.job_id}_approved.json"
    save_json(approved_path, [asdict(segment) for segment in segments])
    job.approved_path = str(approved_path)
    save_job(job)
    return approved_path


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return float(result.stdout.strip())


def speech_instructions(job: DubJob) -> str | None:
    if job.tts_model in {"tts-1", "tts-1-hd"}:
        return None
    if job.tts_speed > 1.0:
        return "Speak clearly with a compact educational voice-over cadence. Avoid long dramatic pauses."
    if job.tts_speed < 1.0:
        return "Speak clearly with a relaxed educational voice-over cadence."
    return "Speak clearly in a natural educational voice-over cadence."


def synthesize_segment(text: str, path: Path, job: DubJob, speed: float | None = None) -> None:
    api = client()
    request = {
        "model": job.tts_model,
        "voice": job.tts_voice,
        "input": text,
        "response_format": "wav",
        "speed": max(0.25, min(4.0, speed if speed is not None else job.tts_speed)),
    }
    instructions = speech_instructions(job)
    if instructions:
        request["instructions"] = instructions
    with api.audio.speech.with_streaming_response.create(
        **request,
    ) as response:
        response.stream_to_file(path)


def estimate_spoken_duration(text: str, speed: float = 1.0) -> float:
    words = re.findall(r"\b[\w'-]+\b", text)
    word_count = max(1, len(words))
    punctuation_pauses = len(re.findall(r"[,.!?;:]", text)) * 0.12
    return max(0.8, (word_count / 2.55 + punctuation_pauses) / max(0.25, speed))


def timing_diagnostic(index: int, segment: DubSegment, base_speed: float, max_adjustment: float) -> TimingDiagnostic:
    estimated_duration = estimate_spoken_duration(segment.translated_text, base_speed)
    if segment.start is None or segment.end is None:
        return TimingDiagnostic(index, segment.start, segment.end, None, estimated_duration, None, "ok", "No fixed timing.")
    slot_duration = max(0.1, segment.end - segment.start)
    required_speed = estimated_duration / slot_duration
    max_speed = 1.0 + max_adjustment
    if required_speed <= 0.92:
        status = "relaxed"
        message = "Short enough; natural speech plus silence."
    elif required_speed <= max_speed:
        status = "ok"
        message = "Fits with a small speed adjustment."
    elif required_speed <= max_speed + 0.12:
        status = "tight"
        message = "Tight timing; consider shortening for a more natural voice-over."
    else:
        status = "too-long"
        message = "Too long for natural timing; shorten this line before final build."
    return TimingDiagnostic(index, segment.start, segment.end, slot_duration, estimated_duration, required_speed, status, message)


def timing_diagnostics(job: DubJob, segments: list[DubSegment]) -> list[TimingDiagnostic]:
    return [timing_diagnostic(index, segment, job.tts_speed, job.max_speed_adjustment) for index, segment in enumerate(segments, start=1)]


def fit_audio_to_duration(input_path: Path, output_path: Path, target_duration: float) -> None:
    current = media_duration(input_path)
    if current <= 0 or target_duration <= 0:
        shutil.copy2(input_path, output_path)
        return
    ratio = current / target_duration
    if 1.0 <= ratio <= 1.08:
        run(["ffmpeg", "-y", "-i", str(input_path), "-filter:a", f"atempo={ratio:.6f}", str(output_path)])
    elif ratio < 1.0:
        run(["ffmpeg", "-y", "-i", str(input_path), "-af", f"apad,atrim=0:{target_duration:.3f}", str(output_path)])
    else:
        shutil.copy2(input_path, output_path)


def silence_file(path: Path, duration: float) -> None:
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{max(0.01, duration):.3f}", str(path)])


def segment_speed(job: DubJob, segment: DubSegment) -> float:
    if segment.start is None or segment.end is None:
        return job.tts_speed
    slot_duration = max(0.1, segment.end - segment.start)
    estimated = estimate_spoken_duration(segment.translated_text, job.tts_speed)
    if estimated <= slot_duration:
        return job.tts_speed
    required_multiplier = estimated / slot_duration
    return min(job.tts_speed * required_multiplier, job.tts_speed * (1.0 + job.max_speed_adjustment))


def build_concat_audio(source: Path, work_dir: Path, timed_dir: Path, job: DubJob, segments: list[DubSegment], smart: bool = False) -> Path:
    concat_lines: list[str] = []
    timing_report: list[dict[str, object]] = []
    cursor = 0.0
    for index, segment in enumerate(segments, start=1):
        start = segment.start if segment.start is not None else cursor
        end = segment.end if segment.end is not None else start + 1.0
        start = max(start, cursor)
        gap = max(0.0, start - cursor)
        if gap > 0:
            silence = timed_dir / f"{index:04d}_silence.wav"
            silence_file(silence, gap)
            concat_lines.append(f"file '{silence.as_posix()}'")

        raw_path = work_dir / "tts_segments" / f"{index:04d}.wav"
        final_path = timed_dir / f"{index:04d}.wav"
        requested_speed = segment_speed(job, segment) if smart else job.tts_speed
        synthesize_segment(segment.translated_text, raw_path, job, requested_speed)
        raw_duration = media_duration(raw_path)
        if segment.start is not None and segment.end is not None:
            slot_duration = max(0.1, end - start)
            if smart:
                current = raw_duration
                if current <= slot_duration:
                    shutil.copy2(raw_path, final_path)
                    cursor = start + current
                    pad = end - cursor
                    if pad > 0:
                        silence = timed_dir / f"{index:04d}_pad.wav"
                        silence_file(silence, pad)
                        cursor = end
                else:
                    ratio = current / slot_duration
                    if ratio <= 1.03:
                        fit_audio_to_duration(raw_path, final_path, slot_duration)
                        cursor = end
                    else:
                        shutil.copy2(raw_path, final_path)
                        cursor = start + current
            else:
                fit_audio_to_duration(raw_path, final_path, slot_duration)
                cursor = end
        else:
            shutil.copy2(raw_path, final_path)
            cursor = start + media_duration(final_path)
        concat_lines.append(f"file '{final_path.as_posix()}'")
        if smart and segment.start is not None and segment.end is not None and raw_duration <= max(0.1, end - start):
            pad_path = timed_dir / f"{index:04d}_pad.wav"
            if pad_path.exists():
                concat_lines.append(f"file '{pad_path.as_posix()}'")
        final_duration = media_duration(final_path)
        timing_report.append(
            {
                "index": index,
                "start": segment.start,
                "end": segment.end,
                "slot_duration": max(0.1, end - start) if segment.start is not None and segment.end is not None else None,
                "requested_tts_speed": round(requested_speed, 4),
                "raw_duration": round(raw_duration, 4),
                "final_duration": round(final_duration, 4),
                "final_to_slot_ratio": round(final_duration / max(0.1, end - start), 4) if segment.start is not None and segment.end is not None else None,
                "text": segment.translated_text,
            }
        )

    video_duration = media_duration(source)
    if cursor < video_duration:
        silence = timed_dir / "tail_silence.wav"
        silence_file(silence, video_duration - cursor)
        concat_lines.append(f"file '{silence.as_posix()}'")

    concat_file = work_dir / "audio_concat.txt"
    concat_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    audio_path = work_dir / f"{job.job_id}_audio.wav"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(audio_path)])
    report_path = work_dir / f"{job.job_id}_timing_report.json"
    save_json(report_path, timing_report)
    job.timing_report_path = str(report_path)
    return audio_path


def build_overlay_audio(source: Path, work_dir: Path, timed_dir: Path, job: DubJob, segments: list[DubSegment]) -> Path:
    inputs: list[str] = []
    filters: list[str] = []
    mix_labels: list[str] = []
    for index, segment in enumerate(segments, start=1):
        raw_path = work_dir / "tts_segments" / f"{index:04d}.wav"
        final_path = timed_dir / f"{index:04d}.wav"
        synthesize_segment(segment.translated_text, raw_path, job, job.tts_speed)
        shutil.copy2(raw_path, final_path)
        inputs.extend(["-i", str(final_path)])
        delay_ms = int(round((segment.start or 0.0) * 1000))
        label = f"a{index}"
        filters.append(f"[{index - 1}:a]adelay={delay_ms}|{delay_ms},apad[{label}]")
        mix_labels.append(f"[{label}]")

    audio_path = work_dir / f"{job.job_id}_audio.wav"
    if not inputs:
        silence_file(audio_path, media_duration(source))
        return audio_path

    filter_complex = ";".join(filters) + ";" + "".join(mix_labels) + f"amix=inputs={len(mix_labels)}:normalize=0,atrim=0:{media_duration(source):.3f}[out]"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", filter_complex, "-map", "[out]", str(audio_path)])
    return audio_path


def build_audio_and_video(job: DubJob, segments: list[DubSegment]) -> tuple[Path, Path]:
    ensure_ffmpeg()
    source = Path(job.source_path)
    work_dir = Path(job.output_dir)
    tts_dir = work_dir / "tts_segments"
    timed_dir = work_dir / "timed_segments"
    tts_dir.mkdir(exist_ok=True)
    timed_dir.mkdir(exist_ok=True)

    if job.timing_mode == "smart":
        audio_path = build_concat_audio(source, work_dir, timed_dir, job, segments, smart=True)
    elif job.timing_mode == "strict":
        audio_path = build_concat_audio(source, work_dir, timed_dir, job, segments)
    else:
        audio_path = build_overlay_audio(source, work_dir, timed_dir, job, segments)
    video_path = work_dir / f"{job.job_id}_english.mp4"
    run(["ffmpeg", "-y", "-i", str(source), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(video_path)])
    job.audio_path = str(audio_path)
    job.video_path = str(video_path)
    save_job(job)
    return audio_path, video_path
