import fitz  # PyMuPDF
from pathlib import Path

def pdf_to_png(pdf_path: Path, out_path: Path, dpi: int = 150) -> tuple[int, int, int]:
    """
    Convert the first page of a PDF to PNG.
    Returns (width_px, height_px) of the output image.
    DPI=150 gives ~1240x1754 for A4. Increase to 200+ for larger plans.
    """
    doc = fitz.open(str(pdf_path))
    num_pages = len(doc)
    page = doc[0]
    mat = fitz.Matrix(dpi / 72, dpi / 72)  # 72 DPI is PDF native
    clip = page.rect  # full page
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    pix.save(str(out_path))
    return pix.width, pix.height, num_pages
