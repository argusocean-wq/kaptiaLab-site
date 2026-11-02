"""Build a deterministic, source-attributed local knowledge pack from approved project docs.

No network access and no third-party packages are required. This is a lexical retrieval
baseline, not a vector database. Only explicitly allowlisted Markdown files are ingested.
"""
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "knowledge" / "index.jsonl"
MANIFEST = ROOT / "knowledge" / "manifest.json"
ALLOWLIST = (
    "README.md",
    "docs/KAPTIA_MODEL_PLAN.md",
    "knowledge/PROJECT_CONTEXT.md",
)
CHUNK_CHARS = 900
OVERLAP_CHARS = 120


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repo_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def split_sections(text: str):
    """Keep headings attached to their section; split oversized sections by paragraphs."""
    heading = "文件內容"
    lines = []
    for line in text.splitlines():
        if line.startswith("#"):
            if lines:
                yield heading, "\n".join(lines).strip()
            heading = line.lstrip("#").strip() or "未命名章節"
            lines = [line]
        else:
            lines.append(line)
    if lines:
        yield heading, "\n".join(lines).strip()


def chunk_text(text: str):
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_CHARS:
        return [text]
    paragraphs = re.split(r"\n\s*\n", text)
    chunks, current = [], ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        candidate = f"{current}\n\n{paragraph}".strip()
        if len(candidate) <= CHUNK_CHARS:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= CHUNK_CHARS:
            current = paragraph
        else:
            start = 0
            while start < len(paragraph):
                end = min(start + CHUNK_CHARS, len(paragraph))
                chunks.append(paragraph[start:end])
                if end == len(paragraph):
                    break
                start = max(end - OVERLAP_CHARS, start + 1)
            current = ""
    if current:
        chunks.append(current)
    return chunks


def main():
    records, source_manifest = [], []
    missing = []
    for rel_path in ALLOWLIST:
        path = ROOT / rel_path
        if not path.is_file():
            missing.append(rel_path)
            continue
        raw = path.read_bytes()
        source_hash = sha256(raw)
        source_text = raw.decode("utf-8")
        source_manifest.append({
            "path": rel_path,
            "sha256": source_hash,
            "bytes": len(raw),
        })
        chunk_number = 0
        for section, body in split_sections(source_text):
            for chunk in chunk_text(body):
                records.append({
                    "id": f"{rel_path}#{chunk_number:04d}",
                    "source": rel_path,
                    "section": section,
                    "source_sha256": source_hash,
                    "text": chunk,
                })
                chunk_number += 1
    if missing:
        raise FileNotFoundError("知識來源檔案不存在，停止建立索引：" + ", ".join(missing))
    if not records:
        raise RuntimeError("沒有可索引的文字內容。")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_revision": repo_revision(),
        "chunk_chars": CHUNK_CHARS,
        "overlap_chars": OVERLAP_CHARS,
        "source_count": len(source_manifest),
        "chunk_count": len(records),
        "sources": source_manifest,
        "index_sha256": sha256(OUTPUT.read_bytes()),
        "note": "Local lexical retrieval baseline; generated timestamp is metadata, not proof of source freshness.",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[PASS] 來源文件：{len(source_manifest)}")
    print(f"[PASS] 知識片段：{len(records)}")
    print(f"[PASS] 索引：{OUTPUT.relative_to(ROOT)}")
    print(f"[PASS] 清單：{MANIFEST.relative_to(ROOT)}")
    print(f"[INFO] Git revision：{manifest['repository_revision']}")
    print("[WARN] 此流程只建立檢索資料，沒有訓練或修改模型權重。")


if __name__ == "__main__":
    main()
