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
ingest (see "Why ingestion is slow" below) — not something you want to wait
on just to check the app works. Use the small 15-page sample instead:

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

There's no automated test suite. Given the scope of this assessment, I
tested by ingesting reports through `/docs` and checking the DB rows and the
debug HTML by hand at each stage (text-only, then images, then the viewer),
plus a full end-to-end run through Docker. That was a deliberate choice
given the time budget, not an oversight — happy to add pytest coverage if
that's expected.

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
