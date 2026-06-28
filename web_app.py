from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, send_file, url_for

from dub_pipeline import (
    TIMING_MODES,
    TRANSLATION_MODELS,
    TRANSCRIPTION_PROVIDERS,
    TTS_MODELS,
    TTS_VOICES,
    WHISPER_MODELS,
    OPENAI_TRANSCRIPTION_MODELS,
    DubJob,
    DubSegment,
    approve_segments,
    build_audio_and_video,
    load_dub_segments,
    load_job,
    load_transcript,
    make_job_id,
    timing_diagnostics,
    translate_segments,
    transcribe_video,
)

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)


def job_path(job_id: str) -> Path:
    return OUTPUTS_DIR / job_id / "job.json"


@app.get("/")
def index():
    sample_path = BASE_DIR / "test video.mp4"
    return render_template(
        "index.html",
        has_api_key=bool(os.environ.get("OPENAI_API_KEY")),
        sample_path=str(sample_path) if sample_path.exists() else "",
        whisper_models=WHISPER_MODELS,
        transcription_providers=TRANSCRIPTION_PROVIDERS,
        openai_transcription_models=OPENAI_TRANSCRIPTION_MODELS,
        translation_models=TRANSLATION_MODELS,
        tts_models=TTS_MODELS,
        tts_voices=TTS_VOICES,
        timing_modes=TIMING_MODES,
    )


@app.post("/jobs")
def create_job():
    try:
        uploaded = request.files.get("video_file")
        local_path = request.form.get("local_path", "").strip()
        if uploaded and uploaded.filename:
            source_name = Path(uploaded.filename).name
            source_path = UPLOADS_DIR / source_name
            uploaded.save(source_path)
        elif local_path:
            source_path = Path(local_path).expanduser().resolve()
            if not source_path.exists():
                raise FileNotFoundError(f"Video was not found: {source_path}")
        else:
            raise ValueError("Upload a video file or provide a local path.")

        job_id = make_job_id(source_path)
        output_dir = OUTPUTS_DIR / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        job = DubJob(
            job_id=job_id,
            source_path=str(source_path),
            source_language=request.form.get("source_language", "fa") or "fa",
            target_language=request.form.get("target_language", "en") or "en",
            transcription_provider=request.form.get("transcription_provider", "openai"),
            whisper_model=request.form.get("whisper_model", "small"),
            openai_transcription_model=request.form.get("openai_transcription_model", "whisper-1"),
            translation_model=request.form.get("translation_model", "gpt-4.1"),
            tts_model=request.form.get("tts_model", "gpt-4o-mini-tts"),
            tts_voice=request.form.get("tts_voice", "alloy"),
            timing_mode=request.form.get("timing_mode", "smart"),
            tts_speed=float(request.form.get("tts_speed", "1.0") or 1.0),
            max_speed_adjustment=float(request.form.get("max_speed_adjustment", "0.10") or 0.10),
            output_dir=str(output_dir),
        )
        from dub_pipeline import save_job

        save_job(job)
        transcript = transcribe_video(job)
        translate_segments(job, transcript)
        return redirect(url_for("review_job", job_id=job.job_id))
    except Exception as exc:
        return render_template("error.html", title="Job failed", message=str(exc)), 500


@app.get("/jobs/<job_id>/review")
def review_job(job_id: str):
    job = load_job(job_path(job_id))
    transcript = load_transcript(Path(job.transcript_path))
    segments = load_dub_segments(Path(job.translation_path))
    diagnostics = timing_diagnostics(job, segments)
    rows = list(zip(transcript.segments, segments, diagnostics))
    return render_template("review.html", job=job, rows=rows)


@app.post("/jobs/<job_id>/approve")
def approve_job(job_id: str):
    try:
        job = load_job(job_path(job_id))
        count = int(request.form["count"])
        segments: list[DubSegment] = []
        for index in range(count):
            segments.append(
                DubSegment(
                    start=float(request.form[f"start_{index}"]) if request.form.get(f"start_{index}") else None,
                    end=float(request.form[f"end_{index}"]) if request.form.get(f"end_{index}") else None,
                    original_text=request.form[f"original_{index}"],
                    translated_text=request.form[f"translated_{index}"].strip(),
                    notes=request.form.get(f"notes_{index}", ""),
                )
            )
        approve_segments(job, segments)
        build_audio_and_video(job, segments)
        return redirect(url_for("result_job", job_id=job.job_id))
    except Exception as exc:
        return render_template("error.html", title="Build failed", message=str(exc)), 500


@app.get("/jobs/<job_id>")
def result_job(job_id: str):
    job = load_job(job_path(job_id))
    files = [
        path
        for path in [job.transcript_path, job.translation_path, job.approved_path, job.timing_report_path, job.audio_path, job.video_path]
        if path
    ]
    return render_template("result.html", job=job, files=files)


@app.get("/download/<job_id>/<path:name>")
def download(job_id: str, name: str):
    path = (OUTPUTS_DIR / job_id / name).resolve()
    if OUTPUTS_DIR.resolve() not in path.parents:
        raise ValueError("Invalid download path.")
    return send_file(path, as_attachment=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
