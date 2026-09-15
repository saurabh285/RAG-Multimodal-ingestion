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

A full report in `knowledge/` is 300-700+ pages and takes **~30+ minutes** to
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

If you'd rather not run anything at all first, `samples/example_output/`
has a pre-generated example (`debug.html` + its images) already checked into
the repo, from a real run of this pipeline.

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
(that's covered separately, manually, given the ~30 min runtime), and no
test asserting exact chunk boundaries. It covers the logic most likely to
have silent bugs: filtering decisions and page/chunk matching.

Beyond the automated tests, I also verified the full pipeline by hand at
each build stage (text-only, then images, then the debug viewer) against
real reports, and end-to-end through Docker.

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

- **Ingestion is slow, on purpose.** A full report takes ~30+ minutes. This
  is dominated by Docling's table-structure model running in accurate mode
  (kept deliberately, since these reports are full of financial tables where
  fidelity matters more than speed) — not by OCR, which is disabled since
  these are digitally-produced PDFs with a real text layer already. A
  production version of this wouldn't run ingestion synchronously inside an
  HTTP request at all — it'd be a background job that returns a "processing"
  status immediately. That's out of scope here since the assessment asks for
  a direct synchronous response, but worth naming plainly.
  - **A GPU would help.** Docling's layout, table-structure, and picture
    classification models all run through PyTorch and support CUDA. On a
    machine with a real GPU (and Docker configured to pass it through), this
    runtime would drop meaningfully. I don't have that hardware available —
    developed this on an 8GB Apple Silicon Mac, and Docker Desktop's Linux VM
    doesn't have GPU passthrough to Apple's MPS backend at all, so the
    containerized app always runs on CPU regardless (confirmed in the logs:
    `Accelerator device: 'cpu'`). The code already requests
    `AcceleratorDevice.AUTO`, so it will pick up a CUDA GPU automatically if
    the reviewer's environment has one — no code change needed.
  - **Given the 5-6 hour assessment time budget and this compute
    constraint**, I validated the full pipeline end-to-end against one
    complete report (`report_2022.pdf`, 674 pages) rather than all four —
    running all four sequentially would be another 2-3 hours with no
    additional signal, since it's the same code path against similarly
    structured documents. That result is in this repo for verification (see
    below). I'd expect the other three to behave the same way.
  - **Memory matters too.** A full-report run pushed Docker's default memory
    allocation on this machine (3.8GB) into an OOM kill on the first attempt.
    I reduced `images_scale` and thread count to bring peak memory down, but
    if the reviewer's Docker has a similarly low memory limit, allocating at
    least ~4-6GB to Docker Desktop (Settings → Resources → Memory) is worth
    doing before ingesting a full report.
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
