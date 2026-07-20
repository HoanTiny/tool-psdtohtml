"""
Phat hien OVERLAY CO DINH (fixed) - phan lap lai giua cac section.

Boi canh: khi design gui moi section 1 file PSD, cac phan chung nhu THANH DIEU
HUONG (logo + menu doc + icon chuot) thuong duoc dat trong TUNG file -> sau khi
ghep, no lap lai o moi section. Thuc te day la 1 thanh co dinh, phai render 1 LAN
(position:fixed), khong phai moi section 1 ban.

Cach phat hien: 1 phan tu co dinh xuat hien o NHIEU section tai GAN cung vi tri
tuong doi trong section (x, y so voi dau section) + cung kich thuoc + nhin giong
nhau (average-hash). Vi design dat tay thuong lech vai px giua cac section, ta
GOM CUM THEO SAI SO (tolerance) chu khong lam tron cung. Nen toan trang bi loai
truoc (cung kich thuoc nhung khac noi dung tung section).
"""

import math
from pathlib import Path

from .sectionize import is_background


def _ahash(path, size=8):
    """Average-hash 64-bit cua 1 anh (de so 2 anh co 'giong nhau' khong)."""
    from PIL import Image
    im = Image.open(path).convert("L").resize((size, size))
    px = list(im.getdata())
    avg = sum(px) / len(px)
    bits = 0
    for i, p in enumerate(px):
        if p >= avg:
            bits |= (1 << i)
    return bits


def _hamming(a, b):
    return bin(a ^ b).count("1")


def _median(vals):
    s = sorted(vals)
    return s[len(s) // 2]


def detect_fixed_overlay(out_dir, layout, pos_tol=16, size_tol=6,
                         ahash_tol=16, min_frac=0.6):
    """
    Tim cac layer lap lai giua cac section (nav/logo co dinh).

    Tra ve (fixed_items, drop_ids):
      fixed_items : list dict {id,asset,x,y,w,h,o,blend,alt,href} - render 1 LAN,
                    toa do y la vi tri TRONG section (y - section.y0).
      drop_ids    : set id can BO khoi luong render thuong (moi ban trung).

    Chi hoat dong khi layout co >=2 section (field 'sections').
    """
    sections = layout.get("sections")
    if not sections or len(sections) < 2:
        return [], set()

    out_dir = Path(out_dir)
    cw, ch = layout["canvas"]["width"], layout["canvas"]["height"]
    n = len(sections)

    def sec_of(l):
        cy = l["bbox"]["y"] + l["bbox"]["height"] / 2
        for i, s in enumerate(sections):
            if s["y0"] <= cy < s["y1"]:
                return i
        return None

    # Ung vien: layer foreground (khong phai nen) co asset.
    cands = []
    for l in layout["layers"]:
        if l.get("kind") == "group" or not l.get("asset"):
            continue
        if is_background(l, cw, ch):
            continue
        si = sec_of(l)
        if si is None:
            continue
        b = l["bbox"]
        cands.append({"l": l, "si": si, "x": b["x"], "y": b["y"] - sections[si]["y0"],
                      "w": b["width"], "h": b["height"]})

    # Gom cum THEO SAI SO (khong lam tron cung -> chiu duoc lech vai px).
    clusters = []
    for c in cands:
        hit = None
        for cl in clusters:
            if (abs(c["x"] - cl["x"]) <= pos_tol and abs(c["y"] - cl["y"]) <= pos_tol
                    and abs(c["w"] - cl["w"]) <= max(size_tol, cl["w"] * 0.15)
                    and abs(c["h"] - cl["h"]) <= max(size_tol, cl["h"] * 0.15)):
                hit = cl
                break
        if hit:
            hit["members"].append(c)
        else:
            clusters.append({"x": c["x"], "y": c["y"], "w": c["w"], "h": c["h"],
                             "members": [c]})

    threshold = max(2, math.ceil(n * min_frac))
    fixed_items, drop_ids = [], set()
    for cl in clusters:
        members = cl["members"]
        secset = {m["si"] for m in members}
        if len(secset) < threshold:            # chua du so section -> khong co dinh
            continue
        # Xac nhan cac ban NHIN GIONG NHAU (loai trang tri rieng section trung vi tri).
        try:
            hs = [_ahash(out_dir / m["l"]["asset"]) for m in members]
            ref = hs[0]
            if sum(1 for h in hs if _hamming(ref, h) <= ahash_tol) < len(hs) * 0.6:
                continue
        except Exception:
            pass

        # Vi tri dai dien = trung vi (bo qua ban lech cua 1 section).
        mx, my = _median([m["x"] for m in members]), _median([m["y"] for m in members])
        rep = min(members, key=lambda m: abs(m["x"] - mx) + abs(m["y"] - my))
        rl = rep["l"]
        alt = ""
        if rl.get("text") and rl["text"].get("content"):
            alt = rl["text"]["content"]
        else:
            alt = rl.get("name", "")

        # lazy import de tranh vong lap import voi render_slices
        from .render_slices import _is_interactive
        fixed_items.append({
            "id": rl["id"], "asset": rl["asset"],
            "x": mx, "y": my, "w": rep["w"], "h": rep["h"],
            "o": rl.get("opacity", 1), "blend": rl.get("blend"),
            "alt": alt, "href": "#" if _is_interactive(rl) else None,
        })
        for m in members:
            drop_ids.add(m["l"]["id"])

    fixed_items.sort(key=lambda it: (it["y"], it["x"]))
    return fixed_items, drop_ids
