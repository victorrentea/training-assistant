"""Generate simple fixture PDFs with page numbers for hermetic testing."""

import struct
import os


def _minimal_pdf(num_pages: int, title: str = "Test Slide") -> bytes:
    """Generate a minimal valid PDF with numbered pages. No external dependencies."""
    # Build a minimal PDF with text showing page numbers
    objects = []
    obj_id = 0

    def add_obj(content: str) -> int:
        nonlocal obj_id
        obj_id += 1
        objects.append((obj_id, content))
        return obj_id

    # Catalog
    catalog_id = add_obj("")  # placeholder
    pages_id = add_obj("")    # placeholder

    # Font
    font_id = add_obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    # Pages
    page_ids = []
    for page_num in range(1, num_pages + 1):
        # Content stream: draw page number centered
        text = f"Page {page_num} of {num_pages} - {title}"
        stream = (
            f"BT /F1 24 Tf 100 400 Td ({text}) Tj ET"
        )
        stream_id = add_obj(
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
        )
        page_id = add_obj(
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 612 792] "
            f"/Contents {stream_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        )
        page_ids.append(page_id)

    # Update pages object
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id - 1] = (pages_id,
        f"<< /Type /Pages /Kids [{kids}] /Count {num_pages} >>")

    # Update catalog
    objects[catalog_id - 1] = (catalog_id,
        f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    # Render PDF
    lines = [b"%PDF-1.4\n"]
    offsets = {}
    for oid, content in objects:
        offsets[oid] = len(b"".join(lines))
        lines.append(f"{oid} 0 obj\n{content}\nendobj\n".encode())

    xref_offset = len(b"".join(lines))
    lines.append(b"xref\n")
    lines.append(f"0 {len(objects) + 1}\n".encode())
    lines.append(b"0000000000 65535 f \n")
    for oid in range(1, len(objects) + 1):
        lines.append(f"{offsets[oid]:010d} 00000 n \n".encode())

    lines.append(b"trailer\n")
    lines.append(f"<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n".encode())
    lines.append(b"startxref\n")
    lines.append(f"{xref_offset}\n".encode())
    lines.append(b"%%EOF\n")

    return b"".join(lines)


def generate_fixtures(output_dir: str) -> dict[str, str]:
    """Generate fixture PDFs. Returns {slug: filepath}."""
    os.makedirs(output_dir, exist_ok=True)
    fixtures = {
        "clean-code": ("Clean Code", 5),
        "design-patterns": ("Design Patterns", 8),
        "architecture": ("Architecture", 3),
    }
    paths = {}
    for slug, (title, pages) in fixtures.items():
        pdf_bytes = _minimal_pdf(pages, title)
        path = os.path.join(output_dir, f"{slug}.pdf")
        with open(path, "wb") as f:
            f.write(pdf_bytes)
        paths[slug] = path
        print(f"Generated {path} ({pages} pages, {len(pdf_bytes)} bytes)")
    return paths


if __name__ == "__main__":
    generate_fixtures("/tmp/fixture-pdfs")
