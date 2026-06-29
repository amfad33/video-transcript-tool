import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dub_pipeline import DubJob, DubSegment, build_audio_and_video, translation_system_prompt


class DubPipelineTests(unittest.TestCase):
    def test_translation_prompt_uses_target_language(self):
        job = DubJob(
            job_id="test",
            source_path="video.mp4",
            source_language="fa",
            target_language="ar",
            transcription_provider="openai",
            whisper_model="small",
            openai_transcription_model="whisper-1",
            translation_model="gpt-4.1",
            tts_model="gpt-4o-mini-tts",
            tts_voice="alloy",
            timing_mode="smart",
            output_dir="outputs/test",
        )

        prompt = translation_system_prompt(job)

        self.assertIn("Persian", prompt)
        self.assertIn("Arabic voice-over", prompt)
        self.assertNotIn("English voice-over", prompt)

    def test_video_and_subtitle_outputs_share_stem(self):
        with TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "source.mp4"
            source.write_bytes(b"")
            job = DubJob(
                job_id="test_job",
                source_path=str(source),
                source_language="fa",
                target_language="ar",
                transcription_provider="openai",
                whisper_model="small",
                openai_transcription_model="whisper-1",
                translation_model="gpt-4.1",
                tts_model="gpt-4o-mini-tts",
                tts_voice="alloy",
                timing_mode="smart",
                output_dir=tmp_dir,
            )

            with patch("dub_pipeline.ensure_ffmpeg"), patch("dub_pipeline.build_concat_audio", return_value=Path(tmp_dir) / "audio.wav"), patch("dub_pipeline.run"):
                build_audio_and_video(job, [DubSegment(0.0, 1.0, "سلام", "مرحبا")])

            self.assertEqual(Path(job.video_path).stem, Path(job.subtitle_srt_path).stem)
            self.assertEqual(Path(job.video_path).stem, Path(job.subtitle_vtt_path).stem)


if __name__ == "__main__":
    unittest.main()
