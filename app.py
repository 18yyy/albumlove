from __future__ import annotations

import io
import json
import mimetypes
import re
import shutil
import zipfile
import base64
import hashlib
import os
import secrets
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import fitz
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
OUTPUT = ROOT / "output"
SESSIONS = ROOT / "sessions"
TEMPLATE_PATH = ROOT / "template.json"

def find_pdf(preferred: str, contains: tuple[str, ...]) -> Path:
    preferred_path = ROOT / preferred
    if preferred_path.exists():
        return preferred_path
    pdfs = list(ROOT.glob("*.pdf"))
    for path in pdfs:
        normalized = path.name.casefold()
        if all(part.casefold() in normalized for part in contains):
            return path
    return preferred_path


DEFAULT_PDFS = {
    "figurinhas": find_pdf("Figurinhas.pdf", ("figur",)),
    "album": find_pdf("Álbum Oficial - Nosso Amor.pdf", ("album", "amor")),
}
DEFAULT_PHOTOS = ROOT / "fotos"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
AUTH_COOKIE = "album_editor_auth"
SESSION_COOKIE = "album_editor_session"
FONT_FILES = {
    "arial": Path("C:/Windows/Fonts/arial.ttf"),
    "arial-bold": Path("C:/Windows/Fonts/arialbd.ttf"),
    "segoe": Path("C:/Windows/Fonts/segoeui.ttf"),
    "calibri": Path("C:/Windows/Fonts/calibri.ttf"),
}


def clean_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", value or "")


def auth_password() -> str:
    return os.environ.get("ACCESS_PASSWORD", "")


def auth_token() -> str:
    password = auth_password()
    secret = os.environ.get("ACCESS_SESSION_SECRET", password)
    return hashlib.sha256(f"{password}:{secret}".encode("utf-8")).hexdigest()


def cookie_value(header: str, name: str) -> str:
    for item in (header or "").split(";"):
        item = item.strip()
        if item.startswith(f"{name}="):
            return item.split("=", 1)[1]
    return ""


def safe_session_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", value or "")[:80]


def decode_data_url(value: str) -> tuple[str, bytes]:
    if "," not in value:
        raise ValueError("Imagem enviada em formato inválido.")
    header, encoded = value.split(",", 1)
    match = re.search(r"data:(image/[a-zA-Z0-9.+-]+);base64", header)
    if not match:
        raise ValueError("Apenas imagens em base64 são aceitas.")
    return match.group(1), base64.b64decode(encoded)


def safe_project_path(value: str | None, fallback: Path) -> Path:
    if not value:
        return fallback
    raw = Path(unquote(value))
    path = raw if raw.is_absolute() else ROOT / raw
    resolved = path.resolve()
    root = ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("O caminho precisa estar dentro da pasta do projeto.")
    return resolved


def photo_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted([p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS])


def page_info(pdf_path: Path) -> list[dict]:
    doc = fitz.open(pdf_path)
    try:
        return [
            {"page": index + 1, "width": page.rect.width, "height": page.rect.height}
            for index, page in enumerate(doc)
        ]
    finally:
        doc.close()


def rect_contains(outer: fitz.Rect, inner: fitz.Rect, tolerance: float = 3.0) -> bool:
    return (
        inner.x0 >= outer.x0 - tolerance
        and inner.y0 >= outer.y0 - tolerance
        and inner.x1 <= outer.x1 + tolerance
        and inner.y1 <= outer.y1 + tolerance
    )


def is_probable_photo_rect(rect: fitz.Rect, page: fitz.Rect) -> bool:
    page_area = page.width * page.height
    area_ratio = (rect.width * rect.height) / page_area
    aspect = rect.width / max(rect.height, 1)
    if area_ratio < 0.006 or area_ratio > 0.72:
        return False
    if aspect < 0.28 or aspect > 3.2:
        return False
    if rect.width < 28 or rect.height < 28:
        return False
    return True


