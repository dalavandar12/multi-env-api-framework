"""Local document → plain text.

Supports .txt, .md, .docx, .pdf. Returns text to stdout. Caller (Claude) is
responsible for converting that text into the endpoint dict shape via an
LLM extraction step — see SKILL.md section "Normalize".
"""
import logging
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)


def _read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_md(path: Path) -> str:
    import markdown
    from bs4 import BeautifulSoup
    html = markdown.markdown(path.read_text(encoding="utf-8", errors="replace"))
    return str(BeautifulSoup(html, "html.parser").get_text("\n"))


def _read_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


_READERS = {
    ".txt": _read_txt,
    ".md": _read_md,
    ".markdown": _read_md,
    ".docx": _read_docx,
    ".pdf": _read_pdf,
}


def read(path: Path) -> str:
    suffix = path.suffix.lower()
    reader = _READERS.get(suffix)
    if reader is None:
        print(f"[parse_document] unsupported extension: {suffix}", file=sys.stderr)
        sys.exit(2)
    return reader(path)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: parse_document.py <path>", file=sys.stderr)
        sys.exit(64)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"[parse_document] not found: {path}", file=sys.stderr)
        sys.exit(2)
    sys.stdout.write(read(path))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
