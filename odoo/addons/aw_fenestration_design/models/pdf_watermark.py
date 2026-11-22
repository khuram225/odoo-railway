# -*- coding: utf-8 -*-
"""Put a watermark BEHIND every page of a finished PDF.

It is done on the PDF and not in the HTML because wkhtmltopdf cannot repeat an element
on every page: a `position: fixed` image is laid out once for the whole document (seen:
one image straddling pages 2 and 3 of a 4-page schedule), and a flowing document like
the Quotation has no per-page container to put one in. Here the watermark is a page of
its own, the same size as the page it goes behind, and the original page is merged on
top of it, so the text and the drawing stay on top and untouched.
"""
import io

from odoo.tools.pdf import PdfFileReader, PdfFileWriter


def stamp(pdf, watermark_for):
    """The PDF with a watermark behind every page.

    `watermark_for(width_pt, height_pt)` gives (png bytes, width_pt, height_pt) of the
    watermark for a page of that size, or None for no watermark; when it gives None
    for any page the PDF is returned as it came (no logo, switched off)."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    reader = PdfFileReader(io.BytesIO(pdf), strict=False)
    pages = [reader.getPage(i) for i in range(reader.getNumPages())]
    if not pages:
        return pdf
    sizes = [(float(abs(p.mediaBox.getWidth())),
              float(abs(p.mediaBox.getHeight()))) for p in pages]
    made = {}
    for width, height in sizes:
        key = (round(width), round(height))
        if key not in made:
            result = watermark_for(width, height)
            if not result:
                return pdf
            png, w, h = result
            # one image object for every page of this size: it is stored once
            made[key] = (ImageReader(io.BytesIO(png)), w, h)
    packet = io.BytesIO()
    page_canvas = canvas.Canvas(packet)
    for width, height in sizes:
        image, w, h = made[(round(width), round(height))]
        page_canvas.setPageSize((width, height))
        page_canvas.drawImage(
            image, (width - w) / 2.0, (height - h) / 2.0, w, h, mask='auto')
        page_canvas.showPage()
    page_canvas.save()
    marks = PdfFileReader(packet, overwriteWarnings=False)
    writer = PdfFileWriter()
    for index, page in enumerate(pages):
        writer.addPage(marks.getPage(index))
        stamped = writer.getPage(-1)
        stamped.mergePage(page)          # the page goes on top of the watermark
        # merging writes the page's content out uncompressed: a 135 KB schedule
        # came out at 2.5 MB. Odoo's own add_banner compresses after merging too.
        stamped.compressContentStreams()
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