def detect_image_fields(pdf_key: str, pdf_path: Path) -> list[dict]:
    fields: list[dict] = []
    doc = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(doc):
            image_infos = page.get_image_info(xrefs=True)
            raw_rects: list[fitz.Rect] = []
            for info in image_infos:
                bbox = fitz.Rect(info["bbox"])
                if not is_probable_photo_rect(bbox, page.rect):
                    continue
                raw_rects.append(bbox)

            filtered: list[fitz.Rect] = []
            for rect in raw_rects:
                rect_area = rect.width * rect.height
                contains_inner_photo = False
                for other in raw_rects:
                    if other is rect:
                        continue
                    other_area = other.width * other.height
                    if rect_contains(rect, other) and 0.18 <= other_area / rect_area <= 0.92:
                        contains_inner_photo = True
                        break
                if not contains_inner_photo:
                    filtered.append(rect)

            seen: set[tuple[int, int, int, int, int]] = set()
            for bbox in sorted(filtered, key=lambda item: (page_index, item.y0, item.x0)):
                key = (
                    page_index,
                    round(bbox.x0),
                    round(bbox.y0),
                    round(bbox.x1),
                    round(bbox.y1),
                )
                if key in seen:
                    continue
                seen.add(key)
                fields.append(
                    {
                        "id": f"{pdf_key}-foto-{len(fields)+1}",
                        "pdf": pdf_key,
                        "page": page_index + 1,
                        "type": "photo",
                        "x": round(bbox.x0, 2),
                        "y": round(bbox.y0, 2),
                        "width": round(bbox.width, 2),
                        "height": round(bbox.height, 2),
                        "rotation": 0,
                        "align": "center",
                        "fontSize": 18,
                        "fontColor": "#2b2523",
                        "photoIndex": len(fields),
                        "source": "image",
                    }
                )
    finally:
        doc.close()
    return fields


def classify_text(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) < 3 or len(normalized) > 90:
        return None
    if re.search(r"\d{1,2}[/.-]\d{1,2}([/.-]\d{2,4})?", normalized):
        return "date"
    if re.search(r"\b(e|&)\b", normalized, flags=re.IGNORECASE) and len(normalized) <= 45:
        return "name"
    if "gustavo" in normalized.casefold() or "yasmim" in normalized.casefold():
        return "name"
    if any(word in normalized.casefold() for word in ("amor", "amo", "sempre", "namoro")):
        return "text"
    return None


def detect_text_fields(pdf_key: str, pdf_path: Path, offset: int = 0) -> list[dict]:
    fields: list[dict] = []
    doc = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(doc):
            data = page.get_text("dict")
            seen: set[tuple[int, int, int, int, str]] = set()
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                text = " ".join(
                    span.get("text", "")
                    for line in block.get("lines", [])
                    for span in line.get("spans", [])
                ).strip()
                kind = classify_text(text)
                if not kind:
                    continue
                bbox = fitz.Rect(block["bbox"])
                if bbox.width < 18 or bbox.height < 5:
                    continue
                key = (round(bbox.x0), round(bbox.y0), round(bbox.x1), round(bbox.y1), kind)
                if key in seen:
                    continue
                seen.add(key)
                padding_x = max(4, bbox.width * 0.08)
                padding_y = max(3, bbox.height * 0.45)
                rect = fitz.Rect(
                    max(0, bbox.x0 - padding_x),
                    max(0, bbox.y0 - padding_y),
                    min(page.rect.width, bbox.x1 + padding_x),
                    min(page.rect.height, bbox.y1 + padding_y),
                )
                spans = [
                    span
                    for line in block.get("lines", [])
                    for span in line.get("spans", [])
                    if span.get("text", "").strip()
                ]
                font_size = spans[0].get("size", 14) if spans else 14
                fields.append(
                    {
                        "id": f"{pdf_key}-{kind}-det-{offset + len(fields) + 1}",
                        "pdf": pdf_key,
                        "page": page_index + 1,
                        "type": kind,
                        "label": text[:40],
                        "x": round(rect.x0, 2),
                        "y": round(rect.y0, 2),
                        "width": round(rect.width, 2),
                        "height": round(rect.height, 2),
                        "rotation": 0,
                        "align": "center",
                        "fontSize": round(max(8, min(28, font_size)), 1),
                        "fontColor": "#2b2523",
                        "photoIndex": 0,
                        "source": "text",
                    }
                )
    finally:
        doc.close()
    return fields


