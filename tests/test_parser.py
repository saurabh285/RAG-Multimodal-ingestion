from types import SimpleNamespace

from app.parser import _pages_for_chunk


def _fake_chunk(page_numbers):
    doc_items = [
        SimpleNamespace(prov=[SimpleNamespace(page_no=n) for n in group])
        for group in page_numbers
    ]
    return SimpleNamespace(meta=SimpleNamespace(doc_items=doc_items))


def test_pages_for_chunk_collects_unique_sorted_pages():
    chunk = _fake_chunk([[3], [1, 1]])

    assert _pages_for_chunk(chunk) == [1, 3]


def test_pages_for_chunk_defaults_to_page_one_when_empty():
    chunk = _fake_chunk([])

    assert _pages_for_chunk(chunk) == [1]
