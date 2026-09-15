from pathlib import Path

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tiny.pdf"


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ingest_rejects_non_pdf(client):
    response = client.post(
        "/ingest",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"year": 2022},
    )

    assert response.status_code == 400


def test_ingest_rejects_invalid_year(client):
    with open(FIXTURE_PDF, "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("tiny.pdf", f, "application/pdf")},
            data={"year": 1500},
        )

    assert response.status_code == 422


def test_ingest_returns_expected_shape(client):
    with open(FIXTURE_PDF, "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("tiny.pdf", f, "application/pdf")},
            data={"year": 2022},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "tiny.pdf"
    assert body["year"] == 2022
    assert body["total_pages"] == 2
    assert body["chunk_count"] > 0
