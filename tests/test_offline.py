import json
import pytest
from pathlib import Path
from blackboard_companion.pipeline.offline import prepare, validate

def test_prepare_synthetic(tmp_path):
    source = Path(__file__).parents[1] / "examples" / "synthetic-course"
    out = tmp_path / "output"
    manifest = prepare(source, out)
    assert manifest["caption_count"] == 2
    report = validate(out)
    assert report["valid"]
    assert len((out / "evidence.jsonl").read_text(encoding="utf-8").splitlines()) == 5
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["sources"]


def test_repeated_nested_output_is_not_reimported(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'lecture.vtt').write_text('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello')
    output = source / 'output'
    assert prepare(source, output)['caption_count'] == 1
    assert prepare(source, output)['caption_count'] == 1


def test_multiple_lectures_and_untimed_input_are_rejected(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'lecture.txt').write_text('No real timestamps here.')
    with pytest.raises(ValueError):
        prepare(source, tmp_path / 'output')
    (source / 'lecture.vtt').write_text('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello')
    (source / 'other.vtt').write_text('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nOther')
    with pytest.raises(ValueError):
        prepare(source, tmp_path / 'output')


def test_vtt_and_srt_pair_is_one_lecture(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'lecture.vtt').write_text('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello')
    (source / 'lecture.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\nHello')
    assert prepare(source, tmp_path / 'output')['caption_count'] == 1
