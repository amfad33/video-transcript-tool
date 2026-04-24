import unittest

from transcript_tool import (
    TranscriptSegment,
    dedupe_rolling_captions,
    parse_json3,
    parse_vtt_or_srt,
    seconds_to_srt,
    transcript_text,
)


class TranscriptParsingTests(unittest.TestCase):
    def test_parse_vtt(self):
        text = """WEBVTT

00:00:01.000 --> 00:00:02.500
Hello <c>world</c>

00:00:03.000 --> 00:00:05.000
This &amp; that
"""
        segments = parse_vtt_or_srt(text)

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].start, 1.0)
        self.assertEqual(segments[0].end, 2.5)
        self.assertEqual(segments[0].text, "Hello world")
        self.assertEqual(transcript_text(segments), "Hello world\nThis & that\n")

    def test_parse_srt(self):
        text = """1
00:00:01,000 --> 00:00:02,500
Hello

2
00:00:03,000 --> 00:00:04,000
Again
"""
        segments = parse_vtt_or_srt(text)

        self.assertEqual([segment.text for segment in segments], ["Hello", "Again"])

    def test_parse_json3(self):
        text = '{"events":[{"tStartMs":1000,"dDurationMs":1500,"segs":[{"utf8":"Hi "},{"utf8":"there"}]}]}'
        segments = parse_json3(text)

        self.assertEqual(segments[0].start, 1.0)
        self.assertEqual(segments[0].end, 2.5)
        self.assertEqual(segments[0].text, "Hi there")

    def test_seconds_to_srt(self):
        self.assertEqual(seconds_to_srt(3661.25), "01:01:01,250")

    def test_dedupe_rolling_captions(self):
        segments = [
            TranscriptSegment(0.0, 1.0, "How's that uh how's that internet"),
            TranscriptSegment(1.0, 2.0, "How's that uh how's that internet though, dude?"),
            TranscriptSegment(2.0, 2.1, "though, dude?"),
            TranscriptSegment(2.1, 3.0, "though, dude? I see that she's not speaking up today."),
        ]

        cleaned = dedupe_rolling_captions(segments)

        self.assertEqual(
            [segment.text for segment in cleaned],
            [
                "How's that uh how's that internet",
                "though, dude?",
                "I see that she's not speaking up today.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
