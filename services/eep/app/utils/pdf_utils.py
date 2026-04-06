"""PDF → PNG conversion using PyMuPDF."""


def pdf_to_png_bytes(pdf_bytes: bytes, dpi: int = 150) -> bytes:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")
