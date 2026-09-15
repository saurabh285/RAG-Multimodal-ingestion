import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

MIN_DIMENSION_PX = 100
MAX_ASPECT_RATIO = 15
NOISE_CLASSES = {"logo", "icon", "qr_code", "bar_code", "stamp", "signature"}
NOISE_CLASS_CONFIDENCE = 0.6
MAX_DUPLICATE_OCCURRENCES = 2


@dataclass
class ExtractedImage:
    page_no: int
    image: object  # PIL.Image.Image


def extract_images(doc) -> list[ExtractedImage]:
    candidates = []
    for picture in doc.pictures:
        pil_image = picture.get_image(doc)
        if pil_image is None:
            continue
        if _is_small_or_thin(pil_image) or _is_classified_as_noise(picture):
            continue
        page_no = picture.prov[0].page_no if picture.prov else 1
        candidates.append(ExtractedImage(page_no=page_no, image=pil_image))

    return _drop_repeated_images(candidates)


def _is_small_or_thin(image) -> bool:
    width, height = image.size
    if width < MIN_DIMENSION_PX or height < MIN_DIMENSION_PX:
        return True
    aspect_ratio = max(width, height) / max(min(width, height), 1)
    return aspect_ratio > MAX_ASPECT_RATIO


def _is_classified_as_noise(picture) -> bool:
    for annotation in picture.annotations:
        predicted = getattr(annotation, "predicted_classes", None)
        if not predicted:
            continue
        top = predicted[0]
        if top.class_name in NOISE_CLASSES and top.confidence >= NOISE_CLASS_CONFIDENCE:
            return True
    return False


def _drop_repeated_images(images: list[ExtractedImage]) -> list[ExtractedImage]:
    hashes = [_hash_image(item.image) for item in images]
    counts = Counter(hashes)
    return [
        item
        for item, image_hash in zip(images, hashes)
        if counts[image_hash] <= MAX_DUPLICATE_OCCURRENCES
    ]


def _hash_image(image) -> str:
    thumbnail = image.convert("L").resize((16, 16))
    return hashlib.md5(thumbnail.tobytes()).hexdigest()


def save_images(
    document_id: int,
    images: list[ExtractedImage],
    base_dir: str = "data/images",
) -> list[tuple[int, str]]:
    out_dir = Path(base_dir) / str(document_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for index, extracted in enumerate(images):
        path = out_dir / f"image_{index}.png"
        extracted.image.save(path)
        saved.append((extracted.page_no, str(path)))
    return saved


def associate_images_to_chunks(chunks, saved_images: list[tuple[int, str]]) -> None:
    for page_no, path in saved_images:
        chunk = _find_chunk_for_page(chunks, page_no)
        chunk.image_paths.append(path)


def _find_chunk_for_page(chunks, page_no: int):
    for chunk in chunks:
        if chunk.page_start <= page_no <= chunk.page_end:
            return chunk
    return min(
        chunks,
        key=lambda c: min(abs(c.page_start - page_no), abs(c.page_end - page_no)),
    )
