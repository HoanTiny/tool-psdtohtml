"""Phan loai va tach layer dong cho che do Composite + hotspot.

AI chi lam viec ngu nghia: nhan ra so lieu, trang thai, tab va CTA. Python van
quyet dinh toa do tu layout.json va render lai PSD bo cac layer dong, do do nen
phia duoi duoc Photoshop/psd-tools ghep dung thay vi xoa/vay anh bang inpaint.
"""

import base64
import hashlib
import io
import json
import os
import re
import unicodedata
from pathlib import Path

from PIL import Image

from .ai_convert import DEFAULT_MODEL, _load_env

_ROLES = {"dynamic_text", "status", "button", "tab"}
_CLASSIFIER_VERSION = 2

_SYSTEM = """Ban la chuyen gia UI/UX va frontend game landing. Ban nhan anh mot
section PSD va danh sach TEXT LAYER co id/toa do/noi dung/parent path.

Hay CHON BAO THU cac layer can tach khoi anh tinh de noi API hoac tuong tac:
- dynamic_text: so lieu co the doi (tong luot, luot con lai, diem, so nguoi...)
- status: trang thai co the doi (da nhan, chua nhan, het luot...)
- button: CTA bam duoc (nhan luot, quay/vung, nap, tai, dang nhap...)
- tab: tab/chuyen noi dung (lich su, the le, bang xep hang...)

Khong chon logo, tieu de nghe thuat, mo ta va nhan noi dung tinh. Bao thu: neu
khong chac thi bo qua. Chi tra JSON hop le, khong markdown:
{"layers":[{"id":"L1","role":"dynamic_text|status|button|tab","binding":"key_snake_case","action":"action_key_or_empty","reason":"ngan"}]}
"""


def _ascii(value):
    text = str(value or "")
    for _ in range(2):
        try:
            repaired = text.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if repaired == text:
            break
        text = repaired
    text = unicodedata.normalize(
        "NFD", text.replace("\u0111", "d").replace("\u0110", "D"),
    )
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()

def _slug(value):
    text = re.sub(r"[^a-z0-9]+", "_", _ascii(value)).strip("_")
    return text[:48] or "value"


def _text_of(layer):
    return str((layer.get("text") or {}).get("content") or layer.get("name") or "").strip()


def _parent_paths(layout):
    by_id = {layer["id"]: layer for layer in layout.get("layers", [])}
    paths = {}
    for layer in layout.get("layers", []):
        names = []
        current = by_id.get(layer.get("parent"))
        while current and len(names) < 5:
            names.append(str(current.get("name") or current["id"]))
            current = by_id.get(current.get("parent"))
        paths[layer["id"]] = " / ".join(reversed(names))
    return paths


def _fallback_role(layer, task_rank=None):
    """Fallback co dinh cho cac cum pho bien; AI co the bo sung them."""
    raw = _text_of(layer)
    text = _ascii(raw)
    if not text:
        return None
    binding = _slug(raw)
    action = ""
    role = None

    if "da nhan" in text or "chua nhan" in text or "het luot" in text:
        role, action = "status", ""
    elif len(text) <= 36 and ("nhan luot" in text or "nhan qua" in text):
        role, action = "button", "claim"
    elif (("vung riu" in text and re.search(r"x\s*\d+", text)) or "quay x" in text or "quay 1" in text):
        role = "button"
        if "x50" in text or " 50" in text:
            binding, action = "spin_fifty", "spin_50"
        else:
            binding, action = "spin_once", "spin_1"
    elif text.strip() in {"lich su", "the le", "bang xep hang", "phan thuong"}:
        role = "tab"
        action = {"lich su": "history", "the le": "rules"}.get(text.strip(), binding)
    elif (
        re.fullmatch(r"[\d\s.,:/+-]+", text)
        or "luot vung con lai" in text
        or "luot quay con lai" in text
        or "tong diem" in text
        or "so du" in text
    ):
        role = "dynamic_text"
        if "con lai" in text:
            binding = "remaining_spins"
        elif re.fullmatch(r"[\d\s.,]+", text):
            binding = "total_spins"

    if not role:
        return None
    if task_rank is not None and ("nhan luot" in text or "da nhan" in text or "chua nhan" in text):
        binding = f"task_{task_rank}_status"
    return {
        "id": layer["id"], "role": role, "binding": binding,
        "action": action, "reason": "fallback",
    }


