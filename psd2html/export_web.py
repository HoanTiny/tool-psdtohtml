"""
Xuat sang du an REACT (Vite) hoac NEXT (app router), Tailwind, chon TS hoac JS.

- Tu phat hien GROUP LAP (7 the diem danh...) -> component render bang .map() + API hooks.
- Chia trang thanh nhieu COMPONENT theo SECTION (components/landing/*) de de maintain.
- Tach san: Stage (responsive), Layer (1 lop anh), Background (nen), va tung repeat item.
- TypeScript: kem types/landing + tsconfig.

Dung:
  from psd2html.export_web import export
  export("output", framework="react", lang="ts", mobile_dir=None)
"""

import json
import re
import shutil
import unicodedata
from collections import defaultdict
from pathlib import Path

from .render_slices import _is_interactive, _content_bottom_from_image, _norm, _action_of
from .sectionize import split_sections


# ================= tien ich =================

def _ascii(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("đ", "d").replace("Đ", "D")


def _pascal(s):
    parts = re.split(r"[^0-9a-zA-Z]+", _ascii(s or ""))
    name = "".join(p[:1].upper() + p[1:] for p in parts if p)
    if not name:
        name = "Item"
    if name[0].isdigit():
        name = "G" + name
    return name


def _slug(s):
    return re.sub(r"[^0-9a-zA-Z]+", "-", _ascii(s or "").lower()).strip("-") or "page"


def _norm_name(name):
    n = (name or "").strip().lower()
    return re.sub(r"\s*copy(\s*\d+)?\s*$", "", n).strip()


def _index(layout):
    by_id = {l["id"]: l for l in layout["layers"]}
    children = defaultdict(list)
    for l in layout["layers"]:
        children[l.get("parent")].append(l["id"])
    return by_id, children


def _leaves(gid, by_id, children):
    out = []
    for cid in children.get(gid, []):
        n = by_id[cid]
        if n.get("kind") == "group":
            out += _leaves(cid, by_id, children)
        elif n.get("asset"):
            out.append(n)
    return out


def _descendant_groups(gid, by_id, children):
    out = []
    for cid in children.get(gid, []):
        if by_id[cid].get("kind") == "group":
            out.append(cid)
            out += _descendant_groups(cid, by_id, children)
    return out


def _alt_of(l):
    if l.get("text") and l["text"].get("content"):
        return _norm(l["text"]["content"])
    return _norm(l.get("name", ""))


def _src(asset, asset_dir):
    return f"/{asset_dir}/{Path(asset).name}"


def _ext(lang):
    return "tsx" if lang == "ts" else "jsx"


def _ann(lang, t):
    return f": {t}" if lang == "ts" else ""


# ================= phat hien group lap =================

def _grid_of(instances, W, H):
    """Suy ra luoi flex-wrap tu vi tri cac instance: goc, gap ngang/doc, so cot.

    Cho phep cum lap render bang display:flex;flex-wrap thay vi tung the absolute
    -> tu xep lai hang khi so item doi hoac man hep (giong ban production)."""
    xs = [it["x"] for it in instances]
    ys = [it["y"] for it in instances]
    x0, y0 = min(xs), min(ys)
    # gom instance theo HANG (tolerance = 40% chieu cao the)
    tol = max(8, H * 0.4)
    rows = []
    for it in sorted(instances, key=lambda i: i["y"]):
        for r in rows:
            if abs(r[0]["y"] - it["y"]) <= tol:
                r.append(it)
                break
        else:
            rows.append([it])
    cols = max(len(r) for r in rows)
    # gap NGANG = trung vi khoang cach 2 the lien tiep trong 1 hang - W
    gxs = []
    for r in rows:
        r.sort(key=lambda i: i["x"])
        for i in range(len(r) - 1):
            g = r[i + 1]["x"] - r[i]["x"] - W
            if g > -4:
                gxs.append(g)
    # gap DOC = trung vi khoang cach 2 hang lien tiep - H
    rys = sorted(min(i["y"] for i in r) for r in rows)
    gys = [rys[i + 1] - rys[i] - H for i in range(len(rys) - 1) if rys[i + 1] - rys[i] - H > -4]
    med = lambda a: round(sorted(a)[len(a) // 2]) if a else 0
    gx = max(0, med(gxs))
    gy = max(0, med(gys)) if gys else gx
    width = cols * W + (cols - 1) * gx
    # co phai LUOI DEU khong? (chi luoi deu moi chuyen flex-wrap an toan)
    # -> moi hang tru hang cuoi phai DAY (= cols), hang cuoi <= cols, cac hang cach deu.
    rows.sort(key=lambda r: min(i["y"] for i in r))
    is_grid = True
    if len(rows) > 1:
        if any(len(r) != cols for r in rows[:-1]) or len(rows[-1]) > cols:
            is_grid = False
        elif len(gys) and (max(gys) - min(gys)) > 0.5 * H + 8:
            is_grid = False   # hang khong cach deu -> so le/zigzag
    return {"x": round(x0), "y": round(y0), "w": round(width),
            "gx": gx, "gy": gy, "cols": cols, "is_grid": is_grid}


def _detect_repeats(layout, ab_bbox, by_id, children, asset_dir="assets"):
    ax, ay = ab_bbox["x"], ab_bbox["y"]
    groups = [l for l in layout["layers"] if l.get("kind") == "group"]
    clusters = defaultdict(list)
    for g in groups:
        b = g["bbox"]
        cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        if not (ax <= cx < ax + ab_bbox["width"] and ay <= cy < ay + ab_bbox["height"]):
            continue
        clusters[(g.get("parent"), _norm_name(g["name"]))].append(g)

    cand = []
    for (parent, nm), members in clusters.items():
        if len(members) < 3:
            continue
        ws = sorted(m["bbox"]["width"] for m in members)
        hs = sorted(m["bbox"]["height"] for m in members)
        medw, medh = ws[len(ws) // 2], hs[len(hs) // 2]
        members = [m for m in members
                   if abs(m["bbox"]["width"] - medw) <= medw * 0.2 + 2
                   and abs(m["bbox"]["height"] - medh) <= medh * 0.2 + 2]
        if len(members) < 3:
            continue
        cand.append((medw * medh, nm, members))
    cand.sort(reverse=True)

    consumed_groups, consumed_leaves, repeats = set(), set(), []
    used_names = {}
    for _, nm, members in cand:
        if any(m["id"] in consumed_groups for m in members):
            continue
        members.sort(key=lambda m: (round(m["bbox"]["y"] / 20), m["bbox"]["x"]))
        inst_leaves = [(m, _leaves(m["id"], by_id, children)) for m in members]
        counts = {len(lv) for _, lv in inst_leaves}
        same = len(counts) == 1 and next(iter(counts)) > 0
        take = inst_leaves if same else inst_leaves[:1]
        aligned = []
        for m, lv in take:
            ox, oy = m["bbox"]["x"], m["bbox"]["y"]
            s = sorted(lv, key=lambda n: (round((n["bbox"]["y"] - oy) / 8), n["bbox"]["x"] - ox))
            aligned.append((m, ox, oy, s))
        if not aligned or len(aligned[0][3]) == 0:
            continue

        comp = _pascal(nm) or "Item"
        used_names[comp] = used_names.get(comp, 0) + 1
        if used_names[comp] > 1:
            comp = f"{comp}{used_names[comp]}"

        tpl_m, tox, toy, tpl_leaves = aligned[0]
        slots, var_idx = [], 0
        for si in range(len(tpl_leaves)):
            tnode = tpl_leaves[si]
            names = [_norm(a[3][si].get("name", "")) for a in aligned] if same else [_norm(tnode.get("name", ""))]
            varying = len(set(names)) > 1
            slot = {
                "rx": tnode["bbox"]["x"] - tox, "ry": tnode["bbox"]["y"] - toy,
                "w": tnode["bbox"]["width"], "h": tnode["bbox"]["height"],
                "o": tnode.get("opacity", 1), "blend": tnode.get("blend"),
                "alt": _alt_of(tnode), "asset": _src(tnode["asset"], asset_dir),
            }
            if _is_interactive(tnode):
                slot["kind"] = "button"
            elif varying:
                slot["kind"], slot["var"] = "var", f"s{var_idx}"
                var_idx += 1
            else:
                slot["kind"] = "static"
            slots.append(slot)

        instances = []
        for (m, ox, oy, s) in aligned:
            vars_ = {slot["var"]: _src(s[si]["asset"], asset_dir)
                     for si, slot in enumerate(slots) if slot["kind"] == "var"}
            instances.append({"id": len(instances) + 1,
                              "x": m["bbox"]["x"] - ax, "y": m["bbox"]["y"] - ay, "vars": vars_})

        repeats.append({"comp": comp, "W": tpl_m["bbox"]["width"], "H": tpl_m["bbox"]["height"],
                        "slots": slots, "instances": instances, "count": len(instances),
                        "grid": _grid_of(instances, tpl_m["bbox"]["width"], tpl_m["bbox"]["height"])})
        for m in members:
            consumed_groups.add(m["id"])
            for gid in _descendant_groups(m["id"], by_id, children):
                consumed_groups.add(gid)
            for lf in _leaves(m["id"], by_id, children):
                consumed_leaves.add(lf["id"])
    return repeats, consumed_leaves


def _detect_menu(layout, ab_bbox, by_id, children):
    ax, ay = ab_bbox["x"], ab_bbox["y"]
    aw, ah = ab_bbox["width"], ab_bbox["height"]

    def inside(b):
        cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        return ax <= cx < ax + aw and ay <= cy < ay + ah

    toggle = None
    for l in layout["layers"]:
        if l.get("kind") == "group" or not l.get("asset"):
            continue
        nm = _norm(l.get("name", ""))
        b = l["bbox"]
        if inside(b) and (("menu" in nm) or ("nut" in nm) or ("ham" in nm)) and b["width"] < 160 and b["height"] < 160:
            if toggle is None or b["y"] < toggle["bbox"]["y"]:
                toggle = l
    if toggle is None:
        return set(), None
    best, best_area = None, 0
    for g in layout["layers"]:
        if g.get("kind") != "group" or "menu" not in _norm(g.get("name", "")):
            continue
        b = g["bbox"]
        area = b["width"] * b["height"]
        if area > best_area and area > 0.1 * aw * ah:
            best, best_area = g, area
    if best is None:
        return set(), None
    ids = {lf["id"] for lf in _leaves(best["id"], by_id, children)}
    ids.discard(toggle["id"])
    return ids, toggle["id"]


def _build_flat(layers, ab_bbox, exclude, asset_dir, menu_ids, toggle_id, fx_auto=False):
    ax, ay = ab_bbox["x"], ab_bbox["y"]
    items = []
    for l in layers:
        if not l.get("asset") or l["id"] in exclude:
            continue
        b = l["bbox"]
        cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        if not (ax <= cx < ax + ab_bbox["width"] and ay <= cy < ay + ab_bbox["height"]):
            continue
        lk = l.get("link") or {}
        tx = l.get("text") or {}
        as_text = bool(tx.get("asText") and tx.get("content"))
        popup = lk.get("popup")   # click layer nay -> mo popup (tu PSD popup)
        is_btn = bool(lk.get("button") or lk.get("url") or lk.get("action") or popup) or _is_interactive(l)
        item = {"id": l["id"], "src": _src(l["asset"], asset_dir),
                "x": b["x"] - ax, "y": b["y"] - ay, "w": b["width"], "h": b["height"],
                "o": l.get("opacity", 1), "blend": l.get("blend"),
                "alt": (l.get("alt") or _alt_of(l)),
                # popup: LUON dat href="#" de click roi vao openAction -> setPopup (khong dieu huong URL)
                "href": ("#" if popup else (lk.get("url") or ("#" if is_btn else None))),
                "act": (("popup:" + str(popup)) if popup
                        else (lk.get("action") or (_action_of(l) if is_btn else None))),
                "t": l.get("kind") == "type"}
        if as_text:   # CHU THAT: render text node thay vi img (tru cot 2)
            item["asText"] = True
            item["text"] = tx.get("content")
            item["tsize"] = tx.get("size")
            item["tcolor"] = tx.get("color")
        if toggle_id and l["id"] == toggle_id:
            item["toggle"] = True
            item["href"] = None
        elif menu_ids and l["id"] in menu_ids:
            item["menu"] = True
        # fx: hieu ung. Editor gan tay (l['fx']) uu tien; neu khong va bat AUTO (fx_auto)
        # thi tu doan: nut -> 'btn'; chu tieu de LON (kind type, cao >= 5% khung) -> 'title'.
        manual_fx = l.get("fx")
        if manual_fx:
            item["fx"] = manual_fx
        elif fx_auto:
            if is_btn:
                item["fx"] = "btn"
            elif l.get("kind") == "type" and b["height"] >= 0.05 * ab_bbox["height"]:
                item["fx"] = "title"
        items.append(item)
    return items


# ================= chia section =================

def _looks_title(alt):
    if not alt or len(alt) > 40:
        return False
    if re.fullmatch(r"[0-9a-f]{6,}.*", alt):   # ten dang hash
        return False
    return bool(re.search(r"[a-zàáâãèéêìíòóôõùúăâêôơưỳý/ ]", alt)) and (" " in alt or len(alt) <= 16)


# Tu khoa nhan dien section landing-game (dang khong dau, viet thuong) -> ten component.
# Quet moi layer chu trong band; khop cum dai truoc (nhieu tu) de uu tien cai cu the hon.
_SECTION_KEYWORDS = [
    ("nap lien tiep", "NapLienTiep"),
    ("nap tich luy", "TichLuyNap"),
    ("nap dung goi", "NapDungGoi"),
    ("nap moc", "MocNap"),
    ("tich luy", "TichLuy"),
    ("diem danh", "DiemDanh"),
    ("dang nhap", "DangNhap"),
    ("vong quay", "VongQuay"),
    ("quay so", "QuaySo"),
    ("mini game", "MiniGame"),
    ("doi qua", "DoiQua"),
    ("doi thuong", "DoiThuong"),
    ("moc thuong", "MocThuong"),
    ("phan thuong", "PhanThuong"),
    ("qua tang", "QuaTang"),
    ("nhan qua", "NhanQua"),
    ("su kien", "SuKien"),
    ("the le", "TheLe"),
    ("huong dan", "HuongDan"),
    ("gioi thieu", "GioiThieu"),
    ("nap the", "NapThe"),
    ("nap", "Nap"),
    ("qua", "Qua"),
]


def _keyword_name(flat):
    """Quet chu trong band tim tu khoa section quen thuoc; None neu khong khop."""
    blob = " ".join(_ascii(it["alt"]).lower() for it in flat if it.get("t") and it.get("alt"))
    for kw, name in _SECTION_KEYWORDS:
        if kw in blob:
            return name
    return None


def _section_name(flat, W, H, y0, y1, idx, used):
    """Dat ten section: (1) tieu de chu noi bat, (2) tu khoa quen thuoc, (3) Section{n}."""
    band_h = max(1, y1 - y0)
    # (1) chi lay LAYER CHU (t=True) lam tieu de section; uu tien o tren cung
    cands = [it for it in flat if it.get("t") and it["y"] < y0 + band_h * 0.6 and _looks_title(it["alt"])]
    cands.sort(key=lambda it: (it["y"], -it["w"]))
    name = _pascal(cands[0]["alt"])[:24] if cands else None
    # (2) khong doan duoc tieu de -> quet tu khoa section trong ca band
    if not name:
        name = _keyword_name(flat)
    # (3) van khong co -> Section{n}
    if not name:
        name = f"Section{idx + 1}"
    base = name
    k = 1
    while name in used:
        k += 1
        name = f"{base}{k}"
    used.add(name)
    return name


def _split_sections(board, layout):
    W, H = board["W"], board["H"]
    flat = board["flat"]
    # nen phu toan trang -> component Background rieng. KHONG dua vao nen (du to/rong):
    # nut bam (href), chu that (asText), va layer CO GAN HIEU UNG (fx) - vi nen render
    # bang <img> thuong, khong qua component Layer nen se MAT hieu ung (float/shine/glow).
    bg = [it for it in flat if (it["h"] >= 0.5 * H or it["w"] >= 0.85 * W)
          and not it.get("href") and not it.get("asText") and not it.get("fx")]
    content = [it for it in flat if it not in bg]
    board["backgrounds"] = bg

    try:
        secs = split_sections(layout)
        bands = [(s["y0"], s["y1"]) for s in secs]
        band_names = [s.get("name") for s in secs]
    except Exception:
        bands, band_names = [(0, H)], [None]
    if not bands:
        bands, band_names = [(0, H)], [None]

    reps = board["repeats"]
    rep_band = {}
    for j, rp in enumerate(reps):
        cy = sorted(inst["y"] + rp["H"] / 2 for inst in rp["instances"])[len(rp["instances"]) // 2]
        rep_band[j] = cy

    sections, used = [], set()
    for i, (y0, y1) in enumerate(bands):
        sflat = [it for it in content if y0 <= it["y"] + it["h"] / 2 < y1]
        sreps = [reps[j] for j in rep_band if y0 <= rep_band[j] < y1]
        if not sflat and not sreps:
            continue
        # Uu tien ten section chia san tu file PSD (merge.py); khong thi doan tieu de.
        # BO QUA ten merge tam thuong (chi chu so, vd file '1.psd'/'2.psd' -> 'G1'/'G2')
        # de con roi ve doan tieu de/tu khoa -> ten co nghia hon.
        explicit = band_names[i] if i < len(band_names) else None
        if explicit and re.fullmatch(r"[\s0-9_.\-]+", explicit or ""):
            explicit = None
        if explicit:
            base = _pascal(explicit)[:24] or f"Section{len(sections) + 1}"
            name, k = base, 1
            while name in used:
                k += 1
                name = f"{base}{k}"
            used.add(name)
        else:
            name = _section_name(sflat, W, H, y0, y1, len(sections), used)
        sections.append({"comp": name, "flat": sflat, "repeats": sreps, "y0": y0})
    # repeat chua gan (hiem) -> section dau
    assigned = {rp["comp"] for s in sections for rp in s["repeats"]}
    leftover = [rp for rp in reps if rp["comp"] not in assigned]
    if leftover:
        if sections:
            sections[0]["repeats"] = leftover + sections[0]["repeats"]
        else:
            sections.append({"comp": "Section1", "flat": [], "repeats": leftover, "y0": 0})
    board["sections"] = sections


def _artboards_from_layout(layout, asset_dir="assets", comp_prefix="", extra_exclude=None,
                           detect_repeats=False, fx_auto=False):
    cw, ch = layout["canvas"]["width"], layout["canvas"]["height"]
    # Loai cac layer da dua vao FixedNav (nav/logo lap) NGAY TU DAU - truoc ca
    # buoc phat hien cum lap. Neu khong, nav se bi nhan nham la 'cum lap' va sinh
    # component lap render nav o moi section (lap lai dung cai da fixed).
    if extra_exclude:
        exset = set(extra_exclude)
        layout = dict(layout)
        layout["layers"] = [l for l in layout["layers"] if l["id"] not in exset]
    by_id, children = _index(layout)
    ab = {"x": 0, "y": 0, "width": cw, "height": ch}
    # MAC DINH render PHANG (moi layer dat tuyet doi = khop thiet ke nhu slices).
    # Chi gom 'cum lap' (.map, API-ready) khi detect_repeats=True: voi landing dày
    # do hoa, cac the/vat pham khac nhau hay bi gom nham -> meo/chong len nhau.
    if detect_repeats:
        repeats, consumed = _detect_repeats(layout, ab, by_id, children, asset_dir)
    else:
        repeats, consumed = [], set()
    menu_ids, toggle_id = _detect_menu(layout, ab, by_id, children)
    flat = _build_flat(layout["layers"], ab, consumed, asset_dir, menu_ids, toggle_id, fx_auto=fx_auto)
    stem = Path(layout.get("source", "Page")).stem
    board = {"comp": comp_prefix + "Landing", "landing_name": comp_prefix + "Landing",
             "W": cw, "H": ch, "flat": flat, "repeats": repeats, "has_menu": bool(toggle_id)}
    return board


# ================= sinh JSX/TSX =================

def _gen_types():
    return (
        "export interface LayerItem {\n"
        "  id: string; src: string; x: number; y: number; w: number; h: number;\n"
        "  o: number; blend?: string | null; alt?: string; cls?: string;\n"
        "  href?: string | null; act?: string | null; menu?: boolean; toggle?: boolean;\n"
        "  asText?: boolean; text?: string; tsize?: number; tcolor?: string; lcp?: boolean; fx?: string;\n}\n\n"
        "export interface FixedItem {\n"
        "  src: string; x: number; y: number; w: number; h: number;\n"
        "  o: number; blend?: string | null; alt?: string; href?: string | null; nav?: number | null;\n}\n\n"
        "export interface SlotItem { src: string; x: number; y: number; w: number; h: number; alt?: string; }\n\n"
        "export interface RepeatItem {\n"
        "  id: number; x: number; y: number; claimed?: boolean; cls?: string;\n"
        "  items?: SlotItem[]; [key: string]: unknown;\n}\n\n"
        "export interface SectionProps {\n"
        "  onClaim?: (id: number) => void; menuOpen?: boolean; onToggleMenu?: () => void;\n}\n"
    )


def _gen_stage(lang, client):
    head = '"use client";\n\n' if client else ""
    # Do bang document.documentElement.clientWidth (be rong viewport, tru scrollbar):
    #   - Khong bi 0 khi component dang bi display:none (bug cu voi el.clientWidth).
    #   - Khong dinh scrollbar (tranh tran ngang nhu window.innerWidth).
    # Khoi tao scale NGAY tu dau (lazy initializer) -> khong nhap nhay tran o lan ve dau.
    if lang == "ts":
        return head + (
            'import { useEffect, useState } from "react";\n'
            'import type { ReactNode } from "react";\n\n'
            "const calc = (w: number) =>\n"
            '  typeof document !== "undefined" ? Math.min(1, document.documentElement.clientWidth / w) : 1;\n\n'
            "export default function Stage({ width, height, children }: "
            "{ width: number; height: number; children: ReactNode }) {\n"
            "  const [scale, setScale] = useState(() => calc(width));\n"
            "  useEffect(() => {\n"
            "    const fit = () => setScale(calc(width));\n"
            "    fit();\n    window.addEventListener('resize', fit);\n"
            "    return () => window.removeEventListener('resize', fit);\n  }, [width]);\n"
            "  return (\n"
            '    <div className="w-full overflow-hidden" style={{ height: height * scale }}>\n'
            '      <div className="relative" style={{ width, height, transformOrigin: "top left", transform: `scale(${scale})` }}>\n'
            "        {children}\n      </div>\n    </div>\n  );\n}\n")
    return head + (
        'import { useEffect, useState } from "react";\n\n'
        "const calc = (w) =>\n"
        '  typeof document !== "undefined" ? Math.min(1, document.documentElement.clientWidth / w) : 1;\n\n'
        "export default function Stage({ width, height, children }) {\n"
        "  const [scale, setScale] = useState(() => calc(width));\n"
        "  useEffect(() => {\n"
        "    const fit = () => setScale(calc(width));\n"
        "    fit();\n    window.addEventListener('resize', fit);\n"
        "    return () => window.removeEventListener('resize', fit);\n  }, [width]);\n"
        "  return (\n"
        '    <div className="w-full overflow-hidden" style={{ height: height * scale }}>\n'
        '      <div className="relative" style={{ width, height, transformOrigin: "top left", transform: `scale(${scale})` }}>\n'
        "        {children}\n      </div>\n    </div>\n  );\n}\n")


def _gen_fixednav(board, lang, client):
    """Component thanh CO DINH (nav/logo): render 1 lan, position:fixed, tu co gian."""
    head = '"use client";\n\n' if client else ""
    W = board["W"]
    data = json.dumps(board["fixed"], ensure_ascii=False, indent=2)
    tpl = r'''import { useEffect, useState } from "react";
__RIMP__
const items__ITEMSANN__ = __DATA__;

// Thanh dieu huong CO DINH - render 1 lan, tu co gian theo be rong man hinh.
const calcNav = () =>
  typeof document !== "undefined" ? Math.min(1, document.documentElement.clientWidth / __W__) : 1;
export default function FixedNav() {
  const [scale, setScale] = useState(calcNav);
  useEffect(() => {
    const fit = () => setScale(calcNav());
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);
  return (
    <div style={{ position: "fixed", top: 0, left: 0, width: "100%", height: 0, zIndex: 1000, pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: 0, left: 0, width: __W__, transformOrigin: "top left", transform: `scale(${scale})` }}>
        {items.map((it, i) => {
          const st__STYLEANN__ = { position: "absolute", left: it.x, top: it.y, width: it.w, height: it.h, opacity: it.o, mixBlendMode: (it.blend || undefined)__BLENDCAST__, pointerEvents: "auto" };
          const isNav = it.nav != null;
          return (isNav || it.href) ? (
            <a key={i} href={it.href || "#"} data-nav={isNav ? it.nav : undefined} className={isNav ? "navitem" : undefined} title={it.alt} style={st}>
              <img src={it.src} alt={it.alt} style={{ width: "100%", height: "100%", display: "block" }} />
            </a>
          ) : (
            <img key={i} src={it.src} alt={it.alt} style={st} />
          );
        })}
      </div>
    </div>
  );
}
'''
    if lang == "ts":
        tpl = (tpl.replace("__RIMP__", 'import type React from "react";\n')
               .replace("__ITEMSANN__", ": FixedItem[]")
               .replace("__STYLEANN__", ": React.CSSProperties")
               .replace("__BLENDCAST__", " as React.CSSProperties[\"mixBlendMode\"]"))
        tpl = ('import type { FixedItem } from "../../types/landing";\n' + tpl)
    else:
        tpl = (tpl.replace("__RIMP__\n", "")
               .replace("__ITEMSANN__", "").replace("__STYLEANN__", "")
               .replace("__BLENDCAST__", ""))
    tpl = tpl.replace("__DATA__", data).replace("__W__", str(W))
    return head + tpl


def _popup_flat(board):
    """Gom TOAN BO layer cua 1 popup board thanh 1 mang phang (toa do tuyet doi trong
    canvas popup): backgrounds (duoi) + flat cac section. Popup la 1 artboard nen toa do
    da tuyet doi (khong tru y0 nhu section trang chinh)."""
    flat = list(board.get("backgrounds", []))
    for s in board.get("sections", []):
        flat += s.get("flat", [])
    return flat


def _popup_sanitize(flat):
    """Layer TRONG popup chi clickable khi co URL that (do user gan). Bo href='#'/act
    suy tu heuristic de KHONG bi document click handler cua Landing mo/dong nham popup."""
    out = []
    for it in flat:
        it = dict(it)
        href = it.get("href")
        if not (href and re.match(r"^https?:", str(href))):
            it.pop("href", None)
        it.pop("act", None)   # popup: khong dung data-action (tranh trung key voi trang chinh)
        out.append(it)
    return out


def _gen_popups(popups, lang, client):
    """He popup dung tu PSD: moi popup render THEO LAYER (nhu section thu nho) trong modal,
    tu co gian CONTAIN vua man hinh. type = 'popup:<id>' -> hien popup tuong ung; null -> an.
    Dong bang nut X / click nen / phim Esc (Esc wiring o Landing)."""
    head = '"use client";\n\n' if client else ""
    imp = 'import { useEffect, useState } from "react";\n'
    if lang == "ts":
        imp += 'import type { LayerItem } from "../../types/landing";\n'
    pdata = {p["id"]: {"w": p["w"], "h": p["h"],
                       "layers": json.loads(_flat_json(_popup_sanitize(p["flat"])))}
             for p in popups}
    data = json.dumps(pdata, ensure_ascii=False, indent=2)
    decl = (f"const POPUPS: Record<string, {{ w: number; h: number; layers: LayerItem[] }}> = {data};\n\n"
            if lang == "ts" else f"const POPUPS = {data};\n\n")
    sig = ("{ type, onClose }: { type: string | null; onClose: () => void }"
           if lang == "ts" else "{ type, onClose }")
    st = "useState<number>(1)" if lang == "ts" else "useState(1)"
    return head + imp + "\n" + decl + (
        "// vua man hinh CONTAIN (theo ca rong va cao viewport), gioi han 94vw x 90vh.\n"
        + ("const calc = (w: number, h: number) => {\n" if lang == "ts" else "const calc = (w, h) => {\n")
        + '  if (typeof document === "undefined") return 1;\n'
        "  const vw = document.documentElement.clientWidth * 0.94;\n"
        "  const vh = document.documentElement.clientHeight * 0.9;\n"
        "  return Math.min(1, vw / w, vh / h);\n};\n\n"
        f"export default function Popups({sig}) {{\n"
        '  const key = type && type.indexOf("popup:") === 0 ? type.slice(6) : type;\n'
        "  const p = key ? POPUPS[key] : null;\n"
        f"  const [scale, setScale] = {st};\n"
        "  useEffect(() => {\n"
        "    if (!p) return;\n"
        "    const fit = () => setScale(calc(p.w, p.h));\n"
        "    fit();\n"
        '    window.addEventListener("resize", fit);\n'
        '    return () => window.removeEventListener("resize", fit);\n'
        "  }, [p]);\n"
        "  if (!p) return null;\n"
        "  return (\n"
        "    <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}\n"
        '      className="fixed inset-0 z-[3000] flex items-center justify-center bg-[rgba(4,8,20,.72)]">\n'
        '      <div className="relative" style={{ width: p.w * scale, height: p.h * scale }}>\n'
        '        <button onClick={onClose} aria-label="Đóng"\n'
        '          className="absolute -right-3 -top-3 z-10 flex h-9 w-9 cursor-pointer items-center '
        'justify-center rounded-full border-0 bg-[#111a2e] text-2xl leading-none text-[#e8eeff] shadow-lg">&times;</button>\n'
        '        <div className="absolute left-0 top-0"\n'
        '          style={{ width: p.w, height: p.h, transformOrigin: "top left", transform: `scale(${scale})` }}>\n'
        "          {p.layers.map((l) => {\n"
        "            const ext = !!(l.href && /^https?:/.test(l.href));\n"
        "            return l.href ? (\n"
        '              <a key={l.id} href={l.href} data-action="other" target={ext ? "_blank" : undefined}\n'
        '                rel={ext ? "noopener" : undefined} title={l.alt} className={"hot " + l.cls}>\n'
        '                <img src={l.src} alt={l.alt} className="block h-full w-full" loading="lazy" decoding="async" />\n'
        "              </a>\n"
        "            ) : (\n"
        '              <img key={l.id} src={l.src} alt={l.alt} width={l.w} height={l.h} className={l.cls} loading="lazy" decoding="async" />\n'
        "            );\n"
        "          })}\n"
        "        </div>\n"
        "      </div>\n"
        "    </div>\n"
        "  );\n}\n")


def _gen_popups_stub(lang, client):
    """He popup stub (login/the le/lich su/nap dau...). type=null -> khong hien.
    Dung khi bat checkbox 'Popup mau' ma KHONG upload PSD popup (backward-compat)."""
    head = '"use client";\n\n' if client else ""
    sig = ("{ type, onClose }: { type: string | null; onClose: () => void }"
           if lang == "ts" else "{ type, onClose }")
    return head + (
        'const TITLES = { login: "Đăng nhập", rules: "Thể lệ", history: "Lịch sử", napdau: "Nạp đầu", '
        'topup: "Nạp thẻ", gift: "Nhận quà", check: "Kiểm tra", download: "Tải game", register: "Đăng ký", social: "Facebook" };\n'
        'const DESCS = { login: "TODO: gắn form / OIDC đăng nhập tại đây.", '
        'rules: "TODO: nội dung thể lệ sự kiện.", history: "TODO: lịch sử nhận quà (gọi API).", '
        'napdau: "TODO: nội dung nạp đầu.", gift: "TODO: nhận quà (gọi API claim)." };\n\n'
        f"export default function Popups({sig}) {{\n"
        "  if (!type) return null;\n"
        "  return (\n"
        '    <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}\n'
        '      className="fixed inset-0 z-[3000] flex items-center justify-center bg-[rgba(4,8,20,.72)]">\n'
        '      <div className="relative w-[90%] max-w-[460px] rounded-2xl border border-[#33507e] bg-[#111a2e] px-[34px] py-[30px] text-center text-[#e8eeff]">\n'
        '        <button onClick={onClose} className="absolute right-[14px] top-2 cursor-pointer border-0 bg-transparent text-2xl text-[#7d90b5]">&times;</button>\n'
        '        <h3 className="mb-[10px] text-xl">{TITLES[type] || "Thông báo"}</h3>\n'
        '        <p className="mb-5 text-sm leading-normal text-[#9db0d6]">\n'
        "          {DESCS[type] || ('Chức năng \"' + type + '\": cắm nội dung / API tại đây.')}</p>\n"
        '        <button onClick={onClose} className="cursor-pointer rounded-[9px] border-0 bg-gradient-to-r from-[#2563eb] to-[#3b82f6] px-[26px] py-[11px] font-bold text-white">Đóng</button>\n'
        "      </div>\n    </div>\n  );\n}\n")


def _gen_navmenu(board, lang, client):
    """Nav dang CHU (config duoc) - thay nav anh. Muc menu class 'navitem' de Landing wiring."""
    head = '"use client";\n\n' if client else ""
    fixed = board.get("fixed", [])
    logo = max(fixed, key=lambda it: it["w"] * it["h"]) if fixed else None
    navs = [it for it in fixed if it.get("alt") and 15 <= it["w"] <= 220 and 15 <= it["h"] <= 60]
    navs.sort(key=lambda it: it["y"])
    labels = [(_norm(it["alt"]).title() or "Menu") for it in navs] or ["Trang Chủ", "Mốc Quà", "Nạp Đầu"]
    nav_data = json.dumps([{"label": l, "slide": i} for i, l in enumerate(labels)], ensure_ascii=False, indent=2)
    logo_src = json.dumps(logo["src"]) if logo else '""'
    ann = ": { label: string; slide: number }[]" if lang == "ts" else ""
    return head + (
        "// Sua ten muc / thu tu nav tai day. slide = so thu tu section (0..).\n"
        f"export const NAV{ann} = {nav_data};\n"
        f"const LOGO = {logo_src};\n\n"
        "export default function NavMenu() {\n"
        '  return (\n'
        '    <div className="fixed top-4 left-6 z-[1000] flex flex-col items-center" style={{ pointerEvents: "none" }}>\n'
        '      {LOGO ? <img src={LOGO} alt="logo" className="w-[150px] object-contain mb-4" style={{ pointerEvents: "auto" }} /> : null}\n'
        '      <ul className="flex flex-col items-center gap-3" style={{ pointerEvents: "auto" }}>\n'
        "        {NAV.map((it, i) => (\n"
        '          <li key={i}>\n'
        '            <button className="navitem font-bold text-white/85 hover:text-[#ffe07a] transition text-lg leading-tight text-center cursor-pointer"\n'
        '              data-nav={i} style={{ textShadow: "0 2px 6px rgba(0,0,0,.6)", whiteSpace: "pre-line" }}>{it.label}</button>\n'
        "          </li>\n        ))}\n      </ul>\n    </div>\n  );\n}\n")


# CSS hieu ung chu & nut (opt-in feats.fx) - trich tu template t028-samkok-tam-quoc.
# Chi ghi vao index.css/globals.css khi bat fx. Ton trong prefers-reduced-motion.
FX_CSS = """
/* ===== Hieu ung chu & nut (fx) ===== */
@keyframes fxLaluot{from{-webkit-mask-position:150% 0;mask-position:150% 0}to{-webkit-mask-position:0% 0;mask-position:0% 0}}
.fx-shine{filter:brightness(2);-webkit-mask-image:-webkit-linear-gradient(45deg,rgba(255,255,255,0) 40%,#fff 50%,rgba(255,255,255,0) 60%);mask-image:-webkit-linear-gradient(45deg,rgba(255,255,255,0) 40%,#fff 50%,rgba(255,255,255,0) 60%);-webkit-mask-size:300% 200%;mask-size:300% 200%;-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;animation:fxLaluot 2.5s linear infinite 1s}
@keyframes fxGlow{0%,100%{filter:drop-shadow(0 0 5px rgba(255,255,220,.8)) drop-shadow(0 0 15px rgba(255,215,0,.5))}50%{filter:drop-shadow(0 0 8px #fff) drop-shadow(0 0 25px rgba(255,215,0,.85)) drop-shadow(0 0 45px rgba(255,160,0,.5))}}
.fx-glow{animation:fxGlow 3s ease-in-out infinite}
@keyframes fxFloat{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-3%) scale(1.03)}}
.fx-float{animation:fxFloat 2s ease-in-out infinite}
.fx-btn{transition:transform .18s ease}
.fx-btn:hover{transform:scale(1.06)}
@media(prefers-reduced-motion:reduce){.fx-shine,.fx-glow,.fx-float{animation:none}}
"""

# CSS 'section nay/zoom vao khi cuon toi' (opt-in feats.fx_reveal). Nang cap scroll-reveal
# fade-up san co thanh pop-in/zoom-in kieu game. Chi ap scroll + deck (swiper_lib da crossfade).
FX_REVEAL_CSS = """
/* ===== Hieu ung xuat hien khi cuon (fx_reveal) ===== */
@keyframes fxPopIn{0%{opacity:0;transform:translateY(26px) scale(.94)}60%{opacity:1;transform:translateY(0) scale(1.03)}100%{opacity:1;transform:none}}
@keyframes fxZoomIn{0%{opacity:0;transform:scale(1.06)}20%{opacity:1}100%{opacity:1;transform:scale(1)}}
.fx-reveal .landing-sec.reveal.in{animation:fxPopIn .6s ease-out forwards}
.fx-reveal .deck .landing-sec.on{animation:fxZoomIn .5s ease-out}
@media(prefers-reduced-motion:reduce){.fx-reveal .landing-sec.reveal.in,.fx-reveal .deck .landing-sec.on{animation:none}}
"""


def _gen_layer(lang, client, fx=False):
    head = '"use client";\n\n' if client else ""
    imp = 'import type { LayerItem } from "../../types/landing";\n\n' if lang == "ts" else ""
    sig = ("{ l, menuOpen, onToggleMenu }: { l: LayerItem; menuOpen?: boolean; onToggleMenu?: () => void }"
           if lang == "ts" else "{ l, menuOpen, onToggleMenu }")
    react_imp = ""
    # fx: gan hieu ung theo l.fx (auto 'btn'/'title' hoac editor gan tay: shine/glow/float/
    # shine-glow/float-glow). shine = lop anh phu mask luot sang (nhu 'Mo Loi Xung Ba').
    if fx:
        fx_decl = (
            '  const FXMAP = { btn: "fx-btn fx-glow ", title: "fx-float fx-glow ", '
            'shine: "", glow: "fx-glow ", float: "fx-float ", "shine-glow": "fx-glow ", '
            '"float-glow": "fx-float fx-glow " };\n'
            '  const fxCls = FXMAP[l.fx || ""] || "";\n'
            '  const fxShine = l.fx === "btn" || l.fx === "shine" || l.fx === "shine-glow";\n')
    else:
        fx_decl = '  const fxCls = "";\n  const fxShine = false;\n'
    shine = ('      {fxShine && (\n'
             '        <img src={l.src} alt="" aria-hidden="true"\n'
             '          className="fx-shine pointer-events-none absolute inset-0 block h-full w-full" />\n'
             '      )}\n') if fx else ""
    # anh KHONG link co shine -> boc div.relative (fxCls tren div) + anh goc + lop luot sang.
    noref = (
        "  if (fxShine) {\n"
        '    return (\n'
        '      <div className={fxCls + l.cls}>\n'
        '        <img src={l.src} alt={l.alt} className="block h-full w-full" loading={l.lcp ? "eager" : "lazy"} fetchPriority={l.lcp ? "high" : undefined} decoding="async" />\n'
        '        <img src={l.src} alt="" aria-hidden="true" className="fx-shine pointer-events-none absolute inset-0 block h-full w-full" />\n'
        "      </div>\n"
        "    );\n  }\n"
        "  return (\n"
        "    <img src={l.src} alt={l.alt} width={l.w} height={l.h} className={fxCls + l.cls} loading={l.lcp ? \"eager\" : \"lazy\"} fetchPriority={l.lcp ? \"high\" : undefined} decoding=\"async\" />\n  );\n"
    ) if fx else (
        "  return (\n"
        "    <img src={l.src} alt={l.alt} width={l.w} height={l.h} className={fxCls + l.cls} loading={l.lcp ? \"eager\" : \"lazy\"} fetchPriority={l.lcp ? \"high\" : undefined} decoding=\"async\" />\n  );\n"
    )
    # THUAN TAILWIND: l.cls chua san class Tailwind (left-[..]/top-[..]/w-[..]/h-[..]/
    # mix-blend/opacity, va text-[..px]/text-[color] cho chu that). Khong con inline style.
    return head + react_imp + imp + (
        f"// 1 lop: anh (img) HOAC chu that (text). Class Tailwind lay tu l.cls (khong inline style).\n"
        f"export default function Layer({sig}) {{\n"
        f"  const ext = !!(l.href && /^https?:/.test(l.href));\n"
        f"{fx_decl}"
        "  if (l.asText) {\n"
        "    return l.href ? (\n"
        '      <a href={l.href} data-action={l.act || "other"} target={ext ? "_blank" : undefined} rel={ext ? "noopener" : undefined}\n'
        '        title={l.alt} className={"hot z-[6] " + fxCls + l.cls}>{l.text}</a>\n'
        "    ) : (\n"
        "      <div className={fxCls + l.cls}>{l.text}</div>\n"
        "    );\n  }\n"
        "  if (l.toggle) {\n"
        "    return (\n"
        '      <button onClick={onToggleMenu} title={l.alt}\n'
        '        className={"cursor-pointer transition hover:brightness-110 " + l.cls}>\n'
        '        <img src={l.src} alt={l.alt} width={l.w} height={l.h} className="block w-full h-full" loading={l.lcp ? "eager" : "lazy"} fetchPriority={l.lcp ? "high" : undefined} decoding="async" />\n'
        "      </button>\n    );\n  }\n"
        "  if (l.menu && !menuOpen) return null;\n"
        "  if (l.href) {\n"
        "    return (\n"
        '      <a href={l.href} data-action={l.act || "other"} target={ext ? "_blank" : undefined} rel={ext ? "noopener" : undefined}\n'
        '        title={l.alt} className={"hot z-[6] " + fxCls + l.cls}>\n'
        '        <img src={l.src} alt={l.alt} className="block w-full h-full" loading="lazy" decoding="async" />\n'
        f"{shine}"
        "      </a>\n    );\n  }\n"
        f"{noref}"
        "}\n")


def _tw_pos(x, y, w, h):
    """Class Tailwind (arbitrary values) cho vi tri/kich thuoc tuyet doi."""
    return f"left-[{round(x)}px] top-[{round(y)}px] w-[{round(w)}px] h-[{round(h)}px]"


def _tw_cls(it, block=True):
    """Sinh chuoi class Tailwind THUAN cho 1 layer (thay inline style). Tailwind JIT
    quet duoc class literal ke ca khi nam trong mang data trong file .tsx."""
    parts = ["absolute"]
    if it.get("asText"):
        parts += ["flex", "items-center", "justify-center", "text-center", "font-bold",
                  "leading-tight", "whitespace-pre-wrap", "overflow-hidden"]
        if it.get("tsize"):
            parts.append(f"text-[{int(it['tsize'])}px]")
        if it.get("tcolor"):
            parts.append(f"text-[{it['tcolor']}]")
    elif block:
        parts.append("block")
    parts.append(_tw_pos(it["x"], it["y"], it["w"], it["h"]))
    o = it.get("o", 1)
    try:
        if o is not None and float(o) < 0.999:
            parts.append(f"opacity-[{round(float(o), 3)}]")
    except Exception:
        pass
    if it.get("blend"):
        parts.append(f"mix-blend-{it['blend']}")
    return " ".join(parts)


def _flat_json(items):
    keep = []
    for it in items:
        o = {"id": it["id"], "src": it["src"], "x": it["x"], "y": it["y"],
             "w": it["w"], "h": it["h"], "o": it["o"], "alt": it["alt"]}
        if it.get("blend"):
            o["blend"] = it["blend"]
        if it.get("href"):
            o["href"] = it["href"]
        if it.get("act"):
            o["act"] = it["act"]
        if it.get("asText"):
            o["asText"] = True
            o["text"] = it.get("text")
            o["tsize"] = it.get("tsize")
            o["tcolor"] = it.get("tcolor")
        if it.get("menu"):
            o["menu"] = True
        if it.get("toggle"):
            o["toggle"] = True
        if it.get("lcp"):
            o["lcp"] = True           # anh LCP -> tai som + uu tien cao
        if it.get("fx"):
            o["fx"] = it["fx"]        # loai hieu ung (btn/title) - dung khi bat fx
        o["cls"] = _tw_cls(o)          # class Tailwind san (thay inline style)
        keep.append(o)
    return json.dumps(keep, ensure_ascii=False, indent=2)


def _mark_lcp(board):
    """Danh dau anh LCP (dien tich lon nhat o phan tren: backgrounds + section dau)."""
    cands = list(board.get("backgrounds", []))
    secs = board.get("sections", [])
    if secs:
        cands += [it for it in secs[0].get("flat", []) if not it.get("asText")]
    cands = [it for it in cands if it.get("src") and not it.get("asText")]
    if cands:
        max(cands, key=lambda it: it.get("w", 0) * it.get("h", 0))["lcp"] = True


def _gen_background(board, lang, client):
    head = '"use client";\n\n' if client else ""
    imp = 'import type { LayerItem } from "../../types/landing";\n\n' if lang == "ts" else ""
    decl = f"const bg{_ann(lang, 'LayerItem[]')} = {_flat_json(board['backgrounds'])};\n\n"
    return head + imp + decl + (
        "export default function Background() {\n  return (\n    <>\n"
        "      {bg.map((l) => (\n"
        '        <img key={l.id} src={l.src} alt={l.alt} width={l.w} height={l.h} className={l.cls}\n'
        '          loading={l.lcp ? "eager" : "lazy"} fetchPriority={l.lcp ? "high" : undefined} decoding="async" />\n'
        "      ))}\n    </>\n  );\n}\n")


def _gen_repeat(rp, lang, client):
    head = '"use client";\n\n' if client else ""
    imp = 'import type { RepeatItem } from "../../types/landing";\n\n' if lang == "ts" else ""
    sig = ("{ item, onClaim }: { item: RepeatItem; onClaim?: (id: number) => void }"
           if lang == "ts" else "{ item, onClaim }")
    if rp["grid"].get("is_grid"):
        root = f'    <div className="relative shrink-0 w-[{rp["W"]}px] h-[{rp["H"]}px]">'
    else:  # cum bat quy tac (so le) -> vi tri instance qua item.cls (Tailwind)
        root = '    <div className={"absolute " + (item.cls || "")}>'
    L = [head + imp, f"export default function {rp['comp']}({sig}) {{",
         "  return (", root]
    for sl in rp["slots"]:
        cls = _tw_cls({"x": sl["rx"], "y": sl["ry"], "w": sl["w"], "h": sl["h"],
                       "o": sl["o"], "blend": sl.get("blend")})
        if sl["kind"] == "button":
            L.append(f'      <button onClick={{() => onClaim && onClaim(item.id)}} title="{sl["alt"]}"')
            L.append(f'        className="cursor-pointer transition hover:brightness-110 {cls}">')
            L.append(f'        <img src="{sl["asset"]}" alt="{sl["alt"]}" className="block w-full h-full" />')
            L.append("      </button>")
        elif sl["kind"] == "var":
            L.append(f'      {{item.{sl["var"]} ? <img className="{cls}" '
                     f'src={{item.{sl["var"]} as string}} alt="{sl["alt"]}" /> : null}}'
                     if lang == "ts" else
                     f'      {{item.{sl["var"]} && <img className="{cls}" '
                     f'src={{item.{sl["var"]}}} alt="{sl["alt"]}" />}}')
        else:
            L.append(f'      <img className="{cls}" src="{sl["asset"]}" alt="{sl["alt"]}" />')
    # item.items = du lieu tu API (runtime) -> vi tri dong, dung style toi thieu (khong the
    # thanh class Tailwind tinh). Mac dinh rong; chi dung khi do API vao.
    L.append('      {(item.items || []).map((it, i) => (')
    L.append('        <img key={i} className="absolute block" src={it.src} alt={it.alt || ""}')
    L.append("          style={{ left: it.x, top: it.y, width: it.w, height: it.h }} />")
    L.append("      ))}")
    L.append('      {item.claimed ? <div className="absolute inset-0 bg-black/40" /> : null}')
    L += ["    </div>", "  );", "}", ""]
    return "\n".join(L)


def _gen_section(sec, lang, client):
    head = '"use client";\n\n' if client else ""
    # Neu section da duoc AI "prod-hoa" -> dung luon JSX do (chu that + hover + semantic).
    if sec.get("ai_jsx"):
        return head + sec["ai_jsx"] + "\n"
    # Toa do TRONG section (tru goc section) de boc trong container content-visibility.
    y0 = sec.get("y0", 0)
    imports = ['import Layer from "./Layer";']
    for rp in sec["repeats"]:
        imports.append(f'import {rp["comp"]} from "./{rp["comp"]}";')
    if lang == "ts":
        imports.append('import type { SectionProps, LayerItem, RepeatItem } from "../../types/landing";')
    blocks = [head + "\n".join(imports) + "\n"]
    flat_rel = [{**it, "y": it["y"] - y0} for it in sec["flat"]]
    blocks.append(f"const flat{_ann(lang, 'LayerItem[]')} = {_flat_json(flat_rel)};\n")
    for rp in sec["repeats"]:
        var = rp["comp"][0].lower() + rp["comp"][1:] + "Data"
        data = []
        for inst in rp["instances"]:
            e = {"id": inst["id"], "x": inst["x"], "y": inst["y"] - y0}
            e.update(inst["vars"])
            e["claimed"] = False
            e["items"] = []
            e["cls"] = _tw_pos(inst["x"], inst["y"] - y0, rp["W"], rp["H"])  # vi tri instance (Tailwind)
            data.append(e)
        blocks.append(f"// {rp['count']} phan tu lap - thay bang data tu API\n"
                      f"const {var}{_ann(lang, 'RepeatItem[]')} = {json.dumps(data, ensure_ascii=False, indent=2)};\n")
    sig = "{ onClaim, menuOpen, onToggleMenu }" + _ann(lang, "SectionProps")
    body = [f"export default function {sec['comp']}({sig}) {{", "  return (", "    <>"]
    body.append("      {flat.map((l) => (")
    body.append("        <Layer key={l.id} l={l} menuOpen={menuOpen} onToggleMenu={onToggleMenu} />")
    body.append("      ))}")
    for rp in sec["repeats"]:
        var = rp["comp"][0].lower() + rp["comp"][1:] + "Data"
        g = rp["grid"]
        if g.get("is_grid"):
            # Cum LUOI DEU = container FLEX-WRAP (bo tung the absolute) -> tu xep lai hang.
            body.append(f'      <div className="absolute left-[{g["x"]}px] top-[{g["y"] - y0}px] '
                        f'w-[{g["w"]}px] flex flex-wrap justify-center content-start '
                        f'gap-x-[{g["gx"]}px] gap-y-[{g["gy"]}px]">')
            body.append(f"        {{{var}.map((it) => (")
            body.append(f'          <{rp["comp"]} key={{it.id}} item={{it}} onClaim={{onClaim}} />')
            body.append("        ))}")
            body.append("      </div>")
        else:  # cum bat quy tac -> the tu dinh vi absolute (khong bao container)
            body.append(f"      {{{var}.map((it) => (")
            body.append(f'        <{rp["comp"]} key={{it.id}} item={{it}} onClaim={{onClaim}} />')
            body.append("      ))}")
    body += ["    </>", "  );", "}", ""]
    return "\n".join(blocks) + "\n".join(body)


# useEffect lo TUONG TAC: click nut -> link/modal, nav cuon toi section + scroll-spy
# + scroll-reveal. Dung getBoundingClientRect (tinh ca transform:scale cua Stage).
_LANDING_EFFECT = r'''  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const navs = Array.from(document.querySelectorAll(".navitem"));
    const secs = Array.from(root.querySelectorAll(".landing-sec"));
    const topOf = (el) => el.getBoundingClientRect().top + window.scrollY;
    const navHandlers = navs.map((n, i) => {
      const h = (e) => { e.preventDefault();
        const t = secs[Math.min(i, secs.length - 1)];
        if (t) window.scrollTo({ top: Math.max(0, topOf(t) - 4), behavior: "smooth" }); };
      n.addEventListener("click", h); return { n, h };
    });
    const onScroll = () => {
      const mid = window.scrollY + window.innerHeight * 0.4;
      const revealLine = window.scrollY + window.innerHeight * 0.88;
      let cur = 0;
      secs.forEach((s, i) => { const top = topOf(s);
        if (top <= mid) cur = i;
        if (top < revealLine) s.classList.add("in"); });
      navs.forEach((n, i) => n.classList.toggle("active", i === cur));
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    onScroll();
    const revealTimer = setTimeout(() => secs.forEach((s) => s.classList.add("in")), 2500);
    const onClick = (e) => {
      const a = e.target.closest(".hot");
      if (!a || !root.contains(a)) return;
      const href = a.getAttribute("href");
      if (href && href !== "#") return;   // link that -> dieu huong tu nhien
      e.preventDefault();
      const act = a.getAttribute("data-action") || "other";
      const url = LINKS[act];
      if (url) { window.open(url, "_blank", "noopener,noreferrer"); return; }
      openAction(act);
    };
    document.addEventListener("click", onClick);
    return () => {
      navHandlers.forEach(({ n, h }) => n.removeEventListener("click", h));
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      document.removeEventListener("click", onClick);
      clearTimeout(revealTimer);
    };
  }, []);
'''

_LANDING_MODAL = r'''      {modal && (
        <div onClick={(e) => { if (e.target === e.currentTarget) setModal(null); }}
          role="dialog" aria-modal="true" aria-label={modal.title}
          className="fixed inset-0 z-[3000] flex items-center justify-center bg-[rgba(4,8,20,.72)]">
          <div className="relative w-[90%] max-w-[420px] rounded-2xl border border-[#33507e] bg-[#111a2e] px-[34px] py-[30px] text-center text-[#e8eeff]">
            <button onClick={() => setModal(null)} aria-label="Đóng"
              className="absolute right-[14px] top-2 cursor-pointer border-0 bg-transparent text-2xl text-[#7d90b5]">&times;</button>
            <h3 className="mb-[10px] text-xl">{modal.title}</h3>
            <p className="mb-5 text-sm leading-normal text-[#9db0d6]">{modal.desc}</p>
            <button onClick={() => setModal(null)}
              className="cursor-pointer rounded-[9px] border-0 bg-gradient-to-r from-[#2563eb] to-[#3b82f6] px-[26px] py-[11px] font-bold text-white">Đóng</button>
          </div>
        </div>
      )}'''


# useEffect cho che do SWIPER full-page kieu FADE (crossfade nhu swiper effect:'fade').
_LANDING_SWIPER_EFFECT = r'''  const ref = useRef(null); const stageRef = useRef(null);
  useEffect(() => {
    const deck = ref.current, stage = stageRef.current;
    if (!deck || !stage) return;
    const navs = Array.from(document.querySelectorAll(".navitem"));
    const secEls = Array.from(stage.querySelectorAll(".landing-sec"));
    let s = 1, idx = 0, lock = false; const N = secEls.length;
    const go = (i) => { idx = Math.max(0, Math.min(N - 1, i));
      secEls.forEach((el, k) => el.classList.toggle("on", k === idx));
      navs.forEach((n, k) => n.classList.toggle("active", k === Math.min(idx, navs.length - 1))); };
    // FILL WIDTH: scale theo be rong viewport -> lap day be ngang, KHONG vien den 2 ben.
    const fit = () => { s = deck.clientWidth / __W__; stage.style.transform = `scale(${s})`; };
    window.addEventListener("resize", fit); fit(); go(0);
    // Ep repaint: layer scale khong duoc ve (section DEN) cho toi khi co nhip repaint.
    const kick = () => { stage.style.transform = "none"; void stage.offsetHeight; fit(); };
    requestAnimationFrame(kick); setTimeout(kick, 300);
    const step = (d) => { if (lock) return; lock = true; setTimeout(() => (lock = false), 650); go(idx + d); };
    const onWheel = (e) => { e.preventDefault(); if (Math.abs(e.deltaY) < 8) return; step(e.deltaY > 0 ? 1 : -1); };
    deck.addEventListener("wheel", onWheel, { passive: false });
    const onKey = (e) => { if (e.key === "ArrowDown" || e.key === "PageDown") { e.preventDefault(); step(1); }
      else if (e.key === "ArrowUp" || e.key === "PageUp") { e.preventDefault(); step(-1); } };
    window.addEventListener("keydown", onKey);
    let ty = null;
    const onTS = (e) => { ty = e.touches[0].clientY; };
    const onTE = (e) => { if (ty == null) return; const dy = ty - e.changedTouches[0].clientY;
      if (Math.abs(dy) > 40) step(dy > 0 ? 1 : -1); ty = null; };
    deck.addEventListener("touchstart", onTS, { passive: true });
    deck.addEventListener("touchend", onTE);
    const navH = navs.map((n, i) => { const h = (e) => { e.preventDefault(); go(Math.min(i, N - 1)); };
      n.addEventListener("click", h); return { n, h }; });
    const onClick = (e) => { const a = e.target.closest(".hot"); if (!a || !deck.contains(a)) return;
      const href = a.getAttribute("href"); if (href && href !== "#") return; e.preventDefault();
      const act = a.getAttribute("data-action") || "other"; const url = LINKS[act];
      if (url) { window.open(url, "_blank", "noopener,noreferrer"); return; }
      openAction(act); };
    document.addEventListener("click", onClick);
    return () => { window.removeEventListener("resize", fit); deck.removeEventListener("wheel", onWheel);
      window.removeEventListener("keydown", onKey); deck.removeEventListener("touchstart", onTS);
      deck.removeEventListener("touchend", onTE); navH.forEach(({ n, h }) => n.removeEventListener("click", h));
      document.removeEventListener("click", onClick); };
  }, []);
'''


# useEffect cho che do SWIPER.JS THAT (thu vien swiper): scale slide + nav slideTo + nut.
_LANDING_SWIPERLIB_EFFECT = r'''  useEffect(() => {
    // Scope MOI truy van vao rootRef cua ban nay (desktop/mobile) - tranh 2 ban
    // cung dung document.querySelectorAll(".slide-stage") roi giam scale len nhau.
    const root = rootRef.current; if (!root) return;
    const N = __N__;
    // FILL WIDTH: scale theo BE RONG viewport (giong landing prod) -> LAP DAY be ngang,
    // KHONG co vien den 2 ben. Chieu cao section = h*s (co the tran/cat neu cao hon
    // viewport - chap nhan de day be rong nhu thiet ke goc).
    const fit = () => {
      const s = window.innerWidth / __W__;
      root.querySelectorAll__QS__(".slide-stage").forEach((el) => {
        el.style.transform = `scale(${s})`;
      }); };
    fit(); window.addEventListener("resize", fit);
    // Ep repaint: tranh slide bi DEN (layer scale khong duoc ve cho toi khi repaint).
    const kick = () => { root.querySelectorAll__QS__(".slide-stage").forEach((el) => { el.style.transform = "none"; void el.offsetHeight; }); fit(); };
    requestAnimationFrame(kick); setTimeout(kick, 300);
    const navs = Array.from(root.querySelectorAll(".navitem"));
    const navH = navs.map((n, i) => { const h = (e) => { e.preventDefault();
      if (swiperRef.current) swiperRef.current.slideTo(Math.min(i, N - 1)); };
      n.addEventListener("click", h); return { n, h }; });
    const onClick = (e) => { const a = (e.target__ASH__).closest(".hot"); if (!a || !root.contains(a)) return;
      const href = a.getAttribute("href"); if (href && href !== "#") return; e.preventDefault();
      const act = a.getAttribute("data-action") || "other"; const url = LINKS[act];
      if (url) { window.open(url, "_blank", "noopener,noreferrer"); return; }
      openAction(act); };
    root.addEventListener("click", onClick);
    return () => { window.removeEventListener("resize", fit);
      navH.forEach(({ n, h }) => n.removeEventListener("click", h)); root.removeEventListener("click", onClick); };
  }, []);
  useEffect(() => { const root = rootRef.current; if (root) Array.from(root.querySelectorAll(".navitem")).forEach((n, i) => n.classList.toggle("active", i === activeIndex)); }, [activeIndex]);
'''


def _pct(v, base):
    """px -> chuoi phan tram (lam tron 3 so) de dinh vi tuong doi, co gian theo width."""
    return f"{round(v / base * 100, 4)}%"


def _fluid_slots(rp, item_ref, lang):
    """JSX cac slot BEN TRONG 1 the (dinh vi % theo W/H the) - dung chung cho
    the reflow (flex) va the trong canvas. item_ref = ten bien item ('it')."""
    W, H = rp["W"], rp["H"]
    out = []
    for sl in rp["slots"]:
        st = (f'{{ position: "absolute", left: "{_pct(sl["rx"], W)}", top: "{_pct(sl["ry"], H)}", '
              f'width: "{_pct(sl["w"], W)}", height: "{_pct(sl["h"], H)}", opacity: {sl["o"]}'
              + (f', mixBlendMode: "{sl["blend"]}"' if sl.get("blend") else "") + " }")
        if sl["kind"] == "button":
            out.append(f'        <button onClick={{() => onClaim && onClaim({item_ref}.id)}} title="{sl["alt"]}" '
                       f'className="hot" style={{{st}}}>'
                       f'<img src="{sl["asset"]}" alt="{sl["alt"]}" className="block w-full h-full" /></button>')
        elif sl["kind"] == "var":
            cond = (f'{item_ref}.{sl["var"]} ? <img className="block" style={{{st}}} src={{{item_ref}.{sl["var"]} as string}} alt="{sl["alt"]}" /> : null'
                    if lang == "ts" else
                    f'{item_ref}.{sl["var"]} && <img className="block" style={{{st}}} src={{{item_ref}.{sl["var"]}}} alt="{sl["alt"]}" />')
            out.append(f'        {{{cond}}}')
        else:
            out.append(f'        <img className="block" style={{{st}}} src="{sl["asset"]}" alt="{sl["alt"]}" />')
    return out


def _gen_fluid_mobile(board, lang, client, config_rel="../../landing.config"):
    """Layout MOBILE co gian THAT (opt-in --fluid): section xep doc (flow), moi
    section:
      - Khong co luoi deu -> canvas ti le khoa (aspect-ratio), art dinh vi % ->
        pixel-proportional, co theo be rong (giong desktop, chi khac scale).
      - Co luoi deu -> backdrop scene + grid REFLOW: the dung clamp()+aspect-ratio,
        flex-wrap tu be 4->2->1 cot theo viewport (giong ban production)."""
    head = '"use client";\n\n' if client else ""
    W, H = board["W"], board["H"]
    secs = board["sections"]
    ys = [s.get("y0", 0) for s in secs]
    bands = [(ys[i], max(1, (ys[i + 1] if i + 1 < len(secs) else H) - ys[i])) for i in range(len(secs))]
    bgs_all = board.get("backgrounds", [])

    def in_band(it, y0, hb):
        cy = it["y"] + it["h"] / 2
        return y0 <= cy < y0 + hb

    refann = "<HTMLDivElement>" if lang == "ts" else ""
    L = [head + f'import {{ useEffect, useRef }} from "react";\nimport {{ LINKS }} from "{config_rel}";\n',
         "// Layout mobile co gian (fluid): sinh boi che do --fluid. Desktop dung ban rieng.",
         "export default function MobileFluid() {",
         f"  const onClaim = (id{_ann(lang, 'number')}) => {{ console.log('claim', id); }};",
         f"  const rootRef = useRef{refann}(null);",
         "  useEffect(() => {",
         "    const root = rootRef.current; if (!root) return;",
         "    const onClick = (e) => { const a = (e.target" + (" as HTMLElement" if lang == "ts" else "")
         + ').closest(".hot"); if (!a || !root.contains(a)) return;',
         '      const act = a.getAttribute("data-action"); if (!act) return;',
         "      const url = LINKS[act]; if (url) { e.preventDefault(); window.open(url, '_blank', 'noopener,noreferrer'); } };",
         "    root.addEventListener('click', onClick);",
         "    return () => root.removeEventListener('click', onClick);",
         "  }, []);",
         "  return (",
         '    <div ref={rootRef} className="w-full bg-black">']

    for i, sec in enumerate(secs):
        y0, hb = bands[i]
        grid_reps = [rp for rp in sec["repeats"] if rp["grid"].get("is_grid")]
        flat = sec["flat"]
        band_bgs = [b for b in bgs_all if in_band(b, y0, hb)]
        # art (nen + flat + cum KHONG phai luoi) dat trong canvas ti le khoa
        L.append(f'      <section className="relative w-full overflow-hidden" '
                 f'style={{{{ aspectRatio: "{W} / {hb}" }}}}>')
        for b in band_bgs:
            bl = (f', mixBlendMode: "{b["blend"]}"' if b.get("blend") else "")
            L.append(f'        <img src="{b["src"]}" alt="{b.get("alt","")}" loading="lazy" '
                     f'className="absolute block" style={{{{ left: "{_pct(b["x"],W)}", top: "{_pct(b["y"]-y0,hb)}", '
                     f'width: "{_pct(b["w"],W)}", height: "{_pct(b["h"],hb)}", opacity: {b.get("o",1)}{bl} }}}} />')
        for it in flat:
            act = it.get("act")
            cls = "hot absolute block" if it.get("href") else "absolute block"
            extra = f' data-action="{act}"' if act else ""
            st = (f'{{ left: "{_pct(it["x"],W)}", top: "{_pct(it["y"]-y0,hb)}", '
                  f'width: "{_pct(it["w"],W)}", height: "{_pct(it["h"],hb)}", opacity: {it.get("o",1)}'
                  + (f', mixBlendMode: "{it["blend"]}"' if it.get("blend") else "") + " }")
            L.append(f'        <img src="{it["src"]}" alt="{it.get("alt","")}"{extra} loading="lazy" '
                     f'className="{cls}" style={{{st}}} />')
        # cum KHONG phai luoi (zigzag) -> giu vi tri % trong canvas
        for rp in sec["repeats"]:
            if rp["grid"].get("is_grid"):
                continue
            rw, rh = rp["W"], rp["H"]
            for inst in rp["instances"]:
                box = (f'{{ position: "absolute", left: "{_pct(inst["x"],W)}", top: "{_pct(inst["y"]-y0,hb)}", '
                       f'width: "{_pct(rw,W)}", aspectRatio: "{rw} / {rh}" }}')
                L.append(f'        <div style={{{box}}}>')
                # slot dinh vi % trong the; var thay bang src cua instance
                for sl in rp["slots"]:
                    st = (f'{{ position: "absolute", left: "{_pct(sl["rx"],rw)}", top: "{_pct(sl["ry"],rh)}", '
                          f'width: "{_pct(sl["w"],rw)}", height: "{_pct(sl["h"],rh)}", opacity: {sl["o"]} }}')
                    src = inst["vars"].get(sl.get("var"), sl["asset"]) if sl["kind"] == "var" else sl["asset"]
                    if sl["kind"] == "button":
                        L.append(f'          <button onClick={{() => onClaim && onClaim({inst["id"]})}} '
                                 f'className="hot" style={{{st}}}><img src="{sl["asset"]}" alt="{sl["alt"]}" '
                                 f'className="block w-full h-full" /></button>')
                    else:
                        L.append(f'          <img src="{src}" alt="{sl["alt"]}" className="block" style={{{st}}} />')
                L.append('        </div>')
        L.append('      </section>')
        # cum LUOI DEU -> grid reflow that (duoi backdrop)
        for rp in grid_reps:
            data = []
            for inst in rp["instances"]:
                e = {"id": inst["id"]}
                e.update(inst["vars"])
                data.append(e)
            var = rp["comp"][0].lower() + rp["comp"][1:] + "Data"
            L.append(f'      {{/* {rp["count"]} phan tu - reflow theo viewport, thay bang data API */}}')
            L.append(f'      {{(function(){{ const {var}{_ann(lang,"any[]")} = '
                     f'{json.dumps(data, ensure_ascii=False)}; return (')
            L.append('        <div className="w-full flex flex-wrap justify-center items-start gap-[3vw] px-3 py-6">')
            L.append(f'          {{{var}.map((it) => (')
            L.append(f'            <div key={{it.id}} className="relative shrink-0" '
                     f'style={{{{ width: "clamp(120px, {round(100/(rp["grid"]["cols"]+0.3),2)}vw, {rp["W"]}px)", '
                     f'aspectRatio: "{rp["W"]} / {rp["H"]}" }}}}>')
            L += _fluid_slots(rp, "it", lang)
            L.append('            </div>')
            L.append('          ))}')
            L.append('        </div>')
            L.append('      ); })()}')

    L += ['    </div>', '  );', '}', '']
    return "\n".join(L)


def _ctext_of(l):
    s = l.get("text") or (l.get("alt") if l.get("t") else "") or ""
    return " ".join(str(s).split()).strip()


def _seo_texts_from_layout(layout):
    """Noi dung layer CHU (GIU nguyen hoa/thuong, ca cau) sap theo dien tich giam dan."""
    def c(l):
        return " ".join(((l.get("text") or {}).get("content") or "").split()).strip()
    ts = sorted([l for l in layout.get("layers", []) if c(l)],
                key=lambda l: l["bbox"]["width"] * l["bbox"]["height"], reverse=True)
    return [c(l) for l in ts]


def _page_title(board):
    """Tieu de trang (SEO/a11y). Uu tien text goc tu layout (board['page_title'])."""
    if board.get("page_title"):
        return board["page_title"][:70]
    txts = sorted([l for s in board.get("sections", []) for l in s.get("flat", []) if _ctext_of(l)],
                  key=lambda l: l.get("w", 0) * l.get("h", 0), reverse=True)
    return (_ctext_of(txts[0]) if txts else board.get("landing_name", "Landing"))[:70]


def _page_desc(board):
    if board.get("page_desc"):
        return board["page_desc"][:160]
    txts = sorted([l for s in board.get("sections", []) for l in s.get("flat", []) if _ctext_of(l)],
                  key=lambda l: l.get("w", 0) * l.get("h", 0), reverse=True)
    return (" · ".join(_ctext_of(l) for l in txts[:6]) or _page_title(board))[:160]


def _gen_landing(board, lang, client, stage_rel="../Stage", swiper=False, feats=None,
                 config_rel="../../landing.config", comp_base="."):
    head = '"use client";\n\n' if client else ""
    comp = board["landing_name"]
    has_fixed = bool(board.get("fixed"))
    W, H = board["W"], board["H"]
    secs = board["sections"]
    feats = feats or {}
    swiper_lib = bool(feats.get("swiper_lib")) and bool(secs)
    swiper = (swiper and bool(secs)) or swiper_lib
    # fx_reveal: section nay/zoom vao khi cuon toi (scroll) / chuyen slide (deck). Class
    # fx-reveal tren <main> kich hoat CSS pop-in; swiper_lib da crossfade san nen bo qua.
    main_cls = ' className="fx-reveal"' if feats.get("fx_reveal") else ''
    use_navmenu = bool(feats.get("nav_menu")) and has_fixed
    nav_tag = "NavMenu" if use_navmenu else ("FixedNav" if has_fixed else None)
    ys = [s.get("y0", 0) for s in secs]
    bands = [(ys[i], max(1, (ys[i + 1] if i + 1 < len(secs) else H) - ys[i])) for i in range(len(secs))]

    # SEO/a11y: tieu de trang tu layer chu lon nhat
    page_title = _page_title(board) or comp
    h1_jsx = f'      <h1 className="sr-only">{{{json.dumps(page_title, ensure_ascii=False)}}}</h1>'

    imports = ['import { useState, useEffect, useRef } from "react";',
               f'import {{ LINKS, LABELS }} from "{config_rel}";']
    if swiper_lib:  # dung thu vien Swiper.js that (giong prod)
        imports.insert(1, 'import { Swiper, SwiperSlide } from "swiper/react";')
        imports.insert(2, 'import { Mousewheel, EffectFade } from "swiper/modules";')
        imports.insert(3, 'import "swiper/css";')
        imports.insert(4, 'import "swiper/css/effect-fade";')
    elif not swiper:  # swiper (fade tu viet) tu ve nen trong section, khong dung Stage/Background
        imports.insert(1, f'import Stage from "{stage_rel}";')
        imports.insert(2, f'import Background from "{comp_base}/Background";')
    if nav_tag:
        imports.append(f'import {nav_tag} from "{comp_base}/{nav_tag}";')
    popups = bool(feats.get("popups"))
    if popups:
        imports.append(f'import Popups from "{comp_base}/Popups";')
    for sec in secs:
        imports.append(f'import {sec["comp"]} from "{comp_base}/{sec["comp"]}";')

    modal_ty = "<{ title: string; desc: string } | null>" if lang == "ts" else ""
    pop_ty = "<string | null>" if lang == "ts" else ""
    refann = "<HTMLDivElement>" if lang == "ts" else ""
    L = [head + "\n".join(imports) + "\n"]
    L.append(f"export default function {comp}() {{")
    L.append("  const [menuOpen, setMenuOpen] = useState(false);")
    L.append(f"  const [modal, setModal] = useState{modal_ty}(null);")
    L.append(f"  const onClaim = (id{_ann(lang, 'number')}) => {{ console.log('claim', id); }};")
    L.append("  const onToggleMenu = () => setMenuOpen((o) => !o);")
    L.append("  const props = { onClaim, menuOpen, onToggleMenu };")
    if popups:
        L.append(f"  const [popup, setPopup] = useState{pop_ty}(null);")
        L.append("  const openAction = (act) => setPopup(act);  // mo popup theo loai nut")
    else:
        # UX: KHONG lo ten bien cau hinh (LINKS.<act>) ra UI cho nguoi dung cuoi.
        # Chi hien thong bao chung; nhac dev qua console.warn (chi hien khi dev).
        L.append("  const openAction = (act) => {")
        L.append('    if (process.env.NODE_ENV !== "production") '
                 "console.warn('[landing] Chua cau hinh link cho \"' + act + '\". "
                 "Dien URL vao LINKS.' + act + ' trong landing.config, hoac goi API tai openAction().');")
        L.append("    setModal({ title: LABELS[act] || \"Thông báo\", "
                 "desc: \"Tính năng đang được cập nhật. Vui lòng quay lại sau.\" });")
        L.append("  };")
    # a11y: dong modal/popup bang phim Esc (hook dat truoc cac mode -> thu tu hook on dinh)
    close_call = "setPopup(null)" if popups else "setModal(null)"
    L.append("  useEffect(() => {")
    L.append(f'    const onKey = (e{_ann(lang, "KeyboardEvent")}) => {{ if (e.key === "Escape") {close_call}; }};')
    L.append('    window.addEventListener("keydown", onKey);')
    L.append('    return () => window.removeEventListener("keydown", onKey);')
    L.append("  }, []);")
    modal_block = ("      <Popups type={popup} onClose={() => setPopup(null)} />" if popups else _LANDING_MODAL)

    def _bg_imgs(y0, hb, indent):
        """JSX cho cac layer nen GIAO voi section [y0, y0+hb) (toa do doi ve goc section).
        LOC THEO GIAO (khong theo tam): nen phu toan trang (vd canh le hoi cao = ca trang)
        phai hien o MOI section no phu, khong chi 1 section chua tam no -> tranh cac
        slide con lai bi nen DEN. Moi slide/section co overflow-hidden nen phan bg trom
        ra ngoai band se bi cat, con lai dung lat cat nen cho band do."""
        out = []
        for bg in board.get("backgrounds", []):
            top, bot = bg["y"], bg["y"] + bg["h"]
            if bot <= y0 or top >= y0 + hb:
                continue   # bg khong giao band nay
            cls = _tw_cls({"x": bg["x"], "y": bg["y"] - y0, "w": bg["w"], "h": bg["h"],
                           "o": bg.get("o", 1), "blend": bg.get("blend")})
            # LCP: nen section dau (bg.lcp) tai NGAY (eager + fetchPriority high),
            # con lai lazy - dong bo voi cach danh dau o component Background.
            _ld = 'loading="eager" fetchPriority="high"' if bg.get("lcp") else 'loading="lazy"'
            out.append(f'{indent}<img key={json.dumps(bg["id"])} src={json.dumps(bg["src"])} '
                       f'alt={json.dumps(bg.get("alt", ""))} {_ld} decoding="async" className="{cls}" />')
        return out

    if swiper_lib:
        refany = "<any>" if lang == "ts" else ""
        qs = "<HTMLElement>" if lang == "ts" else ""
        ash = " as HTMLElement" if lang == "ts" else ""
        L.append("  const [activeIndex, setActiveIndex] = useState(0);")
        L.append(f"  const swiperRef = useRef{refany}(null);")
        L.append(f"  const rootRef = useRef{('<HTMLDivElement>' if lang == 'ts' else '')}(null);")
        L.append(_LANDING_SWIPERLIB_EFFECT.replace("__N__", str(len(secs))).replace("__W__", str(W))
                 .replace("__QS__", qs).replace("__ASH__", ash))
        L.append("  return (")
        L.append(f'    <main ref={{rootRef}}{main_cls}>')
        L.append(h1_jsx)
        if nav_tag:
            L.append(f"      <{nav_tag} />")
        L.append('      <Swiper direction="vertical" slidesPerView={1} effect="fade" fadeEffect={{ crossFade: true }}')
        L.append('        mousewheel={{ sensitivity: 0.3, thresholdDelta: 20, thresholdTime: 300, releaseOnEdges: true }}')
        L.append('        modules={[Mousewheel, EffectFade]} className="w-full h-[100dvh]"')
        L.append('        onSwiper={(sw) => { swiperRef.current = sw; }} onSlideChange={(sw) => setActiveIndex(sw.activeIndex)}>')
        for i, sec in enumerate(secs):
            y0, hb = bands[i]
            L.append(f"        <SwiperSlide key={{{i}}}>")
            L.append('          <div className="w-full flex items-center justify-center overflow-hidden h-[100dvh]">')
            L.append(f'            <div className="slide-stage relative shrink-0 w-[{W}px] h-[{hb}px] origin-center">')
            L += _bg_imgs(y0, hb, "              ")
            L.append(f"              <{sec['comp']} {{...props}} />")
            L.append("            </div>")
            L.append("          </div>")
            L.append("        </SwiperSlide>")
        L.append("      </Swiper>")
        L.append(modal_block)
        L += ["    </main>", "  );", "}", ""]
    elif swiper:
        max_sec_h = max(b[1] for b in bands)
        L.append(_LANDING_SWIPER_EFFECT.replace("useRef(null)", f"useRef{refann}(null)").replace("__W__", str(W)))
        L.append("  return (")
        L.append(f"    <main{main_cls}>")
        L.append(h1_jsx)
        if nav_tag:
            L.append(f"      <{nav_tag} />")
        L.append('      <div ref={ref} className="deck fixed inset-0 overflow-hidden bg-black flex items-center justify-center">')
        L.append(f'        <div ref={{stageRef}} className="relative shrink-0 w-[{W}px] h-[{max_sec_h}px] origin-center">')
        for i, sec in enumerate(secs):
            y0, hb = bands[i]
            _al = json.dumps(sec.get("comp") or f"Section {i + 1}", ensure_ascii=False)
            L.append(f'          <section aria-label={{{_al}}} className="landing-sec absolute left-0 top-0 w-[{W}px] h-[{hb}px]" data-sec="{i}">')
            L += _bg_imgs(y0, hb, "            ")
            L.append(f"            <{sec['comp']} {{...props}} />")
            L.append("          </section>")
        L.append("        </div>")
        L.append("      </div>")
        L.append(modal_block)
        L += ["    </main>", "  );", "}", ""]
    else:
        L.append(f"  const rootRef = useRef{refann}(null);")
        L.append(_LANDING_EFFECT)
        L.append("  return (")
        L.append(f'    <main ref={{rootRef}}{main_cls}>')
        L.append(h1_jsx)
        if nav_tag:
            L.append(f"      <{nav_tag} />")
        L.append(f"      <Stage width={{{W}}} height={{{H}}}>")
        L.append("        <Background />")
        for i, sec in enumerate(secs):
            y0, hb = bands[i]
            rev = "" if i == 0 else " reveal"
            _al = json.dumps(sec.get("comp") or f"Section {i + 1}", ensure_ascii=False)
            L.append(f'        <section aria-label={{{_al}}} className="landing-sec{rev} absolute left-0 top-[{y0}px] '
                     f'w-[{W}px] h-[{hb}px]" data-sec="{i}">')
            L.append(f"          <{sec['comp']} {{...props}} />")
            L.append("        </section>")
        L.append("      </Stage>")
        L.append(modal_block)
        L += ["    </main>", "  );", "}", ""]
    return "\n".join(L)


# cac loai link/nut + nhan hien thi
_LINK_KEYS = ["download", "login", "register", "topup", "gift", "rules", "history", "social", "check"]
_LINK_LABELS = {"download": "Tải game", "login": "Đăng nhập", "register": "Đăng ký", "topup": "Nạp",
                "gift": "Nhận quà", "rules": "Thể lệ", "history": "Lịch sử",
                "social": "Facebook", "check": "Kiểm tra"}


def _env_key(client, k):
    """Ten bien moi truong: Next -> NEXT_PUBLIC_LINK_*, Vite -> VITE_APP_LINK_*."""
    prefix = "NEXT_PUBLIC_LINK_" if client else "VITE_APP_LINK_"
    return prefix + k.upper()


def _gen_config(lang, env_config=False, client=False):
    """File cau hinh LINK/LABEL. env_config=True -> doc tu bien moi truong (.env)."""
    labels = ", ".join(f'{k}: "{_LINK_LABELS[k]}"' for k in _LINK_KEYS)
    if not env_config:
        links = ", ".join(f'{k}: ""' for k in _LINK_KEYS)
        return (
            "// Dien URL that vao LINKS (de trong -> nut se hien popup mau).\n"
            f"export const LINKS = {{ {links} }};\n\n"
            f"export const LABELS = {{ {labels} }};\n"
        )
    src = "process.env" if client else "import.meta.env"
    links = ",\n".join(f'  {k}: {src}.{_env_key(client, k)} || ""' for k in _LINK_KEYS)
    return (
        "// Link/API doc tu bien moi truong (.env). Dien gia tri vao file .env.\n"
        f"const E = {src};\n"
        f"export const LINKS = {{\n{links},\n}};\n\n"
        f"export const LABELS = {{ {labels} }};\n"
    ).replace(src + ".", "E.")


def _gen_env(client=False):
    """Noi dung file .env mau (dien URL that)."""
    head = ("# Next.js: bien cho client PHAI bat dau NEXT_PUBLIC_\n" if client
            else "# Vite: bien cho client PHAI bat dau VITE_APP_\n")
    return head + "\n".join(f"{_env_key(client, k)}=" for k in _LINK_KEYS) + "\n"


# ================= cau hinh du an =================

TAILWIND_REACT = ('/** @type {import(\'tailwindcss\').Config} */\nexport default {\n'
                  '  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],\n  theme: { extend: {} },\n  plugins: [],\n};\n')
TAILWIND_NEXT = ('/** @type {import(\'tailwindcss\').Config} */\nmodule.exports = {\n'
                 '  content: ["./app/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,jsx,ts,tsx}"],\n  theme: { extend: {} },\n  plugins: [],\n};\n')
POSTCSS_ESM = "export default {\n  plugins: { tailwindcss: {}, autoprefixer: {} },\n};\n"
POSTCSS_CJS = "module.exports = {\n  plugins: { tailwindcss: {}, autoprefixer: {} },\n};\n"
CSS_TW = (
    "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n\n"
    "body { background: #000; }\n\n"
    "/* Nut/lien ket bam: hover phong nhe + sang + glow */\n"
    ".hot { cursor: pointer; transition: transform .18s ease, filter .18s ease; transform-origin: center; }\n"
    ".hot:hover { transform: scale(1.06); filter: brightness(1.15) drop-shadow(0 0 14px rgba(255,214,120,.55)); z-index: 60; }\n"
    ".hot:active { transform: scale(.98); }\n\n"
    "/* Nav (fixed): hover + active (scroll-spy) */\n"
    ".navitem { cursor: pointer; transition: transform .18s ease, filter .2s ease; transform-origin: center; }\n"
    ".navitem:hover { transform: scale(1.1); filter: brightness(1.25); }\n"
    ".navitem.active { color: #ffe07a; filter: brightness(1.4) drop-shadow(0 0 10px rgba(255,214,120,.85)); }\n\n"
    "/* Scroll-reveal: section (tru section dau) fade-up khi vao man hinh */\n"
    ".landing-sec.reveal { opacity: 0; transform: translateY(28px); transition: opacity .6s ease, transform .6s ease; }\n"
    ".landing-sec.reveal.in { opacity: 1; transform: none; }\n\n"
    "/* Swiper (full-page): section fade-in khi thanh active */\n"
    ".deck .landing-sec { opacity: 0; transition: opacity .55s ease .15s; }\n"
    ".deck .landing-sec.on { opacity: 1; }\n"
)

TSCONFIG_VITE = json.dumps({
    "compilerOptions": {"target": "ES2020", "useDefineForClassFields": True,
        "lib": ["ES2020", "DOM", "DOM.Iterable"], "module": "ESNext", "skipLibCheck": True,
        "moduleResolution": "bundler", "allowImportingTsExtensions": True, "resolveJsonModule": True,
        "isolatedModules": True, "noEmit": True, "jsx": "react-jsx", "strict": True,
        # noImplicitAny tat: nhieu DOM handler trong template codegen dung chung cho ca
        # JS lan TS -> khong the annotate rieng cho TS ma khong pha JS. strictNullChecks
        # (phan gia tri nhat cua strict) VAN bat. Annotate day du la buoc nang cap sau.
        "noImplicitAny": False, "noUnusedLocals": False, "noUnusedParameters": False},
    "include": ["src"]}, indent=2)
TSCONFIG_NEXT = json.dumps({
    "compilerOptions": {"target": "ES2017", "lib": ["dom", "dom.iterable", "esnext"], "allowJs": True,
        "skipLibCheck": True, "strict": True, "noImplicitAny": False,
        "noUnusedLocals": False, "noUnusedParameters": False,
        "noEmit": True, "esModuleInterop": True, "module": "esnext",
        "moduleResolution": "bundler", "resolveJsonModule": True, "isolatedModules": True, "jsx": "preserve",
        "incremental": True, "plugins": [{"name": "next"}], "paths": {"@/*": ["./*"]}},
    "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"], "exclude": ["node_modules"]}, indent=2)


def _copy_assets(src_out, project_dir, dest):
    src = Path(src_out) / "assets"
    dst = Path(project_dir) / "public" / dest
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def _write_landing_dir(base_dir, board, lang, client, stage_rel, swiper=False, feats=None,
                       pages_dir=None, config_rel="../../landing.config", comp_base=".", popups=None):
    """Ghi building-block components (Layer/Background/section/repeat/nav/popup) vao
    base_dir; page composition (Landing + MobileFluid) vao pages_dir. Neu pages_dir=None
    -> page nam CHUNG base_dir (dung cho Next app-router: route o app/, phan con lai o
    components/). config_rel/comp_base = duong dan import (tu PAGE) toi config va cac
    building-block."""
    base_dir.mkdir(parents=True, exist_ok=True)
    ext = _ext(lang)
    feats = feats or {}
    (base_dir / f"Layer.{ext}").write_text(_gen_layer(lang, client, fx=feats.get("_fx_render")), encoding="utf-8")
    # Background.{ext} CHI duoc import/render o mode mac dinh (cuon doc), khong dung o
    # mode swiper/swiper_lib (nen ve inline trong section). Khop dung dieu kien voi
    # _gen_landing de KHONG ghi file chet.
    _secs = board.get("sections") or []
    _swiper_lib = bool(feats.get("swiper_lib")) and bool(_secs)
    _eff_swiper = (bool(swiper) and bool(_secs)) or _swiper_lib
    if not _eff_swiper:
        (base_dir / f"Background.{ext}").write_text(_gen_background(board, lang, client), encoding="utf-8")
    if board.get("fixed"):
        if feats.get("nav_menu"):
            (base_dir / f"NavMenu.{ext}").write_text(_gen_navmenu(board, lang, client), encoding="utf-8")
        else:
            (base_dir / f"FixedNav.{ext}").write_text(_gen_fixednav(board, lang, client), encoding="utf-8")
    if popups:   # popup dung tu PSD (render theo layer)
        (base_dir / f"Popups.{ext}").write_text(_gen_popups(popups, lang, client), encoding="utf-8")
    elif feats.get("popups"):   # checkbox 'Popup mau' khong co PSD -> stub chu
        (base_dir / f"Popups.{ext}").write_text(_gen_popups_stub(lang, client), encoding="utf-8")
    for sec in board["sections"]:
        (base_dir / f"{sec['comp']}.{ext}").write_text(_gen_section(sec, lang, client), encoding="utf-8")
        for rp in sec["repeats"]:
            (base_dir / f"{rp['comp']}.{ext}").write_text(_gen_repeat(rp, lang, client), encoding="utf-8")
    # page composition -> pages_dir (React) hoac chung base_dir (Next)
    pdir = pages_dir if pages_dir is not None else base_dir
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{board['landing_name']}.{ext}").write_text(
        _gen_landing(board, lang, client, stage_rel, swiper=swiper, feats=feats,
                     config_rel=config_rel, comp_base=comp_base), encoding="utf-8")
    if feats.get("fluid"):
        (pdir / f"MobileFluid.{ext}").write_text(
            _gen_fluid_mobile(board, lang, client, config_rel=config_rel), encoding="utf-8")


def _eslintrc_react(lang):
    """Cau hinh ESLint toi thieu (React hooks). Rule de muc 'warn' -> huu ich ma
    khong bao loi gia. Chi la GATE tuy chon (npm run lint), khong chan build."""
    ext = ('module.exports = {\n'
           '  root: true,\n'
           '  ignorePatterns: ["dist", "build", ".next", "node_modules", "*.config.js"],\n'
           '  env: { browser: true, node: true, es2021: true },\n'
           '  settings: { react: { version: "detect" } },\n'
           '  parserOptions: { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true } },\n'
           '  plugins: ["react-hooks", "react-refresh"],\n')
    if lang == "ts":
        ext += ('  parser: "@typescript-eslint/parser",\n'
                '  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended", "plugin:react-hooks/recommended"],\n'
                '  rules: {\n'
                '    "no-unused-vars": "off",\n'
                '    "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],\n'
                '    "@typescript-eslint/no-explicit-any": "off",\n'
                '    "react-refresh/only-export-components": "off",\n'
                '  },\n}\n')
    else:
        ext += ('  extends: ["eslint:recommended", "plugin:react-hooks/recommended"],\n'
                '  rules: {\n'
                '    "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],\n'
                '    "react-refresh/only-export-components": "off",\n'
                '  },\n}\n')
    return ext


def _gen_use_is_desktop(lang, client):
    """Hook chon MOT cay theo breakpoint (thay cho hidden md:block + block md:hidden ->
    tranh mount CA 2 cay + chay listener song song). SSR mac dinh desktop, chinh lai
    sau khi mount (khong gay hydration mismatch vi doi state o useEffect)."""
    head = '"use client";\n\n' if client else ""
    return head + (
        'import { useEffect, useState } from "react";\n\n'
        "// True khi viewport >= 768px (Tailwind md). Dung matchMedia, cleanup day du.\n"
        "export function useIsDesktop() {\n"
        f"  const [desktop, setDesktop] = useState{('<boolean>' if lang=='ts' else '')}(true);\n"
        "  useEffect(() => {\n"
        '    const mq = window.matchMedia("(min-width: 768px)");\n'
        "    const on = () => setDesktop(mq.matches);\n"
        "    on();\n"
        '    mq.addEventListener("change", on);\n'
        '    return () => mq.removeEventListener("change", on);\n'
        "  }, []);\n"
        "  return desktop;\n}\n")


def _gen_api(lang):
    """apis/landing: ham goi API cua BE (stub). Dien endpoint that vao day."""
    ret = " : Promise<unknown>" if lang == "ts" else ""
    return ("// API landing: dien endpoint that cua BE vao day roi bo comment.\n"
            f"export async function fetchLandingData(){ret} {{\n"
            "  // const res = await fetch('/api/landing');\n"
            "  // return res.json();\n"
            "  return null;\n}\n")


def _api_hook(lang, api_rel="../apis/landing"):
    """hooks/useLandingData: goi apis/landing.fetchLandingData va giu vao state."""
    return ('import { useEffect, useState } from "react";\n'
            f'import {{ fetchLandingData }} from "{api_rel}";\n\n'
            "// Hook lay data landing tu API cua BE (logic goi nam o apis/landing).\n"
            "export function useLandingData() {\n"
            f"  const [data, setData] = useState{('<unknown>' if lang=='ts' else '')}(null);\n"
            "  useEffect(() => {\n"
            "    fetchLandingData().then(setData).catch(() => {});\n"
            "  }, []);\n  return data;\n}\n")


def _gen_routes(board, mobile, fluid, lang):
    """routes.tsx (React): dinh nghia router bang react-router-dom. Route '/' -> trang
    Landing; neu co ban mobile/fluid thi bao boc bang useIsDesktop de chon 1 cay."""
    landing = board["landing_name"]
    imports = ['import { createBrowserRouter } from "react-router-dom";',
               f'import {landing} from "./pages/{landing}";']
    home, element = "", f"<{landing} />"
    if mobile:
        mname = mobile["board"]["landing_name"]
        imports.append(f'import {mname} from "./pages/{mname}";')
        imports.append('import { useIsDesktop } from "./hooks/useIsDesktop";')
        home = ("\nfunction Home() {\n  const isDesktop = useIsDesktop();\n"
                f"  return isDesktop ? <{landing} /> : <{mname} />;\n}}\n")
        element = "<Home />"
    elif fluid:
        imports.append('import MobileFluid from "./pages/MobileFluid";')
        imports.append('import { useIsDesktop } from "./hooks/useIsDesktop";')
        home = ("\nfunction Home() {\n  const isDesktop = useIsDesktop();\n"
                f"  return isDesktop ? <{landing} /> : <MobileFluid />;\n}}\n")
        element = "<Home />"
    return ("\n".join(imports) + "\n" + home +
            f'\nexport const router = createBrowserRouter([{{ path: "/", element: {element} }}]);\n')


def _gen_app_react():
    """App.tsx (React): root, gan RouterProvider + import CSS global."""
    return ('import { RouterProvider } from "react-router-dom";\n'
            'import { router } from "./routes";\n'
            'import "./styles/index.css";\n\n'
            "export default function App() {\n"
            "  return <RouterProvider router={router} />;\n}\n")


# ---------- REACT (Vite) ----------

def _seo_into_board(layout, board):
    """Gan tieu de/mo ta (text goc, dung hoa thuong) + danh dau LCP cho board."""
    texts = _seo_texts_from_layout(layout)
    if texts:
        board.setdefault("page_title", texts[0])
        board.setdefault("page_desc", " · ".join(texts[:6]))
    _mark_lcp(board)


def _lcp_src(board):
    """Duong dan anh LCP (de preload). None neu khong co."""
    for it in list(board.get("backgrounds", [])) + [l for s in board.get("sections", [])[:1]
                                                     for l in s.get("flat", [])]:
        if it.get("lcp"):
            return it.get("src")
    return None


def _export_react(out_dir, layout, board, mobile, lang, swiper=False, feats=None, popups=None):
    feats = feats or {}
    _seo_into_board(layout, board)
    proj = Path(out_dir) / "react-app"
    ext = _ext(lang)
    src = proj / "src"
    # DON sach src cu truoc khi sinh - tranh lan file .jsx (JS) va .tsx (TS) trong
    # cung thu muc: import khong duoi (vd "./Landing") se nap NHAM ban cu (Vite uu
    # tien .jsx truoc .tsx) -> ra dung code cu. (node_modules/dist/package.json o
    # ngoai src nen khong bi xoa.)
    if src.exists():
        shutil.rmtree(src, ignore_errors=True)
    dext = _dext(lang)
    fluid = feats.get("fluid") and not mobile
    (src / "components").mkdir(parents=True, exist_ok=True)
    (src / "components" / f"Stage.{ext}").write_text(_gen_stage(lang, client=False), encoding="utf-8")
    # building-blocks -> src/components/landing[-mobile]; page composition -> src/pages
    _write_landing_dir(src / "components" / "landing", board, lang, False, "../components/Stage",
                       swiper=swiper, feats=feats, pages_dir=src / "pages",
                       config_rel="../constants/landing.config", comp_base="../components/landing", popups=popups)
    if mobile:
        _write_landing_dir(src / "components" / "landing-mobile", mobile["board"], lang, False,
                           "../components/Stage", swiper=swiper, feats=feats, pages_dir=src / "pages",
                           config_rel="../constants/landing.config", comp_base="../components/landing-mobile", popups=popups)
    if lang == "ts":
        (src / "types").mkdir(exist_ok=True)
        (src / "types" / "landing.ts").write_text(_gen_types(), encoding="utf-8")
        (src / "vite-env.d.ts").write_text('/// <reference types="vite/client" />\n', encoding="utf-8")
    # apis (goi BE) + hooks (custom hook)
    (src / "apis").mkdir(exist_ok=True)
    (src / "apis" / f"landing.{dext}").write_text(_gen_api(lang), encoding="utf-8")
    (src / "hooks").mkdir(exist_ok=True)
    (src / "hooks" / f"useLandingData.{dext}").write_text(_api_hook(lang, "../apis/landing"), encoding="utf-8")
    if mobile or fluid:  # hook chon 1 cay theo breakpoint (dung o routes.tsx)
        (src / "hooks" / f"useIsDesktop.{dext}").write_text(
            _gen_use_is_desktop(lang, client=False), encoding="utf-8")
    # constants (LINKS/LABELS)
    (src / "constants").mkdir(exist_ok=True)
    (src / "constants" / f"landing.config.{dext}").write_text(
        _gen_config(lang, feats.get("env_config"), client=False), encoding="utf-8")
    if feats.get("env_config"):
        (proj / ".env").write_text(_gen_env(client=False), encoding="utf-8")
    # styles (css global)
    (src / "styles").mkdir(exist_ok=True)
    (src / "styles" / "index.css").write_text(
        CSS_TW + (FX_CSS if feats.get("_fx_render") else "") + (FX_REVEAL_CSS if feats.get("fx_reveal") else ""),
        encoding="utf-8")
    # router + root + entry
    (src / f"routes.{ext}").write_text(_gen_routes(board, mobile, fluid, lang), encoding="utf-8")
    (src / f"App.{ext}").write_text(_gen_app_react(), encoding="utf-8")
    nn = "!" if lang == "ts" else ""
    (src / f"main.{ext}").write_text(
        'import { createRoot } from "react-dom/client";\nimport App from "./App";\n\n'
        f'createRoot(document.getElementById("root"){nn}).render(<App />);\n', encoding="utf-8")
    import html as _h
    _t = _h.escape(_page_title(board), quote=True)
    _d = _h.escape(_page_desc(board), quote=True)
    _fav = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
            "<text y='.9em' font-size='90'>%F0%9F%8E%AE</text></svg>")
    _lcp = _lcp_src(board)
    _preload = f'<link rel="preload" as="image" href="{_h.escape(_lcp, quote=True)}" fetchpriority="high"/>\n' if _lcp else ""
    (proj / "index.html").write_text(
        '<!doctype html>\n<html lang="vi">\n<head>\n<meta charset="UTF-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0"/>\n'
        f'<title>{_t}</title>\n'
        f'<meta name="description" content="{_d}"/>\n'
        '<meta property="og:type" content="website"/>\n'
        f'<meta property="og:title" content="{_t}"/>\n'
        f'<meta property="og:description" content="{_d}"/>\n'
        '<meta name="twitter:card" content="summary_large_image"/>\n'
        f'<meta name="twitter:title" content="{_t}"/>\n'
        f'<meta name="twitter:description" content="{_d}"/>\n'
        '<meta name="theme-color" content="#0b1120"/>\n'
        f'<link rel="icon" href="{_fav}"/>\n{_preload}</head>\n<body>\n'
        f'<div id="root"></div>\n<script type="module" src="/src/main.{ext}"></script>\n</body>\n</html>\n',
        encoding="utf-8")
    (proj / "public").mkdir(exist_ok=True)
    (proj / "public" / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    (proj / "vite.config.js").write_text(
        'import { defineConfig } from "vite";\nimport react from "@vitejs/plugin-react";\n\n'
        'export default defineConfig({ plugins: [react()] });\n', encoding="utf-8")
    (proj / "tailwind.config.js").write_text(TAILWIND_REACT, encoding="utf-8")
    (proj / "postcss.config.js").write_text(POSTCSS_ESM, encoding="utf-8")
    dev = {"@vitejs/plugin-react": "^4.3.1", "vite": "^5.4.0",
           "tailwindcss": "^3.4.10", "postcss": "^8.4.41", "autoprefixer": "^10.4.20",
           "eslint": "^8.57.0", "eslint-plugin-react-hooks": "^4.6.2",
           "eslint-plugin-react-refresh": "^0.4.9"}
    # gate toi thieu truoc khi commit/deploy: lint + (voi TS) typecheck
    scripts = {"dev": "vite", "build": "vite build", "preview": "vite preview",
               "lint": "eslint . --ext .js,.jsx,.ts,.tsx"}
    if lang == "ts":
        dev.update({"typescript": "^5.5.4", "@types/react": "^18.3.3", "@types/react-dom": "^18.3.0",
                    "@types/node": "^20", "@typescript-eslint/parser": "^7.18.0",
                    "@typescript-eslint/eslint-plugin": "^7.18.0"})
        scripts["typecheck"] = "tsc --noEmit"
        (proj / "tsconfig.json").write_text(TSCONFIG_VITE, encoding="utf-8")
    (proj / ".eslintrc.cjs").write_text(_eslintrc_react(lang), encoding="utf-8")
    deps = {"react": "^18.3.1", "react-dom": "^18.3.1", "react-router-dom": "^6.26.0"}
    if feats.get("swiper_lib"):
        deps["swiper"] = "^11.2.6"
    (proj / "package.json").write_text(json.dumps({
        "name": _slug(layout.get("source", "psd-landing")), "private": True, "version": "0.1.0", "type": "module",
        "scripts": scripts,
        "dependencies": deps, "devDependencies": dev}, indent=2), encoding="utf-8")
    _copy_assets(out_dir, proj, "assets")
    if mobile:
        _copy_assets(mobile["dir"], proj, "assets-m")
    for p in (popups or []):   # moi popup: assets rieng /assets-<id>
        _copy_assets(p["dir"], proj, f"assets-{p['id']}")
    _write_readme(proj, board, mobile, "npm run dev", lang)
    return proj


# ---------- NEXT ----------

def _export_next(out_dir, layout, board, mobile, lang, swiper=False, feats=None, popups=None):
    feats = feats or {}
    _seo_into_board(layout, board)
    proj = Path(out_dir) / "next-app"
    ext = _ext(lang)
    # DON cac thu muc cu (tranh lan .jsx/.tsx -> import khong duoi nap nham ban cu)
    for d in ("app", "components", "types", "lib", "hooks", "apis", "constants"):
        p = proj / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    dext = _dext(lang)
    fluid = feats.get("fluid") and not mobile
    (proj / "app").mkdir(parents=True, exist_ok=True)
    (proj / "components").mkdir(parents=True, exist_ok=True)
    (proj / "components" / f"Stage.{ext}").write_text(_gen_stage(lang, client=True), encoding="utf-8")
    # Next app-router: route nam o app/, phan con lai (building-block + page composition
    # Landing) o components/. config_rel tinh tu components/landing/ (sau 2 cap).
    _write_landing_dir(proj / "components" / "landing", board, lang, True, "../Stage",
                       swiper=swiper, feats=feats, pages_dir=None,
                       config_rel="../../constants/landing.config", comp_base=".", popups=popups)
    if mobile:
        _write_landing_dir(proj / "components" / "landing-mobile", mobile["board"], lang, True, "../Stage",
                           swiper=swiper, feats=feats, pages_dir=None,
                           config_rel="../../constants/landing.config", comp_base=".", popups=popups)
    if lang == "ts":
        (proj / "types").mkdir(exist_ok=True)
        (proj / "types" / "landing.ts").write_text(_gen_types(), encoding="utf-8")
        (proj / "next-env.d.ts").write_text(
            '/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n', encoding="utf-8")
    # apis (goi BE) + hooks (custom hook - o Next PHAI "use client")
    (proj / "apis").mkdir(exist_ok=True)
    (proj / "apis" / f"landing.{dext}").write_text(_gen_api(lang), encoding="utf-8")
    (proj / "hooks").mkdir(exist_ok=True)
    (proj / "hooks" / f"useLandingData.{dext}").write_text(
        '"use client";\n' + _api_hook(lang, "../apis/landing"), encoding="utf-8")
    if mobile or fluid:
        (proj / "hooks" / f"useIsDesktop.{dext}").write_text(
            _gen_use_is_desktop(lang, client=True), encoding="utf-8")
    # constants (LINKS/LABELS)
    (proj / "constants").mkdir(exist_ok=True)
    (proj / "constants" / f"landing.config.{dext}").write_text(
        _gen_config(lang, feats.get("env_config"), client=True), encoding="utf-8")
    if feats.get("env_config"):
        (proj / ".env").write_text(_gen_env(client=True), encoding="utf-8")

    (proj / "app" / "globals.css").write_text(
        CSS_TW + (FX_CSS if feats.get("_fx_render") else "") + (FX_REVEAL_CSS if feats.get("fx_reveal") else ""),
        encoding="utf-8")
    _mt = _ann(lang, "import('next').Metadata")
    _meta = json.dumps({
        "title": _page_title(board),
        "description": _page_desc(board),
        "openGraph": {"title": _page_title(board), "description": _page_desc(board), "type": "website"},
        "twitter": {"card": "summary_large_image", "title": _page_title(board), "description": _page_desc(board)},
    }, ensure_ascii=False, indent=2)
    (proj / "app" / f"layout.{ext}").write_text(
        'import "./globals.css";\n\n'
        f'export const metadata{_mt} = {_meta};\n\n'
        'export const viewport = { themeColor: "#0b1120" };\n\n'
        f'export default function RootLayout({{ children }}{_ann(lang, "{ children: React.ReactNode }")}) {{\n'
        '  return (<html lang="vi"><body>{children}</body></html>);\n}\n', encoding="utf-8")
    (proj / "public").mkdir(exist_ok=True)
    (proj / "public" / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    imp = [f'import Landing from "../components/landing/{board["landing_name"]}";']
    mcomp = "MLanding" if mobile else ("MobileFluid" if fluid else None)
    if mobile:
        imp.append(f'import MLanding from "../components/landing-mobile/{mobile["board"]["landing_name"]}";')
    elif fluid:
        imp.append('import MobileFluid from "../components/landing/MobileFluid";')
    if mcomp:
        # Mount MOT cay theo breakpoint (xem hook). page thanh client component vi
        # dung hook; metadata van nam o layout.tsx (server) nen SEO khong anh huong.
        imp.append('import { useIsDesktop } from "../hooks/useIsDesktop";')
        page = ('"use client";\n\n' + "\n".join(imp) + "\n\n"
                "export default function Page() {\n"
                "  const isDesktop = useIsDesktop();\n"
                f"  return (\n    <>{{isDesktop ? <Landing /> : <{mcomp} />}}</>\n  );\n}}\n")
    else:
        page = ("\n".join(imp) + "\n\nexport default function Page() {\n"
                "  return (\n    <>\n      <Landing />\n    </>\n  );\n}\n")
    (proj / "app" / f"page.{ext}").write_text(page, encoding="utf-8")

    # images.formats: uu tien AVIF/WebP khi dung next/image optimizer (chay tren
    # `next start`/Vercel). LUU Y: hien component van dung <img> thuong; de huong loi
    # tu day can doi sang <Image> cua next/image (viec nay dang hoan - xem README yeu cau).
    (proj / "next.config.js").write_text(
        "/** @type {import('next').NextConfig} */\n"
        "module.exports = {\n"
        "  images: { formats: ['image/avif', 'image/webp'] },\n"
        "};\n", encoding="utf-8")
    (proj / "tailwind.config.js").write_text(TAILWIND_NEXT, encoding="utf-8")
    (proj / "postcss.config.js").write_text(POSTCSS_CJS, encoding="utf-8")
    dev = {"tailwindcss": "^3.4.10", "postcss": "^8.4.41", "autoprefixer": "^10.4.20",
           "eslint": "^8.57.0", "eslint-config-next": "^14.2.5"}
    # gate toi thieu: `next lint` + (voi TS) typecheck
    nscripts = {"dev": "next dev", "build": "next build", "start": "next start", "lint": "next lint"}
    if lang == "ts":
        dev.update({"typescript": "^5.5.4", "@types/react": "^18.3.3", "@types/react-dom": "^18.3.0", "@types/node": "^20"})
        nscripts["typecheck"] = "tsc --noEmit"
        (proj / "tsconfig.json").write_text(TSCONFIG_NEXT, encoding="utf-8")
    # Next dung eslint-config-next (core-web-vitals) - khong can plugin react-hooks rieng
    (proj / ".eslintrc.json").write_text(
        json.dumps({"extends": "next/core-web-vitals"}, indent=2), encoding="utf-8")
    ndeps = {"next": "^14.2.5", "react": "^18.3.1", "react-dom": "^18.3.1"}
    if feats.get("swiper_lib"):
        ndeps["swiper"] = "^11.2.6"
    (proj / "package.json").write_text(json.dumps({
        "name": _slug(layout.get("source", "psd-landing")), "private": True, "version": "0.1.0",
        "scripts": nscripts,
        "dependencies": ndeps,
        "devDependencies": dev}, indent=2), encoding="utf-8")
    _copy_assets(out_dir, proj, "assets")
    if mobile:
        _copy_assets(mobile["dir"], proj, "assets-m")
    for p in (popups or []):   # moi popup: assets rieng /assets-<id>
        _copy_assets(p["dir"], proj, f"assets-{p['id']}")
    _write_readme(proj, board, mobile, "npm run dev", lang)
    return proj


def _write_readme(proj, board, mobile, run_cmd, lang):
    lines = [f"# Export ({'TypeScript' if lang == 'ts' else 'JavaScript'})", "",
             "```bash", "npm install", run_cmd, "```", "",
             "## Cau truc component", "",
             "- `components/Stage` - khung responsive (tu co gian).",
             "- `components/landing/` - moi SECTION la 1 component rieng:"]
    for sec in board["sections"]:
        reps = ", ".join(rp["comp"] for rp in sec["repeats"])
        lines.append(f"  - `{sec['comp']}`" + (f" (cum lap: {reps})" if reps else ""))
    if mobile:
        lines.append("- `components/landing-mobile/` - ban mobile rieng (hien duoi breakpoint md).")
    lines += ["", "## Tich hop API",
              "- Cac cum lap render bang `.map()` qua mang `*Data` trong file section - thay bang data BE.",
              "- Nut 'Nhan Qua' goi `onClaim(id)` (sua trong Landing).",
              "- O vat pham: dien `item.items = [{src,x,y,w,h}]`.",
              "- `item.claimed = true` -> lop mo da nhan.",
              "- Hook `useLandingData` de cam endpoint that."]
    (proj / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _dext(lang):
    return "ts" if lang == "ts" else "js"


# ================= entry =================

def _load_variant(vdir, asset_dir, comp_prefix, detect_repeats=False, feats=None, lang="js", model=None):
    feats = feats or {}
    vdir = Path(vdir)
    layout = json.loads((vdir / "layout.json").read_text(encoding="utf-8"))
    # Thanh CO DINH (nav/logo lap giua cac section) -> tach thanh FixedNav, render 1 lan.
    from .fixed_overlay import detect_fixed_overlay
    fixed_items, drop_ids = detect_fixed_overlay(vdir, layout)
    board = _artboards_from_layout(layout, asset_dir, comp_prefix, extra_exclude=drop_ids,
                                   detect_repeats=detect_repeats, fx_auto=bool(feats.get("fx")))
    fx, navk = [], 0
    for it in fixed_items:
        # muc menu bam duoc: chu ngan (loai logo to, icon chuot cao, duong ke mong)
        isnav = bool(it.get("alt")) and 15 <= it["w"] <= 220 and 15 <= it["h"] <= 60
        fx.append({
            "src": _src(it["asset"], asset_dir), "x": it["x"], "y": it["y"],
            "w": it["w"], "h": it["h"], "o": it.get("o", 1), "blend": it.get("blend"),
            "alt": it.get("alt", ""), "href": it.get("href"),
            "nav": (navk if isnav else None),
        })
        if isnav:
            navk += 1
    board["fixed"] = fx
    if not layout.get("artboards"):
        board["H"] = _content_bottom_from_image(
            vdir / layout.get("screenshot", "screenshot.png"), layout["canvas"]["height"])
    _split_sections(board, layout)
    if feats.get("ai_enhance"):
        try:
            from .ai_enhance import enhance_board
            from .ai_convert import DEFAULT_MODEL
            print(f"[AI] Prod-hoa {len(board['sections'])} section bang AI ...")
            enhance_board(vdir, board, lang=lang, model=model or DEFAULT_MODEL)
        except Exception as e:
            print(f"[AI] Bo qua enhance (loi): {e}")
    return layout, board


def export(out_dir, framework="react", lang="js", mobile_dir=None, detect_repeats=False,
           swiper=False, feats=None, popup_dirs=None):
    out_dir = Path(out_dir)
    if lang not in ("ts", "js"):
        lang = "js"
    feats = dict(feats or {})
    # swiper_lib (Swiper.js that) keo theo che do full-page
    if feats.get("swiper_lib"):
        swiper = True
    feats["swiper"] = swiper
    layout, board = _load_variant(out_dir, "assets", "", detect_repeats, feats=feats, lang=lang)
    mobile = None
    if mobile_dir:
        m_layout, m_board = _load_variant(mobile_dir, "assets-m", "M", detect_repeats, feats=feats, lang=lang)
        mobile = {"dir": Path(mobile_dir), "layout": m_layout, "board": m_board}

    # POPUP tu PSD: moi popup = 1 board rieng (assets rieng /assets-<id>), render theo
    # layer trong modal. popup_dirs = [{"id","name","dir"}]. Khong ai_enhance/repeat cho popup.
    popups = []
    for pinfo in (popup_dirs or []):
        pid = pinfo["id"]
        p_layout, p_board = _load_variant(pinfo["dir"], f"assets-{pid}", pid.upper(),
                                          detect_repeats=False, feats={}, lang=lang)
        popups.append({"id": pid, "name": pinfo.get("name") or pid, "dir": Path(pinfo["dir"]),
                       "w": p_board["W"], "h": p_board["H"], "flat": _popup_flat(p_board)})
    if popups:
        feats["popups"] = True   # bat he popup (Landing import + wiring setPopup)

    # fx_render: sinh Layer co xu ly fx + kem FX_CSS khi bat AUTO (feats.fx) HOAC co
    # layer nao duoc gan hieu ung TAY (l['fx']) trong editor -> hieu ung tay luon chay.
    def _has_manual_fx(lay):
        return any(l.get("fx") for l in (lay or {}).get("layers", []))
    feats["_fx_render"] = bool(feats.get("fx") or _has_manual_fx(layout)
                               or (mobile and _has_manual_fx(mobile["layout"])))

    proj = _export_next(out_dir, layout, board, mobile, lang, swiper=swiper, feats=feats, popups=popups) \
        if framework == "next" \
        else _export_react(out_dir, layout, board, mobile, lang, swiper=swiper, feats=feats, popups=popups)

    nsec = len(board["sections"])
    nrep = sum(len(s["repeats"]) for s in board["sections"])
    nfix = len(board.get("fixed", []))
    print(f"[{framework}/{lang}{' +mobile' if mobile else ''}] {nsec} section, {nrep} cum lap"
          + (f", {nfix} phan tu CO DINH (FixedNav)" if nfix else "") + f" -> {proj}")
    for s in board["sections"]:
        tag = " (" + ", ".join(rp["comp"] + f" x{rp['count']}" for rp in s["repeats"]) + ")" if s["repeats"] else ""
        print(f"    section {s['comp']}{tag}")
    return proj


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "output"
    fw = sys.argv[2] if len(sys.argv) > 2 else "react"
    lg = sys.argv[3] if len(sys.argv) > 3 else "js"
    export(d, fw, lg)
