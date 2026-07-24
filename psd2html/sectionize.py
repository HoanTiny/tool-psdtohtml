"""
Tach 1 trang PSD dai thanh nhieu SECTION theo chieu doc.

Vi sao: trang landing co the cao vai nghin px, 300+ layer. Nhoi het vao 1 lan
goi AI se bi cat output va chat luong kem. Ta cat thanh cac section nho, chuyen
tung section roi ghep lai.

Cach cat: chieu tat ca layer (tru layer nen cao toan trang) len truc Y de biet
dong nao 'co noi dung', dong nao 'trong'. Cac dai trong (gap) du dai chinh la
ranh gioi giua cac section - giong khoang cach ma mat nguoi nhin thay.
"""


def _leaf_layers(layout):
    """Lay cac layer thuc su ve duoc (bo group)."""
    return [l for l in layout["layers"] if l.get("kind") != "group"]


def is_background(layer, canvas_w, canvas_h):
    """
    Doan 1 layer co phai la NEN trang tri khong (de tach khoi foreground).
    Nen = KHONG phai chu, va co it nhat 1 dau hieu 'to bao trum':
      - cao >= 50% trang, HOAC
      - rong >= 85% trang, HOAC
      - dien tich >= 20% ca trang.
    Nho vay dai lua/hoa van nen bi gom vao anh nen, con nhan vat/nut/icon o lai foreground.
    """
    if layer.get("kind") == "type":
        return False
    b = layer["bbox"]
    w, h = b["width"], b["height"]
    area = w * h
    return (
        h >= 0.5 * canvas_h
        or w >= 0.85 * canvas_w
        or area >= 0.20 * canvas_w * canvas_h
    )


def _sections_from_bands(layout, bands):
    """
    Tao section tu ranh gioi TUONG MINH (bands = [{name, y0, y1}, ...]).
    Dung khi moi section la 1 file PSD rieng (xem merge.py) - khong can doan gap.
    Giu nguyen dinh dang tra ve nhu split_sections de downstream dung chung.
    """
    canvas_w = layout["canvas"]["width"]
    canvas_h = layout["canvas"]["height"]
    leaves = _leaf_layers(layout)
    backgrounds, content = [], []
    for l in leaves:
        (backgrounds if is_background(l, canvas_w, canvas_h) else content).append(l)

    sections = []
    for band in bands:
        y0, y1 = band["y0"], band["y1"]
        sec_layers = []
        for l in content:
            cy = l["bbox"]["y"] + l["bbox"]["height"] / 2
            if y0 <= cy < y1:
                nl = dict(l)
                nb = dict(l["bbox"])
                nb["y"] = nb["y"] - y0  # doi toa do ve goc section
                nl["bbox"] = nb
                sec_layers.append(nl)
        sections.append({
            "index": len(sections),
            "y0": y0,
            "y1": y1,
            "height": y1 - y0,
            "name": band.get("name"),
            "layers": sec_layers,
            "backgrounds": backgrounds,
        })
    return sections


