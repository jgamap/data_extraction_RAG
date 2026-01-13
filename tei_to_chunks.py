# tei_to_chunks.py
#
# Section-aware hybrid chunking for scientific TEI (GROBID output).
#
# For each TEI file, this script:
#   - Extracts title, abstract, and structured body sections.
#   - Chunks text within each section using a word window.
#   - Returns chunks with rich metadata for RAG.
#
# Main entry point: tei_dir_to_chunks(tei_dir: str) -> List[Dict]

from pathlib import Path
from typing import List, Dict, Optional

from lxml import etree

# TEI namespace used by GROBID
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _elem_to_text(elem) -> str:
    """
    Safely convert an XML element to plain text by joining all text nodes.
    Returns an empty string if elem is None.
    """
    if elem is None:
        return ""
    text = " ".join(elem.itertext()).strip()
    return text


def _normalize_section_name(raw: Optional[str]) -> str:
    """
    Normalize section names to a small set of canonical labels where possible.
    This improves interpretability of metadata (e.g. "methods" vs "Methods").
    """
    if not raw:
        return "unlabeled"

    name = raw.strip().lower()

    # Common scientific section aliases
    if any(k in name for k in ["introduction", "background"]):
        return "introduction"
    if any(k in name for k in ["method", "materials", "patients and methods"]):
        return "methods"
    if any(k in name for k in ["result", "findings"]):
        return "results"
    if any(k in name for k in ["discussion", "interpretation"]):
        return "discussion"
    if any(k in name for k in ["conclusion", "concluding", "summary"]):
        return "conclusion"
    if "abstract" in name:
        return "abstract"

    # Fall back to cleaned raw
    return name


# -------------------------------------------------------------------
# Core TEI extraction
# -------------------------------------------------------------------

def extract_paper_structure_from_tei(tei_path: Path) -> Dict:
    """
    Parse a TEI file and extract:
      - paper_id (filename stem)
      - title
      - abstract (as a single string)
      - sections: list of {section_name, paragraphs: [str, ...]}
    """
    tree = etree.parse(str(tei_path))
    root = tree.getroot()

    # ---------- Title ----------
    title_elems = root.xpath("//tei:titleStmt/tei:title", namespaces=TEI_NS)
    if title_elems:
        title_text = _elem_to_text(title_elems[0])
        title = title_text if title_text else tei_path.stem
    else:
        title = tei_path.stem

    # ---------- Abstract ----------
    abstract_elems = root.xpath(
        "//tei:profileDesc//tei:abstract//tei:p",
        namespaces=TEI_NS,
    )
    if abstract_elems:
        abstract_paras = [_elem_to_text(p) for p in abstract_elems]
        abstract = "\n".join(p for p in abstract_paras if p)
    else:
        abstract = ""

    # ---------- Body sections ----------
    # GROBID typically structures body as <text><body><div type="...">...</div></body></text>
    div_sections = root.xpath(
        "//tei:text/tei:body//tei:div",
        namespaces=TEI_NS,
    )

    sections: List[Dict] = []

    if div_sections:
        # We have structured <div> sections
        for div in div_sections:
            # Candidate names:
            #   - @type attribute
            #   - <head> text
            sec_type = div.get("type")
            head_elems = div.xpath("./tei:head", namespaces=TEI_NS)
            head_text = _elem_to_text(head_elems[0]) if head_elems else ""

            raw_name = sec_type or head_text
            section_name = _normalize_section_name(raw_name)

            para_elems = div.xpath(".//tei:p", namespaces=TEI_NS)
            paragraphs: List[str] = []
            for p in para_elems:
                text = _elem_to_text(p)
                if text:
                    paragraphs.append(text)

            if paragraphs:
                sections.append(
                    {
                        "section_name": section_name,
                        "paragraphs": paragraphs,
                    }
                )
    else:
        # No <div> sections: fall back to all body paragraphs as a single "body" section
        body_paras = root.xpath(
            "//tei:text/tei:body//tei:p",
            namespaces=TEI_NS,
        )
        paragraphs: List[str] = []
        for p in body_paras:
            text = _elem_to_text(p)
            if text:
                paragraphs.append(text)

        if paragraphs:
            sections.append(
                {
                    "section_name": "body",
                    "paragraphs": paragraphs,
                }
            )

    return {
        "paper_id": tei_path.stem,
        "title": title,
        "abstract": abstract,
        "sections": sections,  # list of {section_name, paragraphs}
    }


# -------------------------------------------------------------------
# Chunking
# -------------------------------------------------------------------

