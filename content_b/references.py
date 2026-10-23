"""Local product-reference uploads. Registration is not factual or rights approval."""
import base64
import hashlib
import json
from pathlib import Path
import struct
import uuid
from urllib.parse import urlsplit

from .contracts import ContentError, text, now
from .image_client import png_dimensions

MAX_UPLOAD = 8 * 1024 * 1024


def image_info(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        width, height = png_dimensions(raw)
        return 'png', 'image/png', width, height
    if raw.startswith(b'\xff\xd8') and raw.endswith(b'\xff\xd9'):
        offset = 2
        while offset + 4 <= len(raw):
            if raw[offset] != 255:
                break
            marker = raw[offset + 1]
            offset += 2
            if marker == 255:
                offset -= 1
                continue
            if marker in (0x01, *range(0xD0, 0xD8)):
                continue
            length = struct.unpack('>H', raw[offset:offset + 2])[0]
            if length < 2 or offset + length > len(raw):
                break
            if marker in (0xC0, 0xC1, 0xC2) and length >= 8:
                height, width = struct.unpack('>HH', raw[offset + 3:offset + 7])
                if 0 < width <= 8192 and 0 < height <= 8192 and width * height <= 24_000_000:
                    return 'jpg', 'image/jpeg', width, height
                break
            if marker in (0xDA, 0xD9):
                break
            offset += length
    raise ContentError('REFERENCE_FORMAT', '请上传完整的 PNG 或 JPEG 产品原图。', 422)


def register_reference(media, payload):
    model = text(payload.get('model', ''), 'model', 200, True)
    encoded = payload.get('image_base64', '')
    if not isinstance(encoded, str) or len(encoded) > MAX_UPLOAD * 4 // 3 + 8:
        raise ContentError('REFERENCE_SIZE', '产品原图最大 8MB。', 413)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ContentError('REFERENCE_FORMAT', '产品原图编码无效。', 422) from None
    if not raw or len(raw) > MAX_UPLOAD:
        raise ContentError('REFERENCE_SIZE', '产品原图最大 8MB。', 413)
    extension, mime, width, height = image_info(raw)
    source = text(payload.get('source_ref', ''), 'source_ref', 2000)
    if source:
        parsed = urlsplit(source)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ContentError('REFERENCE_SOURCE', '来源页面须为 HTTPS 地址，也可以留空。', 422)
    reference_id = 'ref-' + uuid.uuid4().hex
    directory = media.media_dir.parent / 'references'
    directory.mkdir(parents=True, exist_ok=True)
    item = {'catalog_id': reference_id, 'product_model': model,
            'url': f'/api/content/references/{reference_id}.{extension}', 'mime_type': mime,
            'source_ref': source, 'source_type': 'user_reference', 'purpose': 'product',
            'rights_status': 'unconfirmed', 'sha256': hashlib.sha256(raw).hexdigest(),
            'width': width, 'height': height, 'created_at': now(),
            'note': '用户为此型号提供的参考原图；型号、来源与授权仍需审核。'}
    (directory / (reference_id + '.' + extension)).write_bytes(raw)
    (directory / (reference_id + '.json')).write_text(json.dumps(item, ensure_ascii=False), encoding='utf-8')
    return item
