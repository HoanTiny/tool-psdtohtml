"""Doc tai lieu BA va chuyen thanh flow-spec co the review.

MVP dung heuristic quy tac, khong tu bia endpoint hay nghiep vu. Ket qua luon
duoc frontend cho nguoi dung duyet truoc khi ghi vao edits.json.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree


SUPPORTED_EXTENSIONS = {".txt", ".md", ".docx", ".xlsx", ".pdf"}
MAX_TEXT_CHARS = 160_000
MAX_REQUIREMENTS = 120
MAX_XML_BYTES = 8 * 1024 * 1024


class BAFlowError(ValueError):
    pass


def _plain(value):
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def normalize_name(value):
    return _plain(value)


def _slug(value):
    return re.sub(r"\s+", "-", _plain(value)).strip("-")[:60] or "target"


def _xml_text(data):
    root = ElementTree.fromstring(data)
    parts = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] in {"t", "v"} and node.text:
            parts.append(node.text)
        elif node.tag.rsplit("}", 1)[-1] in {"p", "row"}:
            parts.append("\n")
    return " ".join(parts).replace(" \n ", "\n")


def _zip_read_limited(archive, name):
    info = archive.getinfo(name)
    if info.file_size > MAX_XML_BYTES:
        raise BAFlowError("Tai lieu Office co noi dung qua lon.")
    return archive.read(info)


def _read_docx(path):
    with zipfile.ZipFile(path) as archive:
        try:
            return _xml_text(_zip_read_limited(archive, "word/document.xml"))
        except KeyError as exc:
            raise BAFlowError("File DOCX khong co noi dung hop le.") from exc


def _read_xlsx(path):
    rows = []
    with zipfile.ZipFile(path) as archive:
        shared = []
        try:
            shared_xml = _zip_read_limited(archive, "xl/sharedStrings.xml")
            shared_root = ElementTree.fromstring(shared_xml)
            for item in shared_root:
                shared.append("".join(
                    node.text or "" for node in item.iter()
                    if node.tag.rsplit("}", 1)[-1] == "t"
                ))
        except KeyError:
            pass
        sheets = sorted(
            name for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        for sheet in sheets:
            root = ElementTree.fromstring(_zip_read_limited(archive, sheet))
            for row in root.iter():
                if row.tag.rsplit("}", 1)[-1] != "row":
                    continue
                cells = []
                for cell in row:
                    if cell.tag.rsplit("}", 1)[-1] != "c":
                        continue
                    kind = cell.attrib.get("t")
                    value = next((
                        node.text or "" for node in cell.iter()
                        if node.tag.rsplit("}", 1)[-1] in {"v", "t"}
                    ), "")
                    if kind == "s" and value.isdigit():
                        index = int(value)
                        value = shared[index] if index < len(shared) else value
                    if value.strip():
                        cells.append(value.strip())
                if cells:
                    rows.append(" | ".join(cells))
    return "\n".join(rows)


def _read_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise BAFlowError(
            "Can cai pypdf de doc PDF: pip install -r requirements.txt"
        ) from exc
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract_document(path):
    """Tra text sach tu TXT/MD/DOCX/XLSX/PDF."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise BAFlowError(
            "Dinh dang chua ho tro. Dung TXT, MD, DOCX, XLSX hoac PDF."
        )
    if ext in {".txt", ".md"}:
        data = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "cp1258"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("utf-8", errors="replace")
    elif ext == ".docx":
        text = _read_docx(path)
    elif ext == ".xlsx":
        text = _read_xlsx(path)
    else:
        text = _read_pdf(path)
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise BAFlowError("Khong trich xuat duoc noi dung chu tu tai lieu.")
    return text[:MAX_TEXT_CHARS]


def _requirements(text):
    chunks = []
    for raw in text.splitlines():
        raw = re.sub(r"^[\s\-*+\d.)]+", "", raw).strip()
        if not raw:
            continue
        chunks.extend(part.strip() for part in re.split(r"(?<=[.!?;])\s+", raw))
    seen = set()
    out = []
    action_words = (
        "bấm", "nhấn", "click", "chọn", "mở", "popup", "modal",
        "url", "link", "cuộn", "scroll", "section", "đi tới", "chuyển tới",
    )
    for chunk in chunks:
        key = _plain(chunk)
        if len(key) < 5 or not any(_plain(word) in key for word in action_words):
            continue
        if key not in seen:
            seen.add(key)
            out.append(chunk[:500])
        if len(out) >= MAX_REQUIREMENTS:
            break
    return out