def chunk_paragraphs(
    paragraphs: List[str],
    max_words: int = 280,
    overlap_words: int = 40,
) -> List[str]:
    """
    Word-based chunking across paragraphs.
    - max_words: approximate max words per chunk
    - overlap_words: words carried over between chunks for context
    """
    chunks: List[str] = []
    current_words: List[str] = []

    def flush():
        if current_words:
            chunks.append(" ".join(current_words).strip())

    for para in paragraphs:
        words = para.split()
        for w in words:
            current_words.append(w)
            if len(current_words) >= max_words:
                flush()
                # overlap for context
                current_words[:] = current_words[-overlap_words:]

    flush()
    return chunks


def build_chunks_from_paper(paper: Dict) -> List[Dict]:
    """
    Convert a parsed paper structure into chunk dicts suitable for RAG.

    Each chunk dict contains:
      - id
      - text
      - metadata: {
            paper_id,
            title,
            section,
            section_index,
            chunk_index_within_section
        }
    """
    paper_id = paper["paper_id"]
    title = paper["title"]

    all_chunks: List[Dict] = []

    # 1. Abstract as its own pseudo-section (if present)
    section_index = 0
    if paper["abstract"]:
        abstract_paragraphs = [paper["abstract"]]
        abstract_chunks = chunk_paragraphs(abstract_paragraphs)
        for j, ch_text in enumerate(abstract_chunks):
            all_chunks.append(
                {
                    "id": f"{paper_id}::sec_{section_index}::chunk_{j}",
                    "text": ch_text,
                    "metadata": {
                        "paper_id": paper_id,
                        "title": title,
                        "section": "abstract",
                        "section_index": section_index,
                        "chunk_index": j,
                    },
                }
            )
        section_index += 1

    # 2. Body sections
    for sec_idx, sec in enumerate(paper["sections"], start=section_index):
        section_name = sec["section_name"]
        paragraphs = sec["paragraphs"]

        if not paragraphs:
            continue

        sec_chunks = chunk_paragraphs(paragraphs)

        for j, ch_text in enumerate(sec_chunks):
            all_chunks.append(
                {
                    "id": f"{paper_id}::sec_{sec_idx}::chunk_{j}",
                    "text": ch_text,
                    "metadata": {
                        "paper_id": paper_id,
                        "title": title,
                        "section": section_name,
                        "section_index": sec_idx,
                        "chunk_index": j,
                    },
                }
            )

    return all_chunks


# -------------------------------------------------------------------
# Directory-level function
# -------------------------------------------------------------------

def tei_dir_to_chunks(tei_dir: str) -> List[Dict]:
    """
    Read all TEI files in a directory and return a list of chunk dicts
    suitable for RAG.

    Each dict has:
      - id: e.g. "paperid::sec_1::chunk_0"
      - text: chunk content
      - metadata: {
            paper_id,
            title,
            section,
            section_index,
            chunk_index
        }
    """
    tei_dir_path = Path(tei_dir)
    tei_files = sorted(list(tei_dir_path.glob("*.tei.xml")))

    all_chunks: List[Dict] = []

    print(f"Found {len(tei_files)} TEI files in {tei_dir_path}")

    for tei_path in tei_files:
        try:
            paper = extract_paper_structure_from_tei(tei_path)
        except Exception as e:
            print(f"[WARN] Skipping {tei_path.name} due to parse error: {e}")
            continue

        # Quick check: any content at all?
        has_abstract = bool(paper["abstract"].strip())
        has_sections = any(sec["paragraphs"] for sec in paper["sections"])

        if not has_abstract and not has_sections:
            print(f"[WARN] No text found in {tei_path.name}, skipping.")
            continue

        paper_chunks = build_chunks_from_paper(paper)
        all_chunks.extend(paper_chunks)

    return all_chunks


# -------------------------------------------------------------------
# Script entry point (for manual inspection)
# -------------------------------------------------------------------

if __name__ == "__main__":
    """
    Quick test runner:
    - Assumes TEI files are in ./tei
    - Prints how many chunks were created and shows a few examples
    """
    default_tei_dir = "./tei"
    chunks = tei_dir_to_chunks(default_tei_dir)

    print(f"\nExtracted {len(chunks)} chunks from TEI directory '{default_tei_dir}'")

    # Show first few chunks as a sanity check
    n_preview = min(3, len(chunks))
    for i in range(n_preview):
        ch = chunks[i]
        print("\n" + "=" * 70)
        print(f"Chunk {i}")
        print(f"ID:           {ch['id']}")
        print(f"Paper ID:     {ch['metadata']['paper_id']}")
        print(f"Title:        {ch['metadata']['title']}")
        print(f"Section:      {ch['metadata']['section']}")
        print(f"Sec index:    {ch['metadata']['section_index']}")
        print(f"Chunk index:  {ch['metadata']['chunk_index']}")
        print(f"Text (first 600 chars):\n{ch['text'][:600]}...")