def add_default_text_fields(pdf_key: str, pdf_path: Path, fields: list[dict]) -> None:
    pages = page_info(pdf_path)
    if not pages:
        return
    first = pages[0]
    width = first["width"]
    height = first["height"]
    specs = []
    if pdf_key == "figurinhas":
        specs = [
            ("name", "Nome 1", width * 0.10, height * 0.86, width * 0.35, 28),
            ("name", "Nome 2", width * 0.55, height * 0.86, width * 0.35, 28),
        ]
    else:
        specs = [
            ("name", "Nomes", width * 0.18, height * 0.18, width * 0.64, 36),
            ("date", "Data", width * 0.30, height * 0.25, width * 0.40, 28),
            ("text", "Texto", width * 0.16, height * 0.78, width * 0.68, 58),
        ]
    for index, (kind, label, x, y, w, h) in enumerate(specs, start=1):
        fields.append(
            {
                "id": f"{pdf_key}-{kind}-{index}",
                "pdf": pdf_key,
                "page": 1,
                "type": kind,
                "label": label,
                "x": round(x, 2),
                "y": round(y, 2),
                "width": round(w, 2),
                "height": round(h, 2),
                "rotation": 0,
                "align": "center",
                "fontSize": 20 if kind != "text" else 14,
                "fontColor": "#2b2523",
                "photoIndex": 0,
                "source": "manual-default",
            }
        )


def build_template(paths: dict[str, Path]) -> dict:
    template = {"version": 1, "pdfs": {}, "fields": []}
    for key, path in paths.items():
        template["pdfs"][key] = {"file": path.name, "pages": page_info(path)}
        fields = detect_image_fields(key, path)
        fields.extend(detect_text_fields(key, path, offset=len(fields)))
        if not any(field["type"] in {"name", "date", "text"} for field in fields):
            add_default_text_fields(key, path, fields)
        template["fields"].extend(fields)
    return template


def rotated_quad(rect: fitz.Rect, degrees: float) -> fitz.Quad:
    if not degrees:
        return fitz.Quad(rect)
    center = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    matrix = fitz.Matrix(1, 1).prerotate(degrees)
    points = []
    for point in (rect.tl, rect.tr, rect.br, rect.bl):
        shifted = fitz.Point(point.x - center.x, point.y - center.y) * matrix
        points.append(fitz.Point(shifted.x + center.x, shifted.y + center.y))
    return fitz.Quad(points)


def quad_bbox(quad: fitz.Quad) -> fitz.Rect:
    xs = [quad.ul.x, quad.ur.x, quad.lr.x, quad.ll.x]
    ys = [quad.ul.y, quad.ur.y, quad.lr.y, quad.ll.y]
    return fitz.Rect(min(xs), min(ys), max(xs), max(ys))


def cover_rect(page: fitz.Page, rect: fitz.Rect, color: tuple[float, float, float], rotation: float = 0) -> None:
    if rotation % 360:
        page.draw_quad(rotated_quad(rect, rotation), color=color, fill=color, overlay=True)
    else:
        page.draw_rect(rect, color=color, fill=color, overlay=True)


def image_stream_for_rect(path: Path, rect: fitz.Rect, rotation: float = 0) -> bytes:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        target_ratio = rect.width / rect.height
        source_ratio = img.width / img.height
        if source_ratio > target_ratio:
            new_width = int(img.height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        else:
            new_height = int(img.width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))
        if rotation % 360:
            canvas = Image.new("RGB", img.size, "white")
            rotated = img.rotate(-rotation, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
            rotated_ratio = rotated.width / rotated.height
            if rotated_ratio > target_ratio:
                new_width = int(rotated.height * target_ratio)
                left = (rotated.width - new_width) // 2
                rotated = rotated.crop((left, 0, left + new_width, rotated.height))
            else:
                new_height = int(rotated.width / target_ratio)
                top = (rotated.height - new_height) // 2
                rotated = rotated.crop((0, top, rotated.width, top + new_height))
            img = rotated
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=96, subsampling=0)
        return buffer.getvalue()


def open_field_photo(source: Path | str) -> Image.Image:
    if isinstance(source, str) and source.startswith("data:image/"):
        _, encoded = source.split(",", 1)
        return Image.open(io.BytesIO(base64.b64decode(encoded)))
    return Image.open(source)


