from dataclasses import dataclass, field

from docling.chunking import HybridChunker
from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    PdfPipelineOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat

_chunker = HybridChunker(max_tokens=512)


@dataclass
class ParsedChunk:
    text: str
    page_start: int
    page_end: int
    image_paths: list[str] = field(default_factory=list)


def convert(pdf_path: str):
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.images_scale = 1.0
    pipeline_options.generate_picture_images = True
    pipeline_options.do_picture_classification = True
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=4, device=AcceleratorDevice.AUTO
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    result = converter.convert(pdf_path)
    return result.document


def build_chunks(doc) -> list[ParsedChunk]:
    parsed_chunks = []
    for chunk in _chunker.chunk(doc):
        pages = _pages_for_chunk(chunk)
        parsed_chunks.append(
            ParsedChunk(
                text=_chunker.contextualize(chunk),
                page_start=min(pages),
                page_end=max(pages),
            )
        )
    return parsed_chunks


def _pages_for_chunk(chunk) -> list[int]:
    pages = set()
    for item in chunk.meta.doc_items:
        for prov in item.prov:
            pages.add(prov.page_no)
    return sorted(pages) or [1]


if __name__ == "__main__":
    import sys

    document = convert(sys.argv[1])
    chunks = build_chunks(document)
    print(f"total_pages={document.num_pages()} chunk_count={len(chunks)}")
    print(chunks[0])
