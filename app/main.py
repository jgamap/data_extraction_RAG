from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path
import shutil
import time

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse


# Reuse your existing RAG function (no code duplication)
from query_rag import answer_query_with_context

# Reuse your ingestion pipeline steps
from pdf_to_tei import convert_pdf_to_tei
from tei_to_chunks import tei_dir_to_chunks
from build_rag_index import build_chroma_collection


app = FastAPI(title="RAG Web UI")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class Message(BaseModel):
    role: str = Field(..., description="chat role, e.g. 'user' or 'assistant'")
    content: str = Field(..., description="message content")


class AskRequest(BaseModel):
    message: str
    history: List[Message] = Field(default_factory=list)
    persist_dir: str = "./rag_db"
    collection_name: str = "papers"
    k: int = 4
    return_context: bool = True


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/ask", response_class=JSONResponse)
def ask(payload: AskRequest):
    try:
        answer, contexts = answer_query_with_context(
            query=payload.message,
            persist_dir=payload.persist_dir,
            collection_name=payload.collection_name,
            k=payload.k,
        )

        # Ensure answer is a plain string (guards against SDK objects like Message)
        if not isinstance(answer, str):
            if hasattr(answer, "content"):
                answer = answer.content
            else:
                answer = str(answer)

        # Maintain chat history for the frontend (your backend doesn't manage it)
        history_in = payload.history or []
        new_history = history_in + [
            {"role": "user", "content": payload.message},
            {"role": "assistant", "content": answer, "contexts": contexts if payload.return_context else []},
        ]

        response_payload = {
            "answer": answer,
            "contexts": contexts if payload.return_context else [],
            "history": new_history,
        }

        # Make sure everything is JSON serializable
        return JSONResponse(content=jsonable_encoder(response_payload))

    except Exception as e:
        # Optional: surface a readable error to the UI without leaking internals
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/index", response_class=JSONResponse)
def index_pdfs(
    files: List[UploadFile] = File(..., description="One or more PDF files"),
    persist_dir: str = Form("./rag_db"),
    collection_name: str = Form("papers"),
):
    """Upload PDFs and run: PDF -> TEI -> chunks -> Chroma index.

    This is intentionally synchronous for simplicity. For large batches,
    consider moving the work to a background worker (Celery/RQ) and polling status.
    """
    if not files:
        return JSONResponse({"ok": False, "error": "No files received."}, status_code=400)

    # Create an isolated ingestion workspace
    ts = time.strftime("%Y%m%d-%H%M%S")
    ingest_root = Path("./ingest_runs") / ts
    pdf_dir = ingest_root / "pdfs"
    tei_dir = ingest_root / "tei"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    tei_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    errors = []

    for f in files:
        filename = (f.filename or "").strip()
        if not filename.lower().endswith(".pdf"):
            errors.append({"file": filename or "<unknown>", "error": "Not a .pdf file"})
            continue

        safe_name = Path(filename).name  # basic sanitization
        pdf_path = pdf_dir / safe_name
        try:
            with pdf_path.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            saved.append(str(pdf_path))
        except Exception as e:
            errors.append({"file": filename, "error": f"Failed to save upload: {e}"})
            continue

    if not saved:
        return JSONResponse({"ok": False, "error": "No valid PDFs to process.", "errors": errors}, status_code=400)

    # Convert each PDF to TEI
    converted = 0
    for pdf_path_str in saved:
        pdf_path = Path(pdf_path_str)
        tei_path = tei_dir / (pdf_path.stem + ".tei.xml")
        try:
            convert_pdf_to_tei(pdf_path=pdf_path, tei_path=tei_path)
            converted += 1
        except Exception as e:
            errors.append({"file": pdf_path.name, "error": f"PDF->TEI failed: {e}"})

    # Chunk TEI and build index
    try:
        chunks = tei_dir_to_chunks(str(tei_dir))
        if not chunks:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "No chunks were extracted from TEI. Check GROBID output and TEI parsing.",
                    "converted": converted,
                    "errors": errors,
                },
                status_code=500,
            )
        build_chroma_collection(chunks, persist_dir=persist_dir, collection_name=collection_name)
    except Exception as e:
        return JSONResponse(
            {
                "ok": False,
                "error": f"Indexing failed: {e}",
                "converted": converted,
                "errors": errors,
            },
            status_code=500,
        )

    return JSONResponse(
        {
            "ok": True,
            "ingest_run": ts,
            "pdfs_saved": len(saved),
            "pdfs_converted": converted,
            "chunks_indexed": len(chunks),
            "persist_dir": persist_dir,
            "collection_name": collection_name,
            "errors": errors,
        }
    )