def field_photo_source(field: dict, photos: list[Path]) -> Path | str | None:
    custom = field.get("customImageData")
    if isinstance(custom, str) and custom.startswith("data:image/"):
        return custom
    if not photos:
        return None
    photo_index = int(field.get("photoIndex") or 0) % len(photos)
    return photos[photo_index]


def image_bytes_for_photo_field(source: Path | str, field: dict, width_pt: float, height_pt: float, rotation: float) -> tuple[bytes, tuple[int, int]]:
    scale = 4
    target_size = (max(8, round(width_pt * scale)), max(8, round(height_pt * scale)))
    with open_field_photo(source) as photo:
        img = ImageOps.exif_transpose(photo).convert("RGB")
        target_ratio = target_size[0] / target_size[1]
        crop_zoom = max(1, min(4, float(field.get("cropZoom") or 1)))
        crop_x = max(-1, min(1, float(field.get("cropX") or 0)))
        crop_y = max(-1, min(1, float(field.get("cropY") or 0)))
        if img.width / img.height > target_ratio:
            base_height = img.height
            base_width = int(base_height * target_ratio)
        else:
            base_width = img.width
            base_height = int(base_width / target_ratio)
        crop_width = max(1, int(base_width / crop_zoom))
        crop_height = max(1, int(base_height / crop_zoom))
        max_left = max(0, img.width - crop_width)
        max_top = max(0, img.height - crop_height)
        left = int((max_left / 2) + crop_x * (max_left / 2))
        top = int((max_top / 2) + crop_y * (max_top / 2))
        img = img.crop((left, top, left + crop_width, top + crop_height))
        img = img.resize(target_size, Image.Resampling.LANCZOS).convert("RGBA")
        if rotation % 360:
            img = img.rotate(-rotation, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255, 0))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue(), img.size


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = (value or "#2b2523").lstrip("#")
    if len(value) != 6:
        return (0.17, 0.15, 0.14)
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def font_path(name: str | None) -> Path:
    key = (name or "segoe").lower()
    return FONT_FILES.get(key, FONT_FILES["segoe"])


