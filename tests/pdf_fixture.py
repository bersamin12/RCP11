"""A real, parseable PDF for tests that need one.

Built with reportlab (already a dependency) rather than hand-assembled, so pypdf
can actually parse it and extract its text -- which is what the full-text
extraction tests need. Not a pytest fixture module; import the helpers directly.
"""

import io

SENTENCE = "Raising the chilled-water setpoint from 6 to 10 C reduced chiller energy by 14 percent."


def make_pdf(pages: list[str] | None = None) -> bytes:
    """One page per string, each drawing that string as extractable text."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    document = canvas.Canvas(buffer, pagesize=(612, 792))
    for text in pages or [SENTENCE]:
        document.setFont("Helvetica", 12)
        document.drawString(72, 700, text)
        document.showPage()
    document.save()
    return buffer.getvalue()
