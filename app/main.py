from fastapi import FastAPI

from app import models  # noqa: F401 (registers tables on Base.metadata)
from app.database import Base, engine

app = FastAPI(title="MultiModal RAG Ingestion")

Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}
