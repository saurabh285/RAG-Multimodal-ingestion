# Discussion

## 1. Chunk size with multimodal chunks

If we only split chunks by token count, a page or section that's mostly
images (e.g. a photo spread or a chart-heavy page) can end up attached to
one chunk with way more images than the LLM can reasonably use at once. I
ran into a real example of this while building: a single chunk in one of
the test reports ended up with 8 images attached, just because that whole
page fell within one chunk's token budget.

I'd add a second, independent limit alongside the token budget: a max
number of images per chunk (something like 3-5, tunable). Whichever limit
gets hit first — tokens or image count — triggers a new chunk boundary.
That way an image-heavy section naturally spills into a couple of
sequential chunks (same page range, same parent section) instead of one
chunk carrying eight images. Since those chunks share the same page range,
retrieval and citation still make sense — you'd just get "page 42, part 1"
and "page 42, part 2" instead of one bloated chunk.

## 2. Image storage

I store cropped images as files on disk (`data/images/{document_id}/`) and
keep only the file path in the chunks table, not the image bytes. A few
reasons:

- Postgres isn't built to store large binary blobs efficiently — it bloats
  backups, replication, and write-ahead logs, and slows down ordinary
  queries against the same tables.
- Storing just a reference means swapping to S3 later is a backend change,
  not a schema change — the column still just holds a string.

Since we're told we'll always have the original PDFs, there's a leaner
option worth mentioning: don't persist cropped images at all, just store
`(document_id, page_number, bounding_box)` and re-crop from the source PDF
on demand when a chunk's image is actually needed. That cuts storage close
to zero, at the cost of a small re-render step at read time and needing the
original PDFs to stay available indefinitely. For this project I still
persist actual image files, mainly because the debug viewer needs to show
images immediately without re-opening PDFs — but for a larger production
system, I'd seriously consider the bbox-only approach, especially if
storage cost or PDF volume grows a lot.

## 3. ColPali-style approaches

ColPali is appealing because it sidesteps the whole "did the parser get the
layout/table/image right" problem — it treats the page as an image and
lets a vision-language model figure out what matters. For pages that are
mostly charts, infographics, or complex multi-column layouts, that's a real
advantage: no OCR errors, no split-mid-table bugs, no missed image.

That said, for URDs specifically, I wouldn't replace the parsing pipeline
with it outright:

- Most of the value in these reports is in the actual text — financial
  figures, disclosures, strategy language — which a good text parser
  extracts cleanly and relatively cheaply. ColPali's per-page multi-vector
  embeddings are more expensive to compute and store than one dense vector
  per text chunk, for content that doesn't need visual understanding.
- Provenance gets fuzzier. With chunk-based retrieval I can say "this
  answer comes from page 42, paragraph 3." With page-level late
  interaction, you get "this answer comes from page 42" — coarser, and
  harder to point someone at the exact sentence or table.
- It's a newer approach with less mature production tooling than the
  standard parse → chunk → embed pipeline, and (as I found out first-hand
  building this) even the "simpler" parse-based pipeline is already
  computationally heavy on a document this dense — a full page-image VLM
  pass over a 600+ page report would be a significant cost multiplier on
  top of that.

My take: keep the current pipeline as the main path, since most of a URD is
well-structured text. But I'd consider a ColPali-style index as a
*secondary*, specialized retrieval path just for pages that are
chart/infographic-heavy — flag those pages during ingestion (e.g. high
image-to-text ratio, or using the same picture classifier already in this
pipeline to detect chart-dense pages) and route them to a page-image index
instead of, or in addition to, normal chunking.

On the compute point specifically: everything above assumes GPU-backed
inference is available. I developed this on an 8GB Mac with no dedicated
GPU, and a full report already takes ~30+ minutes on CPU with the current
(comparatively lighter) pipeline — a ColPali-style approach, which runs a
VLM over every page image, would be considerably more expensive still on
the same hardware. See the README's "Known limitations" section for how
that constraint shaped what I could actually validate here.

To make the "would a lighter approach work?" question concrete rather
than hypothetical, I built a throwaway comparison pipeline
(`experiments/lightweight_pipeline.py`) using plain PyMuPDF text/image
extraction instead of Docling — no ML at all. On the full `report_2022.pdf`:
6.2 seconds versus Docling's 30+ minutes (and inability to finish on this
machine). The cost is real too — chunking is cruder (no structure
awareness) and at least one clearly non-useful image (a flat gradient
background) got kept, since there's no classifier to catch it. That's the
ColPali trade-off in miniature: strip out the ML, get speed, lose the
judgment calls the ML was making.
