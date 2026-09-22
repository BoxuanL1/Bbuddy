from blackboard_companion.captions import parse_vtt, CaptionError

def test_parse_and_unescape():
    cues = parse_vtt("WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nA &amp; B")
    assert cues[0].start == 1 and cues[0].text == "A & B"

def test_rejects_invalid_timing():
    try: parse_vtt("WEBVTT\n\n00:00:02.000 --> 00:00:01.000\nno")
    except CaptionError: pass
    else: raise AssertionError("invalid cue was accepted")
