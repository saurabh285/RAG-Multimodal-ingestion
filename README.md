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

The numbers above are real (from parsing `report_2022.pdf`), but see "Memory
is the real wall on this machine" under **Known limitations** — I could not
get the full multimodal pipeline to complete end-to-end on a full report
within this machine's available memory, only the text-only parsing stage.

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
  - **There are also non-GPU ways to speed this up, each with a real cost:**
    - Switch Docling's table model to "fast" mode instead of "accurate" —
      meaningfully quicker, but weaker table structure on exactly the
      financial tables this document type is full of. I chose not to make
      this trade for a URD.
    - Use a lighter parser (e.g. plain PyMuPDF/pypdf text extraction)
      instead of Docling — very fast, but loses table structure entirely
      (rows/columns collapse into flat text) and loses the clean image
      bounding boxes Step 2 depends on. This is the trade-off discussed in
      more detail earlier in the project.
    - Sample a subset of pages instead of the full document — fast, but
      it's no longer a real validation of the whole report, just a spot
      check.
    None of these were applied to the actual pipeline; they're noted here
    as known, deliberately-declined options, not hidden gaps.
  - **Memory is the real wall on this machine, not just time.** A full
    674-page report pushed Docker's default memory allocation here (3.8GB)
    into an OOM kill. I reduced `images_scale` (2.0→1.0) and thread count
    (8→4) to lower peak memory, which helped meaningfully — the retry got
    ~18 minutes in (vs. ~3 minutes before) with no errors — but it still
    hit the ceiling eventually, because Docling appears to hold data for
    every processed page in memory for the whole document rather than
    releasing it as it goes, and this report is long enough that it adds up
    regardless of per-page tuning. I did **not** get a full report to
    complete end-to-end inside this machine's Docker limit. Text-only
    parsing of a full report (no images/classifier) did complete earlier,
    natively outside Docker, in ~33 minutes — so the parsing/chunking logic
    itself is proven correct at full scale; it's specifically the combined
    memory cost of images + picture classification over 600+ pages that
    doesn't fit in 3.8GB. If the reviewer's Docker has more headroom (I'd
    guess ~6GB+), a full report should go through fine.
  - **I also tried a genuinely lightweight alternative, to see the trade-off
    for real rather than guess at it:** plain PyMuPDF text extraction (no
    layout model, no ML at all) processed all 4 full reports in **~18
    seconds combined** (vs. 30+ minutes each for Docling) at **~110MB peak
    memory** (vs. multiple GB). That confirms Docling's cost is real and
    specific to its ML pipeline, not an inefficiency in this code. But the
    quality drop is concrete, not theoretical — raw PyMuPDF text from the
    same table-of-contents page that Docling (imperfectly) associates as
    `"1.1, 1 = TotalEnergies at a glance..."` comes out as three disconnected
    blocks of numbers, titles, and page numbers with no way to tell which
    belongs to which, since PyMuPDF has no concept of table structure at
    all. I kept Docling as the actual pipeline because that structure
    matters for a document this table-heavy — but on this hardware, that
    choice comes at a real, hit-the-ceiling cost, and I'd rather say that
    plainly than imply the full pipeline was validated at full scale when
    it wasn't.
  - **I went further and built a full lightweight pipeline** (text +
    images + debug HTML, not just raw text) —
    [`experiments/lightweight_pipeline.py`](experiments/lightweight_pipeline.py),
    reusing this project's actual noise-filter/dedup/association/debug-viewer
    code so the comparison is fair. Run against the full `report_2022.pdf`
    (674 pages): **6.2 seconds**, 594 chunks, 76 images kept — versus
    Docling's 30+ minutes and inability to finish at all on this machine.
    Chunk quality is visibly cruder (fixed character-count splitting, no
    heading/structure awareness, so chunks span pages irregularly). Image
    quality is mixed: real photos extracted fine, but with no ML classifier
    available, a plain gradient background swatch got kept as an "image"
    where Docling's classifier would drop it. This isn't a hidden
    fallback — it's a documented experiment, not part of the delivered app.
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
