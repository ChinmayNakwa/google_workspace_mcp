"""Tests for PDF and image handling in get_drive_file_content."""

import base64
import io
from unittest.mock import Mock, patch

import pytest
from fastmcp.tools import ToolResult
from mcp.types import ImageContent, TextContent

from core.utils import INLINE_IMAGE_MIME_TYPES
from tests.helpers import _make_minimal_pdf
from gdrive.drive_helpers import _download_file_bytes
from gdrive.drive_tools import get_drive_file_content


@pytest.fixture(autouse=True)
def _no_ambient_office_xml_limit(monkeypatch):
    """The expansion limit is read from the environment on every extraction."""
    monkeypatch.delenv("WORKSPACE_MCP_MAX_OFFICE_XML_BYTES", raising=False)


def _unwrap(tool):
    fn = tool.fn if hasattr(tool, "fn") else tool
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def mock_resolve():
    with patch("gdrive.drive_tools.resolve_drive_item") as m:
        m.return_value = (
            "file123",
            {
                "name": "test_file",
                "mimeType": "application/pdf",
                "webViewLink": "https://drive.google.com/file/file123",
            },
        )
        yield m


@pytest.fixture
def mock_resolve_image():
    with patch("gdrive.drive_tools.resolve_drive_item") as m:
        m.return_value = (
            "img456",
            {
                "name": "photo.png",
                "mimeType": "image/png",
                "webViewLink": "https://drive.google.com/file/img456",
            },
        )
        yield m


class _FakeDownloader:
    def __init__(self, fh, data):
        fh.write(data)
        fh.seek(0)

    def next_chunk(self):
        return None, True


def _patch_downloader(content_bytes):
    """Patch MediaIoBaseDownload to write content_bytes into the BytesIO handle."""
    return patch(
        "core.file_limits.MediaIoBaseDownload",
        side_effect=lambda fh, req, chunksize=None: _FakeDownloader(fh, content_bytes),
    )


@pytest.mark.asyncio
async def test_download_file_bytes_supports_shared_drives():
    mock_service = Mock()
    mock_service.files().get_media.return_value = "req"

    with _patch_downloader(b"content"):
        result = await _download_file_bytes(mock_service, "file123")

    assert result == b"content"
    mock_service.files.return_value.get_media.assert_called_once_with(
        fileId="file123", supportsAllDrives=True
    )


@pytest.mark.asyncio
async def test_download_file_bytes_leaves_export_request_unchanged():
    mock_service = Mock()
    mock_service.files().export_media.return_value = "req"

    with _patch_downloader(b"exported"):
        result = await _download_file_bytes(mock_service, "doc123", "text/plain")

    assert result == b"exported"
    mock_service.files.return_value.export_media.assert_called_once_with(
        fileId="doc123", mimeType="text/plain"
    )


# ---------------------------------------------------------------------------
# PDF tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_drive_file_content_pdf(mock_resolve):
    pdf_bytes = _make_minimal_pdf("Contract clause 1")
    mock_service = Mock()
    mock_service.files().get_media.return_value = "req"

    with _patch_downloader(pdf_bytes):
        result = await _unwrap(get_drive_file_content)(
            service=mock_service,
            user_google_email="user@example.com",
            file_id="file123",
        )

    assert "Contract clause 1" in result
    assert "--- CONTENT ---" in result


