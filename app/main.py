import logging
import shutil
import tempfile
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Chunk, Document
from app import debug_view, images, parser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 300 * 1024 * 1024


class IngestResponse(BaseModel):
    document_id: int
    filename: str
    year: int
    total_pages: int
    chunk_count: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="MultiModal RAG Ingestion", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse)
def ingest(
    file: UploadFile = File(...),
    year: int = Form(..., ge=1900, le=2100),
    debug: bool = Form(False),
    db: Session = Depends(get_db),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="File must be a PDF")

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp.flush()

        if tmp.tell() > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File too large")

        logger.info("Ingest starting: filename=%s year=%s", file.filename, year)

        try:
            doc = parser.convert(tmp.name)
            parsed_chunks = parser.build_chunks(doc)
        except Exception:
            logger.exception("Failed to parse %s", file.filename)
            raise HTTPException(status_code=500, detail="Failed to parse PDF")

        logger.info(
            "Parsed %d pages into %d chunks", doc.num_pages(), len(parsed_chunks)
        )

        try:
            extracted_images = images.extract_images(doc)
        except Exception:
            logger.exception(
                "Image extraction failed for %s, continuing with text-only chunks",
                file.filename,
            )
            extracted_images = []

    document = Document(
        filename=file.filename, year=year, total_pages=doc.num_pages()
    )
    db.add(document)
    db.flush()

    saved_images = images.save_images(document.id, extracted_images)
    images.associate_images_to_chunks(parsed_chunks, saved_images)

    chunk_rows = []
    for chunk in parsed_chunks:
        row = Chunk(
            document_id=document.id,
            text=chunk.text,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            image_paths=chunk.image_paths,
        )
        db.add(row)
        chunk_rows.append(row)

    db.commit()

    if debug:
        for row in chunk_rows:
            db.refresh(row)
        debug_view.render_debug_html(document.id, document.filename, chunk_rows)

    logger.info(
        "Ingest complete: document_id=%d filename=%s chunks=%d images_saved=%d",
        document.id,
        document.filename,
        len(parsed_chunks),
        len(saved_images),
    )

    return IngestResponse(
        document_id=document.id,
        filename=document.filename,
        year=document.year,
        total_pages=document.total_pages,
        chunk_count=len(parsed_chunks),
    )
