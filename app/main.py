import shutil
import tempfile

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Chunk, Document
from app import images, parser

app = FastAPI(title="MultiModal RAG Ingestion")

Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest")
def ingest(
    file: UploadFile = File(...),
    year: int = Form(...),
    db: Session = Depends(get_db),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="File must be a PDF")

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp.flush()

        try:
            doc = parser.convert(tmp.name)
            parsed_chunks = parser.build_chunks(doc)
            extracted_images = images.extract_images(doc)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to parse PDF: {exc}"
            )

    document = Document(
        filename=file.filename, year=year, total_pages=doc.num_pages()
    )
    db.add(document)
    db.flush()

    saved_images = images.save_images(document.id, extracted_images)
    images.associate_images_to_chunks(parsed_chunks, saved_images)

    for chunk in parsed_chunks:
        db.add(
            Chunk(
                document_id=document.id,
                text=chunk.text,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                image_paths=chunk.image_paths,
            )
        )

    db.commit()

    return {
        "document_id": document.id,
        "filename": document.filename,
        "year": document.year,
        "total_pages": document.total_pages,
        "chunk_count": len(parsed_chunks),
    }