def _section_candidates(layout, y0, y1):
    paths = _parent_paths(layout)
    candidates = []
    for layer in layout.get("layers", []):
        if layer.get("kind") != "type" or layer.get("visible", True) is False:
            continue
        bbox = layer.get("bbox") or {}
        cy = bbox.get("y", 0) + bbox.get("height", 0) / 2
        if not (y0 <= cy < y1):
            continue
        text = _text_of(layer)
        if not text:
            continue
        candidates.append({
            "id": layer["id"], "text": text, "name": layer.get("name"),
            "bbox": bbox, "parent_path": paths.get(layer["id"], ""),
        })
    return candidates


def _task_ranks(layout):
    rows = []
    for layer in layout.get("layers", []):
        if layer.get("kind") != "type" or layer.get("visible", True) is False:
            continue
        text = _ascii(_text_of(layer))
        if any(key in text for key in ("nhan luot", "da nhan", "chua nhan")):
            bbox = layer.get("bbox") or {}
            rows.append(round(bbox.get("y", 0) / 12) * 12)
    unique = sorted(set(rows))
    return {value: index + 1 for index, value in enumerate(unique)}


def fallback_classification(layout):
    """Phan loai khong can API, bao thu va co xet context layer cung group."""
    ranks = _task_ranks(layout)
    by_parent = {}
    for layer in layout.get("layers", []):
        if layer.get("kind") == "type":
            by_parent.setdefault(layer.get("parent"), []).append(_ascii(_text_of(layer)))
    result = {}
    for layer in layout.get("layers", []):
        if layer.get("kind") != "type" or layer.get("visible", True) is False:
            continue
        bbox = layer.get("bbox") or {}
        row = round(bbox.get("y", 0) / 12) * 12
        item = _fallback_role(layer, ranks.get(row))
        if not item:
            continue
        raw = _ascii(_text_of(layer))
        if re.fullmatch(r"[\d\s.,:/+-]+", raw):
            context = " ".join(by_parent.get(layer.get("parent"), []))
            dynamic_context = any(key in context for key in (
                "tong luot", "luot vung", "luot quay", "tong diem", "so du",
            ))
            if not dynamic_context:
                continue
        result[layer["id"]] = item
    return result

def _image_b64(image):
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=82, optimize=True)
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


def _extract_json(reply):
    match = re.search(r"\{.*\}", reply, re.S)
    if not match:
        return {}
    return json.loads(match.group(0))


def _classify_ai(client, model, crop, candidates):
    message = client.messages.create(
        model=model,
        max_tokens=2500,
        system=_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": _image_b64(crop),
            }},
            {"type": "text", "text": (
                f"Section {crop.width}x{crop.height}px. Text layers:\n"
                + json.dumps(candidates, ensure_ascii=False)
            )},
        ]}],
    )
    reply = "".join(block.text for block in message.content if block.type == "text")
    return _extract_json(reply), message.usage