def _trigger_hint(requirement):
    match = re.search(
        r"(?:bấm|nhấn|click|chọn)\s+(?:vào\s+)?(?:nút|button|layer)?\s*"
        r"[\"“']?(.+?)[\"”']?\s*(?:,|:|->|=>|\bđể\b|\bsẽ\b|\bthì\b|\bmở\b|"
        r"\bđi\b|\bchuyển\b|\bcuộn\b|$)",
        requirement,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(" \"“”':,-")[:100]
    return requirement[:100]


def _best_named(hint, entries, name_key="name"):
    hint_n = _plain(hint)
    hint_tokens = set(hint_n.split())
    best, best_score = None, 0.0
    for entry in entries:
        name = str(entry.get(name_key) or entry.get("id") or "")
        name_n = _plain(name)
        if not name_n:
            continue
        seq = SequenceMatcher(None, hint_n, name_n).ratio()
        tokens = set(name_n.split())
        overlap = len(hint_tokens & tokens) / max(1, len(tokens))
        contains = 1.0 if name_n in hint_n or hint_n in name_n else 0.0
        score = max(seq, overlap * 0.92, contains * 0.96)
        if score > best_score:
            best, best_score = entry, score
    return best, best_score


def _detect_action(requirement, sections, popups):
    plain = _plain(requirement)
    url = re.search(r"https?://[^\s<>\"]+", requirement, re.IGNORECASE)
    if url:
        return "url", url.group(0).rstrip(".,);"), True
    if any(word in plain for word in ("popup", "modal", "hop thoai", "hien thi")):
        target, score = _best_named(requirement, popups)
        return "popup", (target or {}).get("id", ""), score >= 0.35
    if any(word in plain for word in (
        "cuon", "scroll", "di toi", "chuyen toi", "xuong muc", "toi section"
    )):
        target, score = _best_named(requirement, sections)
        index = sections.index(target) if target in sections else -1
        return "scroll", str(index) if index >= 0 else "", score >= 0.3
    return None, "", False


_USECASE_FIELDS = {
    "name": ("ten use case", "ten usecase", "ten chuc nang"),
    "actor": ("tac nhan",),
    "detail": ("chi tiet", "mo ta"),
    "preconditions": ("tien dieu kien", "dieu kien truoc"),
    "postconditions": ("hau dieu kien", "dieu kien sau"),
    "trigger": ("diem kich hoat", "su kien kich hoat"),
    "main_flow": ("luong su kien chinh", "luong nghiep vu", "luong chinh"),
    "alternative_flow": ("luong su kien thay the", "luong thay the"),
    "exceptions": ("luong su kien ngoai le", "ngoai le"),
    "rules": ("quy dinh he thong", "quy tac nghiep vu"),
}


def _field_value(lines, aliases):
    aliases = tuple(_plain(alias) for alias in aliases)
    for index, line in enumerate(lines):
        plain = _plain(line)
        for alias in aliases:
            if plain == alias or plain.startswith(alias + " "):
                value = line[len(line) - max(0, len(line) - len(alias)):].strip(" |:-")
                if _plain(value).startswith(alias):
                    value = value[len(alias):].strip(" |:-")
                if value:
                    return value[:2000]
                if index + 1 < len(lines):
                    return lines[index + 1].strip(" |:-")[:2000]
    return ""


def _structured_features(text):
    """Gom cac khoi FT_xxx va cac truong Use Case thuong gap trong tai lieu BA."""
    features = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.search(r"\bFT[\s_-]?(\d{2,4})\b", line, re.IGNORECASE)
        if match:
            code = f"FT_{int(match.group(1)):03d}"
            current = features.setdefault(code, {"code": code, "lines": []})
            heading = re.sub(
                r"^.*?\bFT[\s_-]?\d{2,4}\b[\s.:\-]*", "", line,
                flags=re.IGNORECASE,
            ).strip()
            heading = re.sub(r"^(luồng|chức năng)\s+", "", heading, flags=re.IGNORECASE)
            if heading and not current.get("heading"):
                current["heading"] = heading[:180]
        if current:
            current["lines"].append(line)

    out = []
    for feature in features.values():
        lines = feature.pop("lines")
        for field, aliases in _USECASE_FIELDS.items():
            feature[field] = _field_value(lines, aliases)
        if not feature.get("name"):
            feature["name"] = feature.get("heading") or feature["code"]
        feature["source_section"] = feature["code"]
        feature["raw_preview"] = "\n".join(lines)[:2400]
        out.append(feature)
    return out


def _structured_action(feature, sections, popups):
    trigger = feature.get("trigger") or feature.get("name") or ""
    flow = " ".join((
        feature.get("main_flow") or "",
        feature.get("detail") or "",
        feature.get("postconditions") or "",
    ))
    plain = _plain(" ".join((feature.get("name") or "", trigger, flow)))
    urls = [
        url.rstrip(".,);")
        for url in re.findall(r"https?://[^\s<>\"]+", flow, re.IGNORECASE)
    ]
    popup, popup_score = _best_named(
        " ".join((feature.get("name") or "", trigger)), popups
    )
    if popup and popup_score >= 0.35 and any(
        word in plain for word in ("popup", "modal", "hien thi man hinh")
    ):
        return "popup", popup.get("id", ""), True
    navigation = re.search(
        r"(?:chuyển sang|đi tới|redirect|mở trang|mở link)[^.\n]{0,160}"
        r"(https?://[^\s<>\"]+)",
        flow, re.IGNORECASE,
    )
    if navigation:
        return "url", navigation.group(1).rstrip(".,);"), True
    if any(word in plain for word in (
        "cuon", "scroll", "di toi section", "chuyen toi section"
    )):
        target, score = _best_named(
            " ".join((feature.get("name") or "", flow)), sections
        )
        index = sections.index(target) if target in sections else -1
        return "scroll", str(index) if index >= 0 else "", score >= 0.3
    if popup and popup_score >= 0.35:
        return "popup", popup.get("id", ""), True
    if any(word in plain for word in ("popup", "modal", "hop thoai")):
        return "popup", "", False
    return None, "", False


def _make_item(index, requirement, hint, action, target, target_ok, layers,
               feature=None):
    layer, layer_score = _best_named(hint, layers)
    confidence = round(min(0.99, layer_score * (1.0 if target_ok else 0.72)), 2)
    status = "proposed" if layer and target_ok and confidence >= 0.45 else "review"
    item = {
        "id": f"req-{index:03d}",
        "requirement": requirement[:500],
        "trigger": hint[:160],
        "action": action,
        "target": target,
        "layer_id": (layer or {}).get("id", ""),
        "layer_name": (layer or {}).get("name", ""),
        "confidence": confidence,
        "status": status,
        "enabled": bool(layer and target_ok),
    }
    if feature:
        item.update({
            "feature_code": feature.get("code"),
            "feature_name": feature.get("name"),
            "actor": feature.get("actor", ""),
            "preconditions": feature.get("preconditions", ""),
            "postconditions": feature.get("postconditions", ""),
            "main_flow": feature.get("main_flow", ""),
            "exceptions": feature.get("exceptions", ""),
            "source_section": feature.get("source_section"),
        })
    return item


def build_flow_spec(text, manifest, source_name):
    """Tao flow-spec: uu tien Use Case FT_xxx, sau do bo sung cau hanh dong le."""
    desktop = (manifest or {}).get("desktop") or {}
    layers = desktop.get("layers") or []
    sections = desktop.get("sections") or []
    popups = ((manifest or {}).get("popups") or []) + (
        (manifest or {}).get("inlinePopups") or []
    )
    items = []
    used = set()

    for feature in _structured_features(text):
        action, target, target_ok = _structured_action(feature, sections, popups)
        if not action:
            action, target, target_ok = "unsupported", "", False
        hint = feature.get("trigger") or feature.get("name") or feature["code"]
        requirement = f"{feature['code']} · {feature.get('name') or hint}"
        item = _make_item(
            len(items) + 1, requirement, hint, action, target, target_ok,
            layers, feature=feature,
        )
        items.append(item)
        used.add((item["action"], item["target"], normalize_name(item["layer_name"])))

    for requirement in _requirements(text):
        action, target, target_ok = _detect_action(requirement, sections, popups)
        if not action:
            continue
        hint = _trigger_hint(requirement)
        item = _make_item(
            len(items) + 1, requirement, hint, action, target, target_ok, layers
        )
        key = (item["action"], item["target"], normalize_name(item["layer_name"]))
        if key in used:
            continue
        used.add(key)
        items.append(item)
        if len(items) >= MAX_REQUIREMENTS:
            break
    return {
        "version": 2,
        "source": source_name,
        "source_text_preview": text[:1200],
        "items": items,
        "summary": {
            "requirements": len(items),
            "structured": sum(bool(item.get("feature_code")) for item in items),
            "unsupported": sum(item["action"] == "unsupported" for item in items),
            "proposed": sum(item["status"] == "proposed" for item in items),
            "needs_review": sum(item["status"] == "review" for item in items),
        },
    }
