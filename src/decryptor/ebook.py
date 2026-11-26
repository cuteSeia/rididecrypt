"""Create EPUB and PDF files from the images in a decrypted book folder."""

import html
import re
import tempfile
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .core import IMAGE_SUFFIXES

Progress = Optional[Callable[[int, int], None]]


def _images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise FileNotFoundError(f"책 폴더가 없습니다: {folder}")
    paths = [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
    paths.sort(
        key=lambda path: (
            0 if path.stem.casefold() == "!000" else 1,
            [(0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"(\d+)", path.name)],
        )
    )
    if not paths:
        raise ValueError("선택한 폴더에 이미지가 없습니다")
    return paths


def _epub_image(path: Path) -> tuple[str, bytes]:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }[suffix]
        return media_type, path.read_bytes()

    from io import BytesIO

    from PIL import Image

    try:
        with Image.open(path) as source:
            output = BytesIO()
            source.save(output, format="PNG")
            return "image/png", output.getvalue()
    except Exception as exc:
        raise ValueError(f"EPUB 이미지 변환 실패: {path.name}: {exc}") from exc


def create_epub(folder: Path, destination: Path, progress: Progress = None) -> int:
    images = _images(folder)
    destination.parent.mkdir(parents=True, exist_ok=True)
    title = folder.name
    safe_title = html.escape(title)
    manifest = []
    spine = []
    nav_items = []
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, str(folder.resolve()))
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with zipfile.ZipFile(destination, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
        epub.writestr("OEBPS/style.css", "html,body{margin:0;padding:0;background:#fff}body{display:flex;align-items:center;justify-content:center;height:100vh}img{display:block;max-width:100%;max-height:100%;object-fit:contain}")
        for index, path in enumerate(images, 1):
            media_type, data = _epub_image(path)
            image_name = f"image{index:05d}{'.png' if media_type == 'image/png' and path.suffix.lower() not in {'.png'} else path.suffix.lower()}"
            page_id = f"page{index:05d}"
            image_id = f"img{index:05d}"
            epub.writestr(f"OEBPS/{image_name}", data, compress_type=zipfile.ZIP_STORED)
            epub.writestr(f"OEBPS/{page_id}.xhtml", f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{safe_title} - {index}</title><link rel="stylesheet" type="text/css" href="style.css"/></head><body><img src="{image_name}" alt="{index}"/></body></html>''')
            cover_property = ' properties="cover-image"' if path.stem.casefold() == "!000" else ""
            manifest.extend((f'<item id="{image_id}" href="{image_name}" media-type="{media_type}"{cover_property}/>', f'<item id="{page_id}" href="{page_id}.xhtml" media-type="application/xhtml+xml"/>'))
            spine.append(f'<itemref idref="{page_id}"/>')
            nav_items.append(f'<li><a href="{page_id}.xhtml">{index}</a></li>')
            if progress:
                progress(index, len(images))
        epub.writestr("OEBPS/nav.xhtml", f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>목차</title></head><body><nav epub:type="toc"><h1>{safe_title}</h1><ol>{''.join(nav_items)}</ol></nav></body></html>''')
        epub.writestr("OEBPS/content.opf", f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.3" unique-identifier="bookid" xml:lang="ko"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">urn:uuid:{identifier}</dc:identifier><dc:title>{safe_title}</dc:title><dc:language>ko</dc:language><meta property="dcterms:modified">{modified}</meta>{'<meta name="cover" content="img00001"/>' if any(path.stem.casefold() == '!000' for path in images) else ''}</metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="css" href="style.css" media-type="text/css"/>{''.join(manifest)}</manifest><spine>{''.join(spine)}</spine></package>''')
    return len(images)


def create_pdf(folder: Path, destination: Path, progress: Progress = None, workers: int = 2) -> int:
    images = _images(folder)
    destination.parent.mkdir(parents=True, exist_ok=True)
    import img2pdf
    from PIL import Image

    page_size = (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297))
    layout = img2pdf.get_layout_fun(page_size)

    with tempfile.TemporaryDirectory(prefix=f".{destination.stem}-pdf-", dir=destination.parent) as temp_dir:
        def prepare_image(item: tuple[int, Path]) -> Path:
            index, path = item
            if path.suffix.lower() != ".webp":
                return path
            target = Path(temp_dir) / f"{index:05d}.jpg"
            with Image.open(path) as source:
                if source.mode in {"RGBA", "LA"} or "transparency" in source.info:
                    rgba = source.convert("RGBA")
                    image = Image.new("RGB", rgba.size, "white")
                    image.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    image = source.convert("RGB")
                image.save(target, "JPEG", quality=95, subsampling=0, optimize=False)
            return target

        prepared = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            for index, path in enumerate(executor.map(prepare_image, enumerate(images, 1)), 1):
                prepared.append(path)
                if progress:
                    progress(index, len(images))

        with destination.open("wb") as output:
            img2pdf.convert(
                [str(path) for path in prepared],
                outputstream=output,
                rotation=img2pdf.Rotation.ifvalid,
                layout_fun=layout,
            )
    return len(images)
