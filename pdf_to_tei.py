# pdf_to_tei.py
import os
import time
import logging
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf_to_tei")

GROBID_URL = "http://grobid:8070/api/processFulltextDocument"  # adjust if needed


def convert_pdf_to_tei(pdf_path: Path, tei_path: Path, sleep_between: float = 0.5):
    """
    Send a single PDF to GROBID and save TEI XML.
    """
    with pdf_path.open("rb") as f:
        files = {"input": (pdf_path.name, f, "application/pdf")}
        # params: see GROBID documentation for more options
        data = {
            "consolidateHeader": 1,
            "consolidateHeader": 1,
            "consolidateCitations": 1,
        }
        logger.info(f"Sending {pdf_path} to GROBID...")
        r = requests.post(GROBID_URL, files=files, data=data, timeout=120)

    if r.status_code != 200:
        raise RuntimeError(f"GROBID error ({r.status_code}) for {pdf_path}: {r.text[:500]}")

    tei_path.write_text(r.text, encoding="utf-8")
    logger.info(f"Saved TEI to {tei_path}")

    time.sleep(sleep_between)


def batch_pdf_to_tei(pdf_dir: str, tei_dir: str):
    pdf_dir = Path(pdf_dir)
    tei_dir = Path(tei_dir)
    tei_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(list(pdf_dir.glob("*.pdf")))

    logger.info(f"Found {len(pdf_files)} PDFs in {pdf_dir}")

    for pdf_path in pdf_files:
        tei_path = tei_dir / (pdf_path.stem + ".tei.xml")
        if tei_path.exists():
            logger.info(f"Skipping {pdf_path.name} (TEI already exists)")
            continue

        try:
            convert_pdf_to_tei(pdf_path, tei_path)
        except Exception as e:
            logger.error(f"Failed to process {pdf_path.name}: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert PDFs to TEI using GROBID")
    parser.add_argument("--pdf_dir", type=str, required=True, help="Directory with PDF files")
    parser.add_argument("--tei_dir", type=str, required=True, help="Output directory for TEI XML")
    args = parser.parse_args()

    batch_pdf_to_tei(args.pdf_dir, args.tei_dir)

# how to run:
# python pdf_to_tei.py --pdf_dir ./pdfs --tei_dir ./tei