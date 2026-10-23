"""Tests for PDF and image helpers in core.utils."""

import base64
import io
import pytest

from tests.helpers import _make_minimal_pdf
from mcp.types import ImageContent

from core.utils import (
    IMAGE_MIME_TYPES,
    INLINE_IMAGE_MIME_TYPES,
    SVG_MIME_TYPE,
    encode_image_content,
    extract_pdf_text,
    image_content_from_bytes,
    svg_source_text,
)


# ---------------------------------------------------------------------------
# extract_pdf_text
# ---------------------------------------------------------------------------


def test_extract_pdf_text_valid():
    pdf_bytes = _make_minimal_pdf("Hello World")
    result = extract_pdf_text(pdf_bytes)
    assert result is not None
    assert "Hello World" in result


def test_extract_pdf_text_corrupted():
    result = extract_pdf_text(b"this is not a pdf")
    assert result is None


def test_extract_pdf_text_empty():
    """A PDF with a blank page (no text) returns None."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)

    result = extract_pdf_text(buf.getvalue())
    assert result is None


# ---------------------------------------------------------------------------
# encode_image_content
# ---------------------------------------------------------------------------


def test_encode_image_content_png():
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    result = encode_image_content(raw, "image/png")
    assert result.startswith("[base64_image:image/png]")
    encoded_part = result[len("[base64_image:image/png]") :]
    assert base64.b64decode(encoded_part) == raw


def test_encode_image_content_jpeg():
    raw = b"\xff\xd8\xff" + b"\x00" * 50
    result = encode_image_content(raw, "image/jpeg")
    assert result.startswith("[base64_image:image/jpeg]")
    encoded_part = result[len("[base64_image:image/jpeg]") :]
    assert base64.b64decode(encoded_part) == raw


def test_encode_image_content_rejects_non_image_mime():
    """encode_image_content should raise ValueError for non-image MIME types."""
    raw = b"some content"
    with pytest.raises(ValueError) as exc_info:
        encode_image_content(raw, "application/pdf")
    assert "Expected image/* MIME type" in str(exc_info.value)
    assert "application/pdf" in str(exc_info.value)


# ---------------------------------------------------------------------------
# image_content_from_bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mime_type", sorted(IMAGE_MIME_TYPES))
def test_image_content_from_bytes_round_trips(mime_type):
    raw = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    result = image_content_from_bytes(raw, mime_type)
    assert isinstance(result, ImageContent)
    assert result.type == "image"
    assert result.mime_type == mime_type
    assert base64.b64decode(result.data) == raw


def test_image_content_from_bytes_rejects_non_image_mime():
    with pytest.raises(ValueError) as exc_info:
        image_content_from_bytes(b"some content", "application/pdf")
    assert "Expected image/* MIME type" in str(exc_info.value)
    assert "application/pdf" in str(exc_info.value)


# ---------------------------------------------------------------------------
# IMAGE_MIME_TYPES constant
# ---------------------------------------------------------------------------


def test_image_mime_types_contains_common():
    for mt in ("image/png", "image/jpeg", "image/gif", "image/webp"):
        assert mt in IMAGE_MIME_TYPES


def test_inline_image_mime_types_is_model_api_allowlist():
    assert INLINE_IMAGE_MIME_TYPES == {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
    assert INLINE_IMAGE_MIME_TYPES <= IMAGE_MIME_TYPES


# ---------------------------------------------------------------------------
# svg_source_text
# ---------------------------------------------------------------------------


def test_svg_mime_type_is_not_inline():
    assert SVG_MIME_TYPE in IMAGE_MIME_TYPES
    assert SVG_MIME_TYPE not in INLINE_IMAGE_MIME_TYPES


def test_svg_source_text_returns_markup_unchanged():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>Ünïcode ✓</text></svg>'
    assert svg_source_text(svg.encode("utf-8")) == svg


def test_svg_source_text_elides_each_base64_data_uri():
    png = b"\x89PNG" + b"\x00" * 100
    jpeg = b"\xff\xd8\xff" + b"\x01" * 50
    svg = (
        f'<svg><image href="data:image/png;base64,{base64.b64encode(png).decode()}"/>'
        f"<image xlink:href='data:image/jpeg;base64,{base64.b64encode(jpeg).decode()}'/>"
        "</svg>"
    )
    assert svg_source_text(svg.encode()) == (
        f'<svg><image href="data:image/png;base64,[{len(png)} bytes of base64 omitted]"/>'
        f"<image xlink:href='data:image/jpeg;base64,[{len(jpeg)} bytes of base64 omitted]'/>"
        "</svg>"
    )


def test_svg_source_text_elides_whitespace_wrapped_payload():
    """SVG tools often wrap long base64 payloads across lines."""
    raw = bytes(range(256))
    encoded = base64.b64encode(raw).decode()
    wrapped = "\n".join(encoded[i : i + 76] for i in range(0, len(encoded), 76))
    svg = f'<svg><image href="data:image/png;base64,{wrapped}"/></svg>'
    assert svg_source_text(svg.encode()) == (
        f'<svg><image href="data:image/png;base64,[{len(raw)} bytes of base64 omitted]"/></svg>'
    )


def test_svg_source_text_elides_uri_with_parameters_or_no_mime():
    raw = b"font-bytes" * 10
    encoded = base64.b64encode(raw).decode()
    svg = (
        f"<style>@font-face{{src:url(data:font/woff2;charset=utf-8;base64,{encoded})}}</style>"
        f'<image href="data:;base64,{encoded}"/>'
    )
    assert svg_source_text(svg.encode()) == (
        f"<style>@font-face{{src:url(data:font/woff2;base64,[{len(raw)} bytes of base64 omitted])}}</style>"
        f'<image href="data:data;base64,[{len(raw)} bytes of base64 omitted]"/>'
    )


def test_svg_source_text_leaves_non_base64_data_uris():
    """Percent-encoded data URIs are already text, so they are kept."""
    svg = '<svg><image href="data:image/svg+xml,%3Csvg%3E%3C/svg%3E"/></svg>'
    assert svg_source_text(svg.encode()) == svg


def test_svg_source_text_returns_none_for_non_utf8():
    assert svg_source_text(b"\x1f\x8b\x08\x00\xff\xfe") is None


def test_svg_source_text_keeps_short_payloads():
    """Eliding a tiny payload would make the text longer, not shorter."""
    svg = '<svg><image href="data:image/png;base64,QUJD"/></svg>'
    assert svg_source_text(svg.encode()) == svg


def test_svg_source_text_does_not_consume_following_text():
    """The match stops at the end of the payload, not at the next whitespace run."""
    raw = bytes(range(128))
    encoded = base64.b64encode(raw).decode()
    svg = f'<image href="data:image/png;base64,{encoded}"/> \n <text>Next</text>'
    assert svg_source_text(svg.encode()) == (
        f'<image href="data:image/png;base64,[{len(raw)} bytes of base64 omitted]"/>'
        " \n <text>Next</text>"
    )