def pil_font(size: float, name: str | None = None) -> ImageFont.FreeTypeFont:
    path = font_path(name)
    if path.exists():
        return ImageFont.truetype(str(path), max(6, round(size)))
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def text_image_stream(field: dict, text: str, rotation: float, base_mode: bool = False) -> tuple[bytes, tuple[int, int]]:
    scale = 4
    width = max(8, round(float(field["width"]) * scale))
    height = max(8, round(float(field["height"]) * scale))
    bg = tuple(int(channel * 255) for channel in hex_to_rgb(field.get("bgColor", "#ffffff")))
    fg = tuple(int(channel * 255) for channel in hex_to_rgb(field.get("fontColor", "#2b2523")))
    bg_alpha = 0 if field.get("bgMode") == "transparent" else 255
    image = Image.new("RGBA", (width, height), (*bg, bg_alpha))
    draw = ImageDraw.Draw(image)
    font = pil_font(float(field.get("fontSize") or 16) * scale, field.get("fontFamily"))
    padding = max(4, round(min(width, height) * 0.08))
    lines = wrap_text(draw, text, font, max(10, width - padding * 2))
    line_boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_height = max((box[3] - box[1] for box in line_boxes), default=height)
    total_height = line_height * len(lines) + max(0, len(lines) - 1) * round(line_height * 0.18)
    y = max(padding, (height - total_height) // 2)
    align = field.get("align", "center")
    for line, box in zip(lines, line_boxes):
        text_width = box[2] - box[0]
        if align == "left":
            x = padding
        elif align == "right":
            x = max(padding, width - padding - text_width)
        else:
            x = max(padding, (width - text_width) // 2)
        draw.text((x, y), line, font=font, fill=(*fg, 255))
        y += line_height + round(line_height * 0.18)
    if rotation % 360:
        image = image.rotate(-rotation, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), image.size


def field_text(field: dict, form: dict) -> str:
    kind = field.get("type")
    if kind == "name":
        one = form.get("person1", "").strip()
        two = form.get("person2", "").strip()
        label = (field.get("label") or "").lower()
        if "2" in label:
            return two or "NOME AQUI"
        if "1" in label:
            return one or "NOME AQUI"
        return " & ".join([part for part in [one, two] if part]) or "NOME AQUI"
    if kind == "date":
        return form.get("date", "").strip() or "DATA AQUI"
    if kind == "text":
        return form.get("customText", "").strip() or "TEXTO AQUI"
    return ""


def expanded_target_rect(rect: fitz.Rect, image_size: tuple[int, int], scale: float = 4) -> fitz.Rect:
    width = image_size[0] / scale
    height = image_size[1] / scale
    center_x = (rect.x0 + rect.x1) / 2
    center_y = (rect.y0 + rect.y1) / 2
    return fitz.Rect(center_x - width / 2, center_y - height / 2, center_x + width / 2, center_y + height / 2)


def sample_background(pdf_key: str, page_number: int, field: dict) -> str:
    pdf_path = DEFAULT_PDFS[pdf_key]
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        zoom = 2
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        x0 = round(float(field["x"]) * zoom)
        y0 = round(float(field["y"]) * zoom)
        x1 = round((float(field["x"]) + float(field["width"])) * zoom)
        y1 = round((float(field["y"]) + float(field["height"])) * zoom)
        pad = 10
        samples = []
        boxes = [
            (max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), max(0, y0)),
            (max(0, x0 - pad), min(img.height, y1), min(img.width, x1 + pad), min(img.height, y1 + pad)),
            (max(0, x0 - pad), max(0, y0), max(0, x0), min(img.height, y1)),
            (min(img.width, x1), max(0, y0), min(img.width, x1 + pad), min(img.height, y1)),
        ]
        for box in boxes:
            if box[2] > box[0] and box[3] > box[1]:
                samples.append(ImageStat.Stat(img.crop(box)).median)
        if not samples:
            return "#ffffff"
        med = tuple(round(sum(sample[i] for sample in samples) / len(samples)) for i in range(3))
        return rgb_to_hex(med)
    finally:
        doc.close()


def render_pdf(
    source: Path,
    destination: Path,
    fields: list[dict],
    pdf_key: str,
    photos: list[Path],
    form: dict,
    base_mode: bool = False,
) -> None:
    doc = fitz.open(source)
    try:
        for field in fields:
            if field.get("pdf") != pdf_key:
                continue
            page_index = int(field.get("page", 1)) - 1
            if page_index < 0 or page_index >= len(doc):
                continue
            page = doc[page_index]
            rect = fitz.Rect(
                float(field["x"]),
                float(field["y"]),
                float(field["x"]) + float(field["width"]),
                float(field["y"]) + float(field["height"]),
            )
            rotation = float(field.get("rotation") or 0) % 360
            bg_color = hex_to_rgb(field.get("bgColor", "#ffffff"))
            kind = field.get("type")
            if field.get("bgMode") != "transparent" or kind == "photo":
                cover_rect(page, rect, bg_color, rotation)
            if kind == "photo":
                if base_mode:
                    page.insert_textbox(
                        rect,
                        "FOTO AQUI",
                        fontsize=max(8, min(18, rect.height / 6)),
                        fontname="helv",
                        color=(0.42, 0.42, 0.42),
                        align=fitz.TEXT_ALIGN_CENTER,
                    )
                    continue
                if not photos:
                    if not field.get("customImageData"):
                        continue
                source = field_photo_source(field, photos)
                if source is None:
                    continue
                stream, size = image_bytes_for_photo_field(source, field, rect.width, rect.height, rotation)
                page.insert_image(expanded_target_rect(rect, size), stream=stream, overlay=True, keep_proportion=False)
            elif kind in {"name", "date", "text"}:
                text = field_text(field, form) if not base_mode else {
                    "name": "NOME AQUI",
                    "date": "DATA AQUI",
                    "text": "TEXTO AQUI",
                }.get(kind, "TEXTO AQUI")
                stream, size = text_image_stream(field, text, rotation, base_mode)
                page.insert_image(expanded_target_rect(rect, size), stream=stream, overlay=True, keep_proportion=False)
        doc.save(destination, garbage=4, deflate=True)
    finally:
        doc.close()


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        if parsed.path == "/":
            return str(STATIC / "index.html")
        if parsed.path.startswith("/static/"):
            return str(ROOT / parsed.path.lstrip("/"))
        return str(STATIC / parsed.path.lstrip("/"))

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.ensure_session_cookie_header()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def is_authenticated(self) -> bool:
        password = auth_password()
        if not password:
            return True
        return cookie_value(self.headers.get("Cookie", ""), AUTH_COOKIE) == auth_token()

    def session_id(self) -> str:
        current = safe_session_id(cookie_value(self.headers.get("Cookie", ""), SESSION_COOKIE))
        if current:
            return current
        if not hasattr(self, "_new_session_id"):
            self._new_session_id = secrets.token_urlsafe(24)
        return self._new_session_id

    def session_dir(self) -> Path:
        path = SESSIONS / self.session_id()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def session_photos_dir(self) -> Path:
        path = self.session_dir() / "photos"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def session_output_dir(self) -> Path:
        path = self.session_dir() / "output"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def session_template_path(self) -> Path:
        return self.session_dir() / "template.json"

    def active_template_path(self) -> Path:
        session_template = self.session_template_path()
        return session_template if session_template.exists() else TEMPLATE_PATH

    def active_photos(self, fallback: Path | None = None) -> list[Path]:
        session_photos = photo_files(self.session_photos_dir())
        if session_photos:
            return session_photos
        return photo_files(fallback or DEFAULT_PHOTOS)

    def ensure_session_cookie_header(self) -> None:
        if hasattr(self, "_new_session_id"):
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={self._new_session_id}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800",
            )

    def auth_required_response(self, api: bool = False) -> bool:
        if self.is_authenticated():
            return False
        if api:
            self.send_json({"error": "Acesso bloqueado. Faça login primeiro."}, status=401)
        else:
            self.send_response(302)
            self.send_header("Location", "/login.html")
            self.end_headers()
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path != "/login.html" and self.auth_required_response(api=parsed.path.startswith("/api/")):
                return
            if parsed.path == "/api/status":
                session_photos = photo_files(self.session_photos_dir())
                fallback_photos = photo_files(DEFAULT_PHOTOS)
                photos = session_photos or fallback_photos
                template_path = self.active_template_path()
                self.send_json(
                    {
                        "pdfs": {key: str(path.relative_to(ROOT)) for key, path in DEFAULT_PDFS.items() if path.exists()},
                        "photosFolder": str(DEFAULT_PHOTOS.relative_to(ROOT)),
                        "sessionId": self.session_id(),
                        "usingSessionPhotos": bool(session_photos),
                        "sessionPhotoCount": len(session_photos),
                        "photoCount": len(photos),
                        "photos": [p.name for p in photos],
                        "hasTemplate": template_path.exists(),
                        "template": json.loads(template_path.read_text(encoding="utf-8")) if template_path.exists() else None,
                    }
                )
                return
            if parsed.path == "/api/preview":
                query = parse_qs(parsed.query)
                pdf_key = clean_name(query.get("pdf", ["figurinhas"])[0])
                page_number = int(query.get("page", ["1"])[0])
                zoom = min(3, max(0.5, float(query.get("zoom", ["1.5"])[0])))
                pdf_path = DEFAULT_PDFS.get(pdf_key)
                if not pdf_path or not pdf_path.exists():
                    self.send_error(HTTPStatus.NOT_FOUND, "PDF não encontrado")
                    return
                doc = fitz.open(pdf_path)
                try:
                    page = doc[page_number - 1]
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                    body = pix.tobytes("png")
                finally:
                    doc.close()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/photo":
                query = parse_qs(parsed.query)
                folder = safe_project_path(query.get("folder", [str(DEFAULT_PHOTOS.relative_to(ROOT))])[0], DEFAULT_PHOTOS)
                photos = self.active_photos(folder)
                if not photos:
                    self.send_error(HTTPStatus.NOT_FOUND, "Nenhuma foto encontrada")
                    return
                index = int(query.get("index", ["0"])[0]) % len(photos)
                target = photos[index]
                body = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "image/jpeg")
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path.startswith("/api/download/"):
                name = Path(unquote(parsed.path.split("/")[-1])).name
                target = self.session_output_dir() / name
                if not target.exists():
                    self.send_error(HTTPStatus.NOT_FOUND, "Arquivo não encontrado")
                    return
                content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                body = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
                self.ensure_session_cookie_header()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/login":
                payload = self.read_json()
                password = auth_password()
                if not password:
                    self.send_json({"ok": True})
                    return
                if payload.get("password") != password:
                    self.send_json({"error": "Senha incorreta."}, status=401)
                    return
                self.send_response(200)
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header(
                    "Set-Cookie",
                    f"{AUTH_COOKIE}={auth_token()}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400",
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/api/logout":
                self.send_response(200)
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"{AUTH_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.auth_required_response(api=True):
                return
            if self.path == "/api/analyze":
                payload = self.read_json()
                paths = {
                    "figurinhas": safe_project_path(payload.get("figurinhasPdf"), DEFAULT_PDFS["figurinhas"]),
                    "album": safe_project_path(payload.get("albumPdf"), DEFAULT_PDFS["album"]),
                }
                for path in paths.values():
                    if not path.exists():
                        raise FileNotFoundError(f"PDF não encontrado: {path.name}")
                template = build_template(paths)
                self.session_template_path().write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
                self.send_json({"template": template})
                return
            if self.path == "/api/template":
                payload = self.read_json()
                template = payload.get("template", payload)
                self.session_template_path().write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
                self.send_json({"ok": True, "path": "session/template.json"})
                return
            if self.path == "/api/upload-photos":
                payload = self.read_json()
                photos_payload = payload.get("photos") or []
                if not isinstance(photos_payload, list) or not photos_payload:
                    raise ValueError("Envie pelo menos uma foto.")
                photos_dir = self.session_photos_dir()
                for old in photos_dir.iterdir():
                    if old.is_file():
                        old.unlink()
                saved = []
                for index, item in enumerate(photos_payload, start=1):
                    original_name = Path(str(item.get("name") or f"foto-{index}.jpg")).name
                    content_type, data = decode_data_url(str(item.get("data") or ""))
                    ext = mimetypes.guess_extension(content_type) or Path(original_name).suffix or ".jpg"
                    if ext.lower() not in IMAGE_EXTS:
                        ext = ".jpg"
                    target = photos_dir / f"{index:03d}-{clean_name(Path(original_name).stem) or 'foto'}{ext.lower()}"
                    target.write_bytes(data)
                    saved.append(target.name)
                self.send_json({"ok": True, "photoCount": len(saved), "photos": saved})
                return
            if self.path == "/api/sample-background":
                payload = self.read_json()
                field = payload.get("field") or {}
                pdf_key = clean_name(field.get("pdf") or payload.get("pdf") or "figurinhas")
                if pdf_key not in DEFAULT_PDFS:
                    raise ValueError("PDF inválido para capturar fundo.")
                page_number = int(field.get("page") or payload.get("page") or 1)
                self.send_json({"color": sample_background(pdf_key, page_number, field)})
                return
            if self.path == "/api/generate":
                payload = self.read_json()
                template = payload.get("template")
                if not template:
                    template_path = self.active_template_path()
                    if not template_path.exists():
                        raise FileNotFoundError("Analise os PDFs ou salve um template antes de gerar.")
                    template = json.loads(template_path.read_text(encoding="utf-8"))
                folder = safe_project_path(payload.get("photosFolder"), DEFAULT_PHOTOS)
                photos = self.active_photos(folder)
                output_dir = self.session_output_dir()
                mode = payload.get("mode", "final")
                base_mode = mode == "base"
                suffix = "base_editavel" if base_mode else "final"
                outputs = {
                    "figurinhas": output_dir / f"figurinhas_{suffix}.pdf",
                    "album": output_dir / f"album_{suffix}.pdf",
                }
                render_pdf(DEFAULT_PDFS["figurinhas"], outputs["figurinhas"], template.get("fields", []), "figurinhas", photos, payload, base_mode)
                render_pdf(DEFAULT_PDFS["album"], outputs["album"], template.get("fields", []), "album", photos, payload, base_mode)
                if base_mode:
                    self.session_template_path().write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
                zip_path = output_dir / f"pdfs_{suffix}.zip"
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for output in outputs.values():
                        zf.write(output, output.name)
                    template_path = self.active_template_path()
                    if template_path.exists():
                        zf.write(template_path, "template.json")
                self.send_json(
                    {
                        "ok": True,
                        "files": [f"/api/download/{path.name}" for path in outputs.values()],
                        "zip": f"/api/download/{zip_path.name}",
                    }
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    STATIC.mkdir(exist_ok=True)
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Aplicação em http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
