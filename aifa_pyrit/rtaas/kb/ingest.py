"""Knowledge-base files for test generation and grading.

Produces three files from the ~60 KB PDFs:
  kb_manifest.json  one row per PDF: doc_id, file, title, url, version_date, sha256
  kb_chunks.jsonl   one row per chunk: chunk_id, doc_id, page, text  (512 tokens, 50 overlap)
  goldens.jsonl     one row per question: id, question, expected_answer, source_chunk_ids,
                    question_type, failure_mode

Goldens come from DeepEval's Synthesizer. A person must review them before
they are used as gold answers; generated answers are sometimes wrong.

    python -m app.kb.ingest --pdf-dir ./kb_pdfs --out ./kb_out --per-doc 2
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_manifest(pdf_dir: Path) -> list[dict]:
    rows = []
    for i, p in enumerate(sorted(pdf_dir.glob("*.pdf")), start=1):
        rows.append({
            "doc_id": f"KB-{i:03d}",
            "file": p.name,
            "title": p.stem.replace("_", " "),
            "url": "",            # fill in the official gov.bc.ca link by hand
            "version_date": "",   # fill in from the document
            "sha256": sha256(p),
        })
    return rows


def chunk_pdfs(pdf_dir: Path, manifest: list[dict], size: int = 512, overlap: int = 50) -> list[dict]:
    """Page-aware chunks. Word count stands in for tokens; close enough for grading."""
    from pypdf import PdfReader

    out = []
    for doc in manifest:
        reader = PdfReader(pdf_dir / doc["file"])
        n = 0
        for page_no, page in enumerate(reader.pages, start=1):
            words = (page.extract_text() or "").split()
            step = size - overlap
            for start in range(0, max(len(words), 1), step):
                text = " ".join(words[start:start + size]).strip()
                if not text:
                    continue
                n += 1
                out.append({"chunk_id": f"{doc['doc_id']}-C{n:04d}", "doc_id": doc["doc_id"],
                            "page": page_no, "text": text})
    return out


def generate_goldens(pdf_dir: Path, manifest: list[dict], per_doc: int = 2) -> list[dict]:
    """Single-turn goldens with DeepEval Synthesizer (uses the Azure judge model)."""
    from deepeval.synthesizer import Synthesizer

    from ..metrics.registry import judge_model

    synth = Synthesizer(model=judge_model())
    paths = [str(pdf_dir / d["file"]) for d in manifest]
    goldens = synth.generate_goldens_from_docs(
        document_paths=paths,
        include_expected_output=True,
        max_goldens_per_context=per_doc,
    )
    by_file = {d["file"]: d["doc_id"] for d in manifest}
    rows = []
    for i, g in enumerate(goldens, start=1):
        src = Path(getattr(g, "source_file", "") or "").name
        rows.append({
            "id": f"G-{i:04d}",
            "question": g.input,
            "expected_answer": g.expected_output,
            "source_doc_id": by_file.get(src, ""),
            "source_chunk_ids": [],        # match g.context back to kb_chunks if needed
            "context": g.context,          # used as HallucinationMetric context
            "question_type": "factual",
            "failure_mode": "PB-1",
            "reviewed": False,
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--per-doc", type=int, default=2)
    ap.add_argument("--skip-goldens", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(a.pdf_dir)
    (a.out / "kb_manifest.json").write_text(json.dumps(manifest, indent=2))
    with (a.out / "kb_chunks.jsonl").open("w") as f:
        for c in chunk_pdfs(a.pdf_dir, manifest):
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    if not a.skip_goldens:
        with (a.out / "goldens.jsonl").open("w") as f:
            for g in generate_goldens(a.pdf_dir, manifest, a.per_doc):
                f.write(json.dumps(g, ensure_ascii=False) + "\n")
    print(f"{len(manifest)} documents written to {a.out}")


if __name__ == "__main__":
    main()