@pytest.mark.asyncio
async def test_get_drive_file_content_pdf_empty(mock_resolve):
    """Empty/scanned PDF falls back to guidance message."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    empty_pdf = buf.getvalue()

    mock_service = Mock()
    mock_service.files().get_media.return_value = "req"

    with _patch_downloader(empty_pdf):
        result = await _unwrap(get_drive_file_content)(
            service=mock_service,
            user_google_email="user@example.com",
            file_id="file123",
        )

    assert "get_drive_file_download_url" in result


@pytest.mark.asyncio
async def test_get_drive_file_content_reports_invalid_docx(mock_resolve):
    mime_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    mock_resolve.return_value[1]["mimeType"] = mime_type
    mock_service = Mock()
    mock_service.files().get_media.return_value = "req"

    with _patch_downloader(b"not a zip"):
        result = await _unwrap(get_drive_file_content)(
            service=mock_service,
            user_google_email="user@example.com",
            file_id="file123",
        )

    assert "appears damaged" in result
    assert "unsupported text encoding" not in result


@pytest.mark.asyncio
async def test_get_drive_file_content_reports_oversized_expansion(
    mock_resolve, monkeypatch
):
    """A file that expands past the limit is reported as that — not as damaged,
    and not handed on to the raw-bytes fallback."""
    import zipfile

    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    mock_resolve.return_value[1]["mimeType"] = mime_type
    monkeypatch.setenv("WORKSPACE_MCP_MAX_OFFICE_XML_BYTES", "1000")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", "<workbook>" + " " * 20_000 + "</workbook>")
    mock_service = Mock()
    mock_service.files().get_media.return_value = "req"

    with _patch_downloader(buf.getvalue()):
        result = await _unwrap(get_drive_file_content)(
            service=mock_service,
            user_google_email="user@example.com",
            file_id="file123",
        )

    assert "expands beyond the extraction limit" in result
    assert "WORKSPACE_MCP_MAX_OFFICE_XML_BYTES" in result
    assert "convert it to a native Google file" in result
    assert "appears damaged" not in result
    assert "unsupported text encoding" not in result


# ---------------------------------------------------------------------------
# Image tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mime_type", sorted(INLINE_IMAGE_MIME_TYPES))
async def test_get_drive_file_content_image(mock_resolve_image, mime_type):
    mock_resolve_image.return_value[1]["mimeType"] = mime_type
    image_bytes = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
    encoded = base64.b64encode(image_bytes).decode("ascii")
    mock_service = Mock()
    mock_service.files().get_media.return_value = "req"

    with _patch_downloader(image_bytes):
        result = await _unwrap(get_drive_file_content)(
            service=mock_service,
            user_google_email="user@example.com",
            file_id="img456",
        )

    assert isinstance(result, ToolResult)
    assert len(result.content) == 2
    text_block, image_block = result.content

    assert isinstance(text_block, TextContent)
    assert text_block.text.startswith(
        f'File: "photo.png" (ID: img456, Type: {mime_type})\n'
        "Link: https://drive.google.com/file/img456\n\n--- CONTENT ---\n"
    )
    assert f"{len(image_bytes)} bytes" in text_block.text
    assert encoded not in text_block.text
    assert "base64_image" not in text_block.text

    assert isinstance(image_block, ImageContent)
    assert image_block.mime_type == mime_type
    assert base64.b64decode(image_block.data) == image_bytes

    assert result.structured_content == {"result": text_block.text}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mime_type, file_bytes",
    [
        ("image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'),
        ("image/bmp", b"BM" + b"\x00" * 64),
        ("image/tiff", b"II*\x00" + b"\x00" * 64),
    ],
    ids=["svg", "bmp", "tiff"],
)
async def test_get_drive_file_content_non_inline_image_unchanged(
    mock_resolve_image, mime_type, file_bytes
):
    """SVG, BMP and TIFF keep the base64 text result; model APIs reject them
    as image blocks, so they are not sent as image content."""
    mock_resolve_image.return_value[1]["mimeType"] = mime_type
    mock_service = Mock()
    mock_service.files().get_media.return_value = "req"

    with _patch_downloader(file_bytes):
        result = await _unwrap(get_drive_file_content)(
            service=mock_service,
            user_google_email="user@example.com",
            file_id="img456",
        )

    assert result == (
        f'File: "photo.png" (ID: img456, Type: {mime_type})\n'
        "Link: https://drive.google.com/file/img456\n\n--- CONTENT ---\n"
        f"[base64_image:{mime_type}]" + base64.b64encode(file_bytes).decode("ascii")
    )


@pytest.mark.asyncio
async def test_get_drive_file_content_text_returns_plain_string(mock_resolve):
    mock_resolve.return_value[1]["mimeType"] = "text/plain"
    mock_service = Mock()
    mock_service.files().get_media.return_value = "req"

    with _patch_downloader(b"hello world"):
        result = await _unwrap(get_drive_file_content)(
            service=mock_service,
            user_google_email="user@example.com",
            file_id="file123",
        )

    assert result == (
        'File: "test_file" (ID: file123, Type: text/plain)\n'
        "Link: https://drive.google.com/file/file123\n\n--- CONTENT ---\n"
        "hello world"
    )
