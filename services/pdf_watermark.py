"""
xIRS PDF Watermark Service

Adds watermark overlay to PDFs based on license state.
For Trial/Grace/Basic mode, a diagonal watermark is applied.

Version: 1.0
Date: 2026-01-25
Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.4 (P1-02)
"""

import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import PDF libraries
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.colors import Color
    from PyPDF2 import PdfReader, PdfWriter
    PDF_WATERMARK_AVAILABLE = True
except ImportError:
    PDF_WATERMARK_AVAILABLE = False
    logger.warning("PDF watermark disabled: missing reportlab or PyPDF2. Install: pip install reportlab PyPDF2")


def create_watermark_pdf(
    text: str,
    page_size: tuple = A4 if PDF_WATERMARK_AVAILABLE else (595.27, 841.89),
    opacity: float = 0.15,
    font_size: int = 60,
    angle: int = 45
) -> Optional[io.BytesIO]:
    """
    Create a single-page PDF with diagonal watermark text.

    Args:
        text: Watermark text to display
        page_size: Page dimensions (width, height)
        opacity: Text opacity (0.0 to 1.0)
        font_size: Font size in points
        angle: Rotation angle in degrees

    Returns:
        BytesIO buffer containing watermark PDF, or None if unavailable
    """
    if not PDF_WATERMARK_AVAILABLE:
        logger.warning("Watermark not available - missing dependencies")
        return None

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=page_size)

    width, height = page_size

    # Set watermark style
    c.setFillColor(Color(0.5, 0.5, 0.5, alpha=opacity))  # Gray with opacity
    c.setFont("Helvetica-Bold", font_size)

    # Calculate center position
    text_width = c.stringWidth(text, "Helvetica-Bold", font_size)

    # Save state, rotate, draw, restore
    c.saveState()
    c.translate(width / 2, height / 2)
    c.rotate(angle)

    # Draw watermark text centered
    c.drawCentredString(0, 0, text)

    # Draw additional smaller watermarks in corners
    c.setFont("Helvetica", 12)
    c.setFillColor(Color(0.5, 0.5, 0.5, alpha=opacity * 1.5))

    c.restoreState()

    # Add corner watermarks
    c.saveState()
    c.setFont("Helvetica", 10)
    c.setFillColor(Color(0.5, 0.5, 0.5, alpha=0.3))

    # Bottom-left
    c.drawString(20, 20, text)
    # Top-right
    c.drawRightString(width - 20, height - 20, text)

    c.restoreState()

    c.save()
    buffer.seek(0)
    return buffer


def apply_watermark_to_pdf(
    pdf_buffer: io.BytesIO,
    watermark_text: str
) -> io.BytesIO:
    """
    Apply watermark to all pages of a PDF.

    Args:
        pdf_buffer: Original PDF as BytesIO
        watermark_text: Text to use for watermark

    Returns:
        New PDF BytesIO with watermark applied
    """
    if not PDF_WATERMARK_AVAILABLE:
        logger.warning("Watermark skipped - dependencies not available")
        return pdf_buffer

    if not watermark_text:
        return pdf_buffer

    try:
        # Read original PDF
        pdf_buffer.seek(0)
        reader = PdfReader(pdf_buffer)
        writer = PdfWriter()

        # Get page size from first page
        first_page = reader.pages[0]
        page_width = float(first_page.mediabox.width)
        page_height = float(first_page.mediabox.height)

        # Create watermark
        watermark_buffer = create_watermark_pdf(
            watermark_text,
            page_size=(page_width, page_height)
        )

        if not watermark_buffer:
            return pdf_buffer

        watermark_reader = PdfReader(watermark_buffer)
        watermark_page = watermark_reader.pages[0]

        # Apply watermark to each page
        for page in reader.pages:
            page.merge_page(watermark_page)
            writer.add_page(page)

        # Write to new buffer
        output_buffer = io.BytesIO()
        writer.write(output_buffer)
        output_buffer.seek(0)

        logger.info(f"Applied watermark '{watermark_text}' to {len(reader.pages)} pages")
        return output_buffer

    except Exception as e:
        logger.error(f"Watermark application failed: {e}")
        # Return original on failure
        pdf_buffer.seek(0)
        return pdf_buffer


def get_watermark_status() -> dict:
    """Get watermark service status."""
    return {
        "available": PDF_WATERMARK_AVAILABLE,
        "dependencies": {
            "reportlab": PDF_WATERMARK_AVAILABLE,
            "PyPDF2": PDF_WATERMARK_AVAILABLE
        }
    }