def _bands_from_horizontal_guides(layout, target_h):
    """
    Doi horizontal guide cua Photoshop thanh ranh gioi section.

    Bo guide qua sat mep/qua sat guide truoc de tranh nham guide can chu,
    baseline... la section. Landing dai thuong dat guide section cach nhau
    hang tram pixel.
    """
    canvas_h = int(layout["canvas"]["height"])
    raw = (layout.get("guides") or {}).get("horizontal") or []
    try:
        positions = sorted({
            int(round(float(y))) for y in raw if 0 < float(y) < canvas_h
        })
    except (TypeError, ValueError):
        return []

    min_section_h = max(240, min(int(target_h) // 3, canvas_h // 12))
    cuts = [0]
    for y in positions:
        if y - cuts[-1] >= min_section_h:
            cuts.append(y)
    if len(cuts) == 1:
        return []
    if canvas_h - cuts[-1] < min_section_h:
        cuts.pop()
    cuts.append(canvas_h)
    if len(cuts) < 3:
        return []

    return [
        {"name": f"Section {i + 1}", "y0": cuts[i], "y1": cuts[i + 1]}
        for i in range(len(cuts) - 1)
    ]


def split_sections(layout, target_h=1300, min_gap=25, bg_ratio=0.6):
    """
    Tra ve danh sach section, moi section:
      {
        "index": 0,
        "y0": 0, "y1": 1236,          # toa do tren trang goc
        "height": 1236,
        "name": "hero" | None,        # ten section (neu chia san tu file)
        "layers": [ ... ],            # layer thuoc section (toa do y da doi ve goc section)
        "backgrounds": [ ... ],       # layer nen cao toan trang (dung chung)
      }

    target_h : chieu cao mong muon moi section (px) - dung de gop gap nho.
    min_gap  : dai toi thieu cua 1 dai trong de tinh la ranh gioi.
    bg_ratio : layer cao hon ty le nay so voi trang -> coi la nen toan trang.

    Neu layout co field "sections" (moi section = 1 file PSD, xem merge.py) thi
    DUNG DUNG ranh gioi do - khong doan gap nua.
    """
    explicit = layout.get("sections")
    if explicit:
        return _sections_from_bands(layout, explicit)

    guide_bands = _bands_from_horizontal_guides(layout, target_h)
    if guide_bands:
        return _sections_from_bands(layout, guide_bands)

    canvas_h = layout["canvas"]["height"]
    leaves = _leaf_layers(layout)

    # Tach layer nen ra rieng (khong dung de tim gap, se ghep thanh anh nen)
    canvas_w = layout["canvas"]["width"]
    backgrounds, content = [], []
    for l in leaves:
        if is_background(l, canvas_w, canvas_h):
            backgrounds.append(l)
        else:
            content.append(l)

    # Dem so layer phu len tung dong y (mat do noi dung theo chieu doc)
    density = [0] * (canvas_h + 1)
    for l in content:
        y0 = max(0, l["bbox"]["y"])
        y1 = min(canvas_h, l["bbox"]["y"] + l["bbox"]["height"])
        for y in range(y0, y1):
            density[y] += 1

    # Chia trang thanh ~n_cuts doan; moi diem cat 'ly tuong' nan ve dong
    # co mat do thap nhat trong cua so lan can -> tranh cat ngang qua noi dung.
    import math
    n_sections = max(1, math.ceil(canvas_h / target_h))
    window = max(min_gap, target_h // 4)

    merged = [0]
    for i in range(1, n_sections):
        ideal = round(canvas_h * i / n_sections)
        lo = max(merged[-1] + 1, ideal - window)
        hi = min(canvas_h - 1, ideal + window)
        if lo >= hi:
            cut = ideal
        else:
            # dong co mat do nho nhat; hoa nhau thi gan 'ideal' nhat
            cut = min(range(lo, hi), key=lambda y: (density[y], abs(y - ideal)))
        merged.append(cut)
    merged.append(canvas_h)

    # Tao section tu cac moc cat
    sections = []
    for i in range(len(merged) - 1):
        y0, y1 = merged[i], merged[i + 1]
        sec_layers = []
        for l in content:
            cy = l["bbox"]["y"] + l["bbox"]["height"] / 2  # tam theo chieu doc
            if y0 <= cy < y1:
                nl = dict(l)
                nb = dict(l["bbox"])
                nb["y"] = nb["y"] - y0  # doi toa do ve goc section
                nl["bbox"] = nb
                sec_layers.append(nl)
        if not sec_layers:
            continue
        sections.append({
            "index": len(sections),
            "y0": y0,
            "y1": y1,
            "height": y1 - y0,
            "name": None,
            "layers": sec_layers,
            "backgrounds": backgrounds,
        })
    return sections
