from PIL import Image

from app.images import (
    ExtractedImage,
    _drop_repeated_images,
    _find_chunk_for_page,
    _is_small_or_thin,
)
from app.parser import ParsedChunk


def test_small_image_is_filtered():
    assert _is_small_or_thin(Image.new("RGB", (50, 50))) is True


def test_thin_image_is_filtered():
    assert _is_small_or_thin(Image.new("RGB", (400, 10))) is True


def test_normal_image_is_kept():
    assert _is_small_or_thin(Image.new("RGB", (400, 300))) is False


def test_repeated_images_are_dropped_but_unique_ones_kept():
    repeated = Image.new("RGB", (300, 300), color="red")
    unique = Image.new("RGB", (300, 300), color="blue")
    images = [
        ExtractedImage(page_no=1, image=repeated),
        ExtractedImage(page_no=2, image=repeated),
        ExtractedImage(page_no=3, image=repeated),
        ExtractedImage(page_no=4, image=unique),
    ]

    kept = _drop_repeated_images(images)

    assert len(kept) == 1
    assert kept[0].page_no == 4


def test_find_chunk_for_page_exact_match():
    chunks = [
        ParsedChunk(text="a", page_start=1, page_end=2),
        ParsedChunk(text="b", page_start=3, page_end=5),
    ]

    assert _find_chunk_for_page(chunks, 4) is chunks[1]


def test_find_chunk_for_page_falls_back_to_nearest():
    chunks = [
        ParsedChunk(text="a", page_start=1, page_end=2),
        ParsedChunk(text="b", page_start=10, page_end=12),
    ]

    assert _find_chunk_for_page(chunks, 7) is chunks[1]
