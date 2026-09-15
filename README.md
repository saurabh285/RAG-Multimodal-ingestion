# MultiModal RAG Ingestion

A FastAPI service that ingests TotalEnergies Universal Registration Documents
(PDFs), splits them into chunks of text and images, and stores everything in
Postgres so it's ready for a RAG pipeline later.

## Stack

- **FastAPI** for the API
- **Docling** for PDF parsing — layout-aware, handles the dense tables and
  images in these reports much better than plain text extraction
- **Docling's HybridChunker** for chunking — respects a token budget while
  staying structure-aware (won't split mid-table or mid-section)
- **Docling's picture classifier** + a duplicate-image check, to filter out
  logos/icons/QR codes and repeated headers before they become chunk images
- **PostgreSQL** + **SQLAlchemy** for storage
- **Jinja2** for the debug HTML viewer
- **Docker Compose** to run the whole thing (API + Postgres) with one command

## Running it

```bash
docker compose up --build
```

The API is then available at `http://localhost:8000`. Interactive docs (and
the easiest way to try it) are at `http://localhost:8000/docs`.

### Quick sanity check (recommended first)

A full report in `knowledge/` is 660-680 pages and takes **~30+ minutes** to
ingest (see "Known limitations" below) — not something you want to wait on
just to check the app works. Use the small 15-page sample instead:

```bash
curl -X POST http://localhost:8000/ingest \
  -F "file=@samples/sample_report.pdf" \
  -F "year=2022" \
  -F "debug=true"
```

Takes well under a minute and exercises the full pipeline — text, images,
and the debug viewer.

If you'd rather not run anything at all first, two pre-generated examples
are already checked into the repo — open either directly in a browser:

- **`samples/example_output/debug.html`** — this project's actual delivered
  pipeline (Docling), run on the 15-page sample.
- **`samples/example_output_lightweight/debug.html`** — the lightweight
  comparison pipeline (see "Known limitations" below), run on the full
  674-page `report_2022.pdf`. Not the delivered approach, included so you
  can see the speed/quality trade-off directly instead of just reading
  about it.

### Ingesting a full report

```bash
curl -X POST http://localhost:8000/ingest \
  -F "file=@knowledge/report_2022.pdf" \
  -F "year=2022" \
  -F "debug=true"
```

Returns something like:

```json
{
  "document_id": 1,
  "filename": "report_2022.pdf",
  "year": 2022,
  "total_pages": 674,
  "chunk_count": 3435
}
```

With `debug=true`, a file is also written to `data/debug/{document_id}.html`
— open it in a browser to see every chunk with its page numbers and any
images attached to it.

The numbers above are real (from parsing `report_2022.pdf`) — but see
**Known limitations** for what actually completed end-to-end vs. what
didn't on this machine.

## Database schema

**documents**
| column | type |
|---|---|
| id | int, pk |
| filename | text |
| year | int |
| total_pages | int |

**chunks**
| column | type |
|---|---|
| id | int, pk |
| document_id | int, fk → documents.id |
| text | text |
| page_start | int |
| page_end | int |
| image_paths | json (list of file paths) |

Images are saved as PNG files under `data/images/{document_id}/`; the
database only holds the paths, not the image bytes. Keeps the database
light and makes swapping in S3 later a backend change, not a schema change
(see `Discussion.md`).

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

Runs unit tests for the image noise/duplicate filtering and page-to-chunk
association logic, plus an endpoint smoke test (health check, PDF-type
rejection, year-range validation, and a real ingest against a tiny 2-page
fixture). Tests use an isolated SQLite file, not the real Postgres database,
so they don't need Docker running.

This isn't exhaustive coverage — there's no test against a full real report
(see **Known limitations** for how far that actually got), and no test
asserting exact chunk boundaries. It covers the logic most likely to have
silent bugs: filtering decisions and page/chunk matching.

Beyond the automated tests, I also verified each build stage by hand
(text-only, then images, then the debug viewer) against real reports, and
end-to-end through Docker.

## Error handling & observability

- If image extraction fails partway through, ingestion still completes with
  text-only chunks rather than failing the whole request — a parsing
  problem with pictures shouldn't lose the text that already parsed fine.
  A single bad image (e.g. a disk write failure) is skipped the same way,
  logged, and doesn't take down the rest of the batch.
- `year` is validated to a sane range (1900-2100) and there's a max upload
  size, so obviously bad input is rejected with a 400/422 instead of being
  silently accepted or crashing deep in the pipeline.
- The app logs progress (pages parsed, chunk count, images kept vs.
  filtered) and logs full tracebacks on failure via Python's `logging`
  module, rather than only surfacing a bare error string to the client.

## Known limitations

- **Ingestion is slow, on purpose.** A full report takes ~30+ minutes,
  dominated by Docling's table-structure model in accurate mode (kept
  deliberately — these reports are full of financial tables where fidelity
  matters more than speed). OCR is off, since these PDFs already have a
  real text layer. A production system would run this as a background job,
  not inside a synchronous HTTP request — out of scope here since the
  assessment asks for a direct response.
- **No GPU available while building this** (8GB Mac, no CUDA; Docker
  Desktop's VM doesn't expose Apple's GPU either, so it ran on CPU). The
  code requests `AcceleratorDevice.AUTO`, so it'll use a GPU automatically
  if the reviewer's machine has one.
- **A full report didn't fit in this machine's Docker memory limit
  (3.8GB)** — it OOM-killed even after I lowered image resolution and
  thread count to reduce peak memory. Text-only parsing of a full report
  did complete separately (~33 min, outside Docker), so the pipeline logic
  is correct at full scale; it's specifically images + picture
  classification over 600+ pages that needs more memory than this machine's
  Docker had. ~6GB+ should be enough on a reviewer's machine.
- **For comparison, I also built a lightweight, non-ML version**
  ([`experiments/lightweight_pipeline.py`](experiments/lightweight_pipeline.py),
  PyMuPDF instead of Docling) and ran it on the same full report: 6 seconds
  vs. 30+ minutes, but cruder chunking and weaker image filtering (no
  classifier). Real output from both is checked in for a direct look:
  `samples/example_output/` (Docling, delivered) and
  `samples/example_output_lightweight/` (comparison only). Docling stays
  the actual pipeline — table fidelity matters more here than speed.
- **Logo filtering is a heuristic, not perfect.** Repeated logos (headers,
  footers, cover branding used many times) are reliably caught by a
  duplicate-image check. A one-off logo that only appears once in the whole
  document can occasionally slip through the classifier if it's styled more
  like editorial content (e.g. a vintage/historical logo illustration) than
  a plain brand mark.
- **Table-to-text serialization can look rough.** Dense navigation tables
  (like a table of contents) sometimes come out as a flattened
  `"field = value"` sequence rather than a clean two-column layout. The
  underlying data is accurate, just not visually laid out like the original
  table.
- **Docker on a slim base image needs a couple of extra system packages**
  that aren't obvious from Docling's own docs — `libgl1`/`libglib2.0-0`
  (OpenCV, a Docling dependency) and `g++` (needed by one of Torch's
  internal CPU checks). Both are already in the `Dockerfile`; noting them
  here in case a future dependency bump reintroduces a similar gap.
