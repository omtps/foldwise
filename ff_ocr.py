"""OCR for scanned PDFs and images, using the text-recognition engine built into Windows 10/11 (no Tesseract needed).

PDF pages are rendered with pypdfium2 and recognised with Windows.Media.Ocr (through the `winrt` projection packages).
Everything is optional: `available()` tells the GUI whether the pieces are present.
"""
import asyncio
import io


def available():
    try:
        import winrt.windows.media.ocr  # noqa: F401
        import pypdfium2  # noqa: F401
        return True
    except ImportError:
        return False


async def _ocr_async(png_bytes):
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(list(png_bytes) if not isinstance(png_bytes, (bytes, bytearray)) else png_bytes)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return ""
    result = await engine.recognize_async(bitmap)
    return result.text or ""


def ocr_image(img):
    """Text found in a PIL image ('' if none or OCR unavailable)."""
    if not available():
        return ""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    try:
        return asyncio.run(_ocr_async(buf.getvalue()))
    except Exception:
        return ""


def ocr_pdf(path, max_pages=30, scale=2.0, cancel=lambda: False):
    """Text of up to max_pages pages of a (scanned) PDF."""
    import pypdfium2 as pdfium
    out = []
    pdf = pdfium.PdfDocument(path)
    try:
        for i in range(min(len(pdf), max_pages)):
            if cancel():
                break
            page = pdf[i]
            out.append(ocr_image(page.render(scale=scale).to_pil()))
    finally:
        pdf.close()
    return "\n\n".join(t for t in out if t.strip())
