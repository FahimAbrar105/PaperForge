"""Step 1 - Upload Handler: validate uploads and store them in the job workspace.

Files are only ever read as data. Nothing uploaded is executed.
"""

from __future__ import annotations

import hashlib
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

from app.config import Settings
from app.models.job import UploadedFile
from app.services.workspace import JobWorkspace, sanitize_filename

# PDF papers are not accepted as manuscripts (their structure cannot be recovered
# reliably); a .pdf upload is always treated as a figure.
MANUSCRIPT_EXT = {".tex", ".md", ".markdown", ".docx"}
BIB_EXT = {".bib"}
FIGURE_EXT = {".png", ".jpg", ".jpeg", ".eps", ".svg", ".pdf"}
ALLOWED_EXT = MANUSCRIPT_EXT | BIB_EXT | FIGURE_EXT
TEXT_EXT = {".tex", ".md", ".markdown", ".bib", ".svg"}

# Declared MIME types browsers commonly send for each extension. Browsers are
# inconsistent, so the content signature check below is the real gate.
ACCEPTED_MIME = {
    ".tex": {"text/x-tex", "application/x-tex", "text/plain", "application/octet-stream", "text/x-latex", "application/x-latex", ""},
    ".md": {"text/markdown", "text/x-markdown", "text/plain", "application/octet-stream", ""},
    ".markdown": {"text/markdown", "text/x-markdown", "text/plain", "application/octet-stream", ""},
    ".bib": {"text/x-bibtex", "application/x-bibtex", "text/plain", "application/octet-stream", "text/x-bibtex-text-file", ""},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip", "application/octet-stream", ""},
    ".pdf": {"application/pdf", "application/x-pdf", "application/octet-stream", ""},
    ".png": {"image/png", "application/octet-stream", ""},
    ".jpg": {"image/jpeg", "image/pjpeg", "application/octet-stream", ""},
    ".jpeg": {"image/jpeg", "image/pjpeg", "application/octet-stream", ""},
    ".eps": {"application/postscript", "image/x-eps", "application/eps", "image/eps", "application/octet-stream", ""},
    ".svg": {"image/svg+xml", "text/xml", "application/xml", "text/plain", "application/octet-stream", ""},
}


# Binary formats: (name for messages, byte strings a valid file starts with).
SIGNATURES = {
    ".pdf": ("PDF file", (b"%PDF-",)),
    ".png": ("PNG image", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("JPEG image", (b"\xff\xd8\xff",)),
    ".jpeg": ("JPEG image", (b"\xff\xd8\xff",)),
    ".eps": ("EPS file", (b"%!PS", b"\xc5\xd0\xd3\xc6")),
    ".docx": ("DOCX file", (b"PK\x03\x04",)),
}


class UploadError(ValueError):
    pass


@dataclass
class IncomingFile:
    filename: str
    content_type: str
    stream: BinaryIO


def new_job_id() -> str:
    return uuid.uuid4().hex


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        # A multi-byte character may be cut at the end of the sample.
        if exc.start >= len(head) - 4:
            return True
        try:
            head.decode("cp1252")
            return True
        except UnicodeDecodeError:
            return False


def verify_signature(path: Path, ext: str) -> None:
    """Check file content matches its extension (magic bytes / structure)."""
    with path.open("rb") as fh:
        head = fh.read(8192)
    if ext in TEXT_EXT:
        if not _looks_like_text(head):
            raise UploadError(f"{path.name}: expected a text file but found binary content")
        if ext == ".svg" and b"<svg" not in head.lower() and b"<?xml" not in head.lower():
            raise UploadError(f"{path.name}: not a valid SVG image")
        return
    if ext not in SIGNATURES:
        raise UploadError(f"{path.name}: unsupported file type")
    name, starts = SIGNATURES[ext]
    if ext == ".pdf":
        head = head.lstrip()  # PDF readers accept whitespace before the header
    if not head.startswith(starts):
        raise UploadError(f"{path.name}: not a valid {name}")
    if ext == ".docx":
        _verify_docx(path)


def _verify_docx(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            if "word/document.xml" not in zf.namelist():
                raise UploadError(f"{path.name}: DOCX is missing word/document.xml")
            if sum(i.file_size for i in zf.infolist()) > 500 * 1024 * 1024:
                raise UploadError(f"{path.name}: DOCX expands to an unreasonable size")
    except zipfile.BadZipFile as exc:
        raise UploadError(f"{path.name}: corrupt DOCX file") from exc


def file_kind(ext: str) -> str:
    """manuscript (.tex/.md/.docx), bibliography (.bib) or figure (images and .pdf)."""
    if ext in MANUSCRIPT_EXT:
        return "manuscript"
    if ext in BIB_EXT:
        return "bibliography"
    return "figure"


def store_uploads(workspace: JobWorkspace, incoming: Iterable[IncomingFile], settings: Settings) -> list[UploadedFile]:
    """Stream uploads to disk, enforcing type and size limits. Raises UploadError."""
    workspace.create()
    stored: list[UploadedFile] = []
    total = 0
    items = list(incoming)
    if not items:
        raise UploadError("No files were uploaded.")
    if len(items) > settings.max_files:
        raise UploadError(f"Too many files: {len(items)} (maximum {settings.max_files}).")
    for item in items:
        original = item.filename or "upload"
        ext = Path(original).suffix.lower()
        if ext not in ALLOWED_EXT:
            raise UploadError(
                f"{original}: file type '{ext or 'none'}' is not allowed. Allowed: "
                + ", ".join(sorted(ALLOWED_EXT))
            )
        mime = (item.content_type or "").split(";")[0].strip().lower()
        if mime not in ACCEPTED_MIME.get(ext, set()):
            raise UploadError(f"{original}: MIME type '{mime}' does not match extension '{ext}'.")
        target = workspace.unique_upload_path(sanitize_filename(original))
        digest = hashlib.sha256()
        size = 0
        try:
            with target.open("wb") as out:
                while chunk := item.stream.read(1024 * 1024):
                    size += len(chunk)
                    total += len(chunk)
                    if size > settings.max_file_bytes:
                        raise UploadError(f"{original}: larger than the {settings.max_file_mb} MB per-file limit.")
                    if total > settings.max_total_bytes:
                        raise UploadError(f"Upload exceeds the {settings.max_total_mb} MB total limit.")
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise UploadError(f"{original}: file is empty.")
            verify_signature(target, ext)
        except UploadError:
            target.unlink(missing_ok=True)  # the file is closed by now, so this also works on Windows
            raise
        stored.append(UploadedFile(original_name=original[:255], stored_name=target.name, kind=file_kind(ext),
                                   extension=ext, size_bytes=size, sha256=digest.hexdigest()))
    if not any(f.kind == "manuscript" for f in stored):
        if any(f.extension == ".pdf" for f in stored):
            raise UploadError("PDF papers are not supported. Upload the paper's .tex, .md or .docx source "
                              "(PDF files are accepted only as figures).")
        raise UploadError("No manuscript found. Upload a .tex, .md or .docx file with your paper.")
    return stored
