"""Throwaway comparison script - NOT part of the delivered app.

Runs a lightweight, non-ML ingestion pass (PyMuPDF text + embedded image
extraction) over one full report, reusing the same noise-filter/dedup/
association/debug-viewer code from app/ so the output is directly
comparable to a Docling-based debug HTML.

Usage:
    pip install -r requirements-dev.txt
    python experiments/lightweight_pipeline.py knowledge/report_2022.pdf
"""
import io
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import debug_view
from app.images import (
    ExtractedImage,
    _drop_repeated_images,
    _is_small_or_thin,
    associate_images_to_chunks,
    save_images,
)

CHUNK_CHAR_LIMIT = 2000


@dataclass
class LightweightChunk:
    id: int
    text: str
    page_start: int
    page_end: int
    image_paths: list = field(default_factory=list)


def chunk_by_char_count(doc) -> list[LightweightChunk]:
    chunks = []
    buffer = ""
    page_start = 1
    next_id = 1

    for page_index in range(doc.page_count):
        page_no = page_index + 1
        buffer += doc[page_index].get_text()
        if len(buffer) >= CHUNK_CHAR_LIMIT:
            chunks.append(
                LightweightChunk(
                    id=next_id, text=buffer, page_start=page_start, page_end=page_no
                )
            )
            next_id += 1
            buffer = ""
            page_start = page_no + 1

    if buffer.strip():
        chunks.append(
            LightweightChunk(
                id=next_id,
                text=buffer,
                page_start=page_start,
                page_end=doc.page_count,
            )
        )

    return chunks


def extract_images(doc) -> list[ExtractedImage]:
    candidates = []
    for page_index in range(doc.page_count):
        page_no = page_index + 1
        for img in doc[page_index].get_images(full=True):
            xref = img[0]
            try:
                base = doc.extract_image(xref)
                pil_image = Image.open(io.BytesIO(base["image"])).convert("RGB")
            except Exception:
                continue
            if _is_small_or_thin(pil_image):
                continue
            candidates.append(ExtractedImage(page_no=page_no, image=pil_image))
    return _drop_repeated_images(candidates)


def main(pdf_path: str):
    start = time.time()
    doc = fitz.open(pdf_path)

    chunks = chunk_by_char_count(doc)
    images = extract_images(doc)
    saved = save_images(
        document_id="lightweight_" + Path(pdf_path).stem,
        images=images,
        base_dir="data/images",
    )
    associate_images_to_chunks(chunks, saved)

    elapsed = time.time() - start
    debug_path = debug_view.render_debug_html(
        document_id="lightweight_" + Path(pdf_path).stem,
        filename=Path(pdf_path).name,
        chunks=chunks,
    )

    print(f"pages={doc.page_count} chunks={len(chunks)} images_kept={len(images)}")
    print(f"elapsed={elapsed:.1f}s")
    print(f"debug html: {debug_path}")


if __name__ == "__main__":
    main(sys.argv[1])
