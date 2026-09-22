"""Offline M1 pipeline: local inputs to traceable, conservative study artifacts."""
from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from ..captions import load_captions, write_srt, write_vtt
from ..documents import extract_document

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _record(category, claim, source, cues=(), slides=(), uncertainty="待模型或人工复核"):
    start = end = None
    if cues:
        start, end = cues[0].start * 1000, cues[-1].end * 1000
    return {"id": f"e-{category.lower()}-{len(cues) or 'none'}", "category": category, "claim": claim,
            "source_ids": [source], "cue_ids": [c.id for c in cues], "start_ms": int(start) if start is not None else None,
            "end_ms": int(end) if end is not None else None, "slide_refs": list(slides), "confidence": 0.0,
            "uncertainty": uncertainty}

def prepare(input_dir: Path, output_dir: Path) -> dict:
    input_dir, output_dir = input_dir.resolve(), output_dir.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    if input_dir == output_dir or input_dir.is_relative_to(output_dir):
        raise ValueError("output must not equal or contain the input directory")
    found_captions = sorted(p for p in input_dir.rglob("*")
                           if p.is_file() and not p.is_relative_to(output_dir)
                           and p.suffix.lower() in {".vtt", ".srt", ".txt"})
    if not found_captions: raise ValueError("no .vtt, .srt, or .txt caption file found")
    # A captured lecture intentionally has both VTT and SRT. Prefer the timed
    # VTT pair by stem; separate stems still mean multiple lectures.
    stems = {}
    for path in found_captions:
        stems.setdefault(path.with_suffix('').as_posix().lower(), []).append(path)
    if len(stems) != 1:
        raise ValueError("experimental prepare accepts one lecture; select one caption stem explicitly")
    caption_paths = sorted(stems.values())[0]
    caption_paths.sort(key=lambda path: {'.vtt': 0, '.srt': 1, '.txt': 2}[path.suffix.lower()])
    if caption_paths[0].suffix.lower() == '.txt':
        raise ValueError("TXT has no timestamps; select the VTT or SRT for one lecture")
    caption_paths = caption_paths[:1]
    source_files = []
    all_cues = []
    for path in caption_paths:
        cues = load_captions(path); all_cues.extend(cues)
        source_files.append({"id": path.stem, "kind": "captions", "path": str(path.relative_to(input_dir)), "sha256": _sha(path), "cue_count": len(cues)})
    all_cues.sort(key=lambda cue: (cue.start, cue.end))
    write_vtt(all_cues, output_dir / "lecture.vtt"); write_srt(all_cues, output_dir / "lecture.srt")
    (output_dir / "lecture.txt").write_text("\n".join(c.text for c in all_cues) + "\n", encoding="utf-8")
    slides = []
    for path in sorted(p for p in input_dir.rglob("*") if p.is_file() and not p.is_relative_to(output_dir)
                       and p.suffix.lower() in {".pdf", ".pptx"}):
        pages = extract_document(path)
        source_files.append({"id": path.stem, "kind": "document", "path": str(path.relative_to(input_dir)), "sha256": _sha(path), "page_count": len(pages)})
        slides.extend({"source": path.stem, **page} for page in pages)
    manifest = {"schema_version": "0.1", "created_at": datetime.now(timezone.utc).isoformat(), "input_root": str(input_dir), "sources": source_files, "caption_count": len(all_cues), "document_pages": len(slides)}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    records = [_record("A", "已生成带页码/来源的课件索引；当前版本不自动声称主题对应。", "documents", slides=[f"{x['source']}#p{x['page']}" for x in slides], uncertainty="需要分析阶段根据字幕与课件建立主题映射。"),
               _record("B", "未生成未经证据复核的老师解释。", caption_paths[0].stem, uncertainty="需要分析阶段按 cue 建立老师解释记录。"),
               _record("C", "未生成课堂专业扩展。", caption_paths[0].stem),
               _record("D", "未自动判定课程公告或要求。", caption_paths[0].stem),
               _record("E", "未添加 AI 补充理解。", caption_paths[0].stem, uncertainty="后续生成内容必须显式标注为 AI 补充。")]
    with (output_dir / "evidence.jsonl").open("w", encoding="utf-8") as f:
        for record in records: f.write(json.dumps(record, ensure_ascii=False) + "\n")
    (output_dir / "companion.md").write_text("# 课堂伴读资料\n\n> 当前为 M1 离线准备结果。内容分类尚未调用模型；以下占位记录不会把推测归因于老师。\n\n## 课堂概览\n\n- 字幕 cue：%d\n- 课件页：%d\n\n## 证据分类\n\nA/B/C/D/E 的待处理记录见 `evidence.jsonl`。\n" % (len(all_cues), len(slides)), encoding="utf-8")
    report = validate(output_dir); (output_dir / "quality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest

def validate(run_dir: Path) -> dict:
    required = ["manifest.json", "lecture.vtt", "lecture.srt", "lecture.txt", "evidence.jsonl", "companion.md"]
    missing = [name for name in required if not (run_dir / name).is_file()]
    evidence = []
    path = run_dir / "evidence.jsonl"
    if path.exists():
        evidence = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = missing[:]
    for record in evidence:
        if record.get("category") not in {"A", "B", "C", "D", "E"}: errors.append(f"invalid category: {record.get('id')}")
        if not record.get("source_ids"): errors.append(f"missing source: {record.get('id')}")
    return {"valid": not errors, "errors": errors, "required_files": required, "evidence_records": len(evidence), "checked_at": datetime.now(timezone.utc).isoformat()}