def _fingerprint(layout):
    payload = {
        "classifier_version": _CLASSIFIER_VERSION,
        "layers": [
            (layer.get("id"), layer.get("name"), layer.get("bbox"), layer.get("text"))
            for layer in layout.get("layers", [])
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def classify_layout(vdir, layout, board, model=DEFAULT_MODEL, api_key=None):
    """Tra map layer-id -> role. Cache theo fingerprint de khong ton token lap lai."""
    vdir = Path(vdir)
    cache_path = vdir / "hybrid.json"
    fingerprint = _fingerprint(layout)
    _load_env()
    key = None if os.environ.get("PSD2HTML_HYBRID_OFFLINE") == "1" else (api_key or os.environ.get("ANTHROPIC_API_KEY"))
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (cached.get("fingerprint") == fingerprint
                    and (cached.get("mode") == "ai" or not key)):
                return cached.get("layers", {}), cached.get("mode", "cache")
        except Exception:
            pass

    fallback = fallback_classification(layout)
    result = dict(fallback)
    mode = "fallback"
    if key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            screenshot = Image.open(vdir / layout.get("screenshot", "screenshot.png")).convert("RGB")
            sections = board.get("sections") or []
            total_in = total_out = 0
            for index, section in enumerate(sections):
                y0 = int(section.get("y0", 0))
                y1 = int(sections[index + 1].get("y0", board["H"])) if index + 1 < len(sections) else board["H"]
                candidates = _section_candidates(layout, y0, y1)
                if not candidates:
                    continue
                crop = screenshot.crop((0, y0, board["W"], y1))
                data, usage = _classify_ai(client, model, crop, candidates)
                total_in += getattr(usage, "input_tokens", 0)
                total_out += getattr(usage, "output_tokens", 0)
                valid_ids = {item["id"] for item in candidates}
                for item in data.get("layers", []):
                    layer_id = item.get("id")
                    role = item.get("role")
                    if layer_id not in valid_ids or role not in _ROLES:
                        continue
                    base = result.get(layer_id, {"id": layer_id})
                    base.update({
                        "role": role,
                        "binding": _slug(item.get("binding") or base.get("binding") or layer_id),
                        "action": _slug(item.get("action")) if item.get("action") else base.get("action", ""),
                        "reason": str(item.get("reason") or "ai")[:120],
                    })
                    result[layer_id] = base
            mode = "ai"
            print(f"[AI hybrid] Phan loai xong: {len(result)} layer, token in={total_in} out={total_out}")
        except Exception as exc:
            print(f"[AI hybrid] Loi {exc}; dung fallback {len(fallback)} layer")

    cache_path.write_text(json.dumps({
        "fingerprint": fingerprint, "mode": mode, "layers": result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return result, mode


def _source_psd(vdir, layout):
    vdir = Path(vdir)
    source = layout.get("source")
    if not source:
        return None
    if vdir.name == "_mobile":
        job_root, bucket = vdir.parent.parent, "m"
    else:
        job_root, bucket = vdir.parent, "d"
    candidates = [
        job_root / bucket / source,
        vdir / source,
        Path(source),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".psd":
            return candidate
    return None


def _psd_layer_map(psd):
    mapping = {}
    counter = 0

    def walk(container):
        nonlocal counter
        for layer in container:
            counter += 1
            mapping[f"L{counter}"] = layer
            if layer.is_group():
                walk(layer)

    walk(psd)
    return mapping


def render_static_base(vdir, layout, excluded_ids):
    """Chon composite nen an toan cho che do hybrid.

    parser.py da xuat screenshot tu composite da duoc kiem tra. psd-tools co the
    lam mat fill/adjustment layer khi render lai voi layer_filter, vi vay uu tien
    screenshot nay de bao toan giao dien PSD; hybrid van tach du lieu va hotspot
    o lop DOM phia tren.
    """
    if not excluded_ids:
        return None
    original = Path(vdir) / layout.get("screenshot", "screenshot.png")
    if original.exists():
        print("[AI hybrid] Dung composite parser da kiem tra de giu nen PSD.")
        return original.name
    source = _source_psd(vdir, layout)
    if not source:
        return None
    from psd_tools import PSDImage
    from .parser import _overlay_ids

    print(f"[AI hybrid] Render nen tinh, bo {len(excluded_ids)} layer tu {source.name} ...")
    psd = PSDImage.open(source)
    layer_map = _psd_layer_map(psd)
    excluded_objects = {id(layer_map[layer_id]) for layer_id in excluded_ids if layer_id in layer_map}
    overlay = _overlay_ids(psd)
    image = psd.composite(layer_filter=lambda layer: (
        layer.visible and id(layer) not in excluded_objects and id(layer) not in overlay
    ))
    if image is None:
        return None
    # Mot so PSD co fill/adjustment layer khong duoc psd-tools giu lai khi
    # composite co layer_filter. Neu nen bi trang gan het thi dung composite
    # goc da duoc parser xuat, tuyet doi khong xuat mot section trang.
    rgb = image.convert("RGB")
    try:
        import numpy as np
        pixels = np.asarray(rgb)
        mostly_white = (pixels.min(axis=2) > 248).mean() > 0.70
    except Exception:
        mostly_white = False
    original = Path(vdir) / layout.get("screenshot", "screenshot.png")
    if mostly_white and original.exists():
        print("[AI hybrid] Nen render bi trang; dung composite goc an toan.")
        return original.name
    target = Path(vdir) / "hybrid-base.png"
    rgb.save(target, optimize=True)
    return target.name


def prepare_hybrid(vdir, layout, board, model=DEFAULT_MODEL, api_key=None):
    """Gan metadata hybrid vao board va tao composite nen tinh."""
    roles, mode = classify_layout(vdir, layout, board, model=model, api_key=api_key)
    by_id = {layer["id"]: layer for layer in layout.get("layers", [])}
    for layer_id, role in roles.items():
        layer = by_id.get(layer_id, {})
        text = layer.get("text") or {}
        role.update({
            "text": text.get("content") or layer.get("name") or layer_id,
            "font": text.get("font"), "size": text.get("size"),
            "color": text.get("color"), "bbox": layer.get("bbox") or {},
        })
    board["_hybrid_roles"] = roles
    board["hybrid_mode"] = mode
    source = render_static_base(vdir, layout, set(roles))
    if source:
        board["_composite_source"] = source
    else:
        # Khong co PSD nguon thi khong duoc ve text dong de tranh de len text da bake.
        board["_hybrid_roles"] = {}
        board["hybrid_mode"] = "hotspot-only"
    return board