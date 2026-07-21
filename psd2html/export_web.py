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


def _build_flat(layers, ab_bbox, exclude, asset_dir, menu_ids, toggle_id):
    ax, ay = ab_bbox["x"], ab_bbox["y"]
    items = []
    for l in layers:
        if not l.get("asset") or l["id"] in exclude:
            continue
        b = l["bbox"]
        cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        if not (ax <= cx < ax + ab_bbox["width"] and ay <= cy < ay + ab_bbox["height"]):
            continue
        item = {"id": l["id"], "src": _src(l["asset"], asset_dir),
                "x": b["x"] - ax, "y": b["y"] - ay, "w": b["width"], "h": b["height"],
                "o": l.get("opacity", 1), "blend": l.get("blend"),
                "alt": _alt_of(l), "href": "#" if _is_interactive(l) else None,
                "act": _action_of(l) if _is_interactive(l) else None,
                "t": l.get("kind") == "type"}
        if toggle_id and l["id"] == toggle_id:
            item["toggle"] = True
            item["href"] = None
        elif menu_ids and l["id"] in menu_ids:
            item["menu"] = True
        items.append(item)
    return items


# ================= chia section =================

def _looks_title(alt):
    if not alt or len(alt) > 40:
        return False
    if re.fullmatch(r"[0-9a-f]{6,}.*", alt):   # ten dang hash
        return False
    return bool(re.search(r"[a-zàáâãèéêìíòóôõùúăâêôơưỳý/ ]", alt)) and (" " in alt or len(alt) <= 16)


def _section_name(flat, W, H, y0, y1, idx, used):
    """Dat ten section theo tieu de noi bat (neu doan duoc), khong thi Section{n}."""
    band_h = max(1, y1 - y0)
    # chi lay LAYER CHU (t=True) lam tieu de section; uu tien o tren cung
    cands = [it for it in flat if it.get("t") and it["y"] < y0 + band_h * 0.6 and _looks_title(it["alt"])]
    cands.sort(key=lambda it: (it["y"], -it["w"]))
    name = _pascal(cands[0]["alt"])[:24] if cands else f"Section{idx + 1}"
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
    # nen phu toan trang -> component Background rieng
    bg = [it for it in flat if it["h"] >= 0.5 * H or it["w"] >= 0.85 * W]
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
        explicit = band_names[i] if i < len(band_names) else None
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
                           detect_repeats=False):
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
    flat = _build_flat(layout["layers"], ab, consumed, asset_dir, menu_ids, toggle_id)
    stem = Path(layout.get("source", "Page")).stem
    board = {"comp": comp_prefix + "Landing", "landing_name": comp_prefix + "Landing",
             "W": cw, "H": ch, "flat": flat, "repeats": repeats, "has_menu": bool(toggle_id)}
    return board


# ================= sinh JSX/TSX =================

def _gen_types():
    return (
        "export interface LayerItem {\n"
        "  id: string; src: string; x: number; y: number; w: number; h: number;\n"
        "  o: number; blend?: string | null; alt?: string;\n"
        "  href?: string | null; act?: string | null; menu?: boolean; toggle?: boolean;\n}\n\n"
        "export interface FixedItem {\n"
        "  src: string; x: number; y: number; w: number; h: number;\n"
        "  o: number; blend?: string | null; alt?: string; href?: string | null; nav?: number | null;\n}\n\n"
        "export interface SlotItem { src: string; x: number; y: number; w: number; h: number; alt?: string; }\n\n"
        "export interface RepeatItem {\n"
        "  id: number; x: number; y: number; claimed?: boolean;\n"
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


def _gen_popups(lang, client):
    """He popup stub (login/the le/lich su/nap dau...). type=null -> khong hien."""
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
        '      style={{ position: "fixed", inset: 0, background: "rgba(4,8,20,.72)", display: "flex",\n'
        '        alignItems: "center", justifyContent: "center", zIndex: 3000 }}>\n'
        '      <div style={{ position: "relative", background: "#111a2e", border: "1px solid #33507e",\n'
        '        borderRadius: 16, padding: "30px 34px", maxWidth: 460, width: "90%", color: "#e8eeff", textAlign: "center" }}>\n'
        '        <button onClick={onClose} style={{ position: "absolute", top: 8, right: 14,\n'
        '          background: "none", border: 0, color: "#7d90b5", fontSize: 24, cursor: "pointer" }}>&times;</button>\n'
        '        <h3 style={{ margin: "0 0 10px", fontSize: 20 }}>{TITLES[type] || "Thông báo"}</h3>\n'
        '        <p style={{ margin: "0 0 20px", color: "#9db0d6", fontSize: 14, lineHeight: 1.5 }}>\n'
        "          {DESCS[type] || ('Chức năng \"' + type + '\": cắm nội dung / API tại đây.')}</p>\n"
        '        <button onClick={onClose} style={{ background: "linear-gradient(90deg,#2563eb,#3b82f6)",\n'
        '          color: "#fff", border: 0, borderRadius: 9, padding: "11px 26px", fontWeight: 700, cursor: "pointer" }}>Đóng</button>\n'
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


def _gen_layer(lang, client):
    head = '"use client";\n\n' if client else ""
    imp = 'import type { LayerItem } from "../../types/landing";\n\n' if lang == "ts" else ""
    sig = ("{ l, menuOpen, onToggleMenu }: { l: LayerItem; menuOpen?: boolean; onToggleMenu?: () => void }"
           if lang == "ts" else "{ l, menuOpen, onToggleMenu }")
    style_ty = _ann(lang, "React.CSSProperties")
    react_imp = 'import type React from "react";\n' if lang == "ts" else ""
    return head + react_imp + imp + (
        f"// 1 lop anh (img); tu xu ly nut menu (toggle) va an/hien menu.\n"
        f"export default function Layer({sig}) {{\n"
        f"  const style{style_ty} = {{ left: l.x, top: l.y, width: l.w, height: l.h, opacity: l.o, mixBlendMode: (l.blend || undefined){_ann(lang,'any') and ' as any' or ''} }};\n"
        "  if (l.toggle) {\n"
        "    return (\n"
        '      <button onClick={onToggleMenu} title={l.alt}\n'
        '        className="absolute block cursor-pointer transition hover:brightness-110" style={style}>\n'
        '        <img src={l.src} alt={l.alt} className="block w-full h-full" loading="lazy" decoding="async" />\n'
        "      </button>\n    );\n  }\n"
        "  if (l.menu && !menuOpen) return null;\n"
        "  return l.href ? (\n"
        '    <a href={l.href} data-action={l.act || "other"} title={l.alt} className="hot absolute block" style={style}>\n'
        '      <img src={l.src} alt={l.alt} className="block w-full h-full" loading="lazy" decoding="async" />\n'
        "    </a>\n  ) : (\n"
        '    <img src={l.src} alt={l.alt} className="absolute block" style={style} loading="lazy" decoding="async" />\n  );\n}\n')


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
        if it.get("menu"):
            o["menu"] = True
        if it.get("toggle"):
            o["toggle"] = True
        keep.append(o)
    return json.dumps(keep, ensure_ascii=False, indent=2)


def _gen_background(board, lang, client):
    head = '"use client";\n\n' if client else ""
    imp = 'import type { LayerItem } from "../../types/landing";\n\n' if lang == "ts" else ""
    decl = f"const bg{_ann(lang, 'LayerItem[]')} = {_flat_json(board['backgrounds'])};\n\n"
    return head + imp + decl + (
        "export default function Background() {\n  return (\n    <>\n"
        "      {bg.map((l) => (\n"
        '        <img key={l.id} src={l.src} alt={l.alt} className="absolute block" loading="lazy" decoding="async"\n'
        "          style={{ left: l.x, top: l.y, width: l.w, height: l.h, opacity: l.o, mixBlendMode: (l.blend || undefined)"
        + (' as any' if lang == "ts" else "") + " }} />\n"
        "      ))}\n    </>\n  );\n}\n")


def _gen_repeat(rp, lang, client):
    head = '"use client";\n\n' if client else ""
    imp = 'import type { RepeatItem } from "../../types/landing";\n\n' if lang == "ts" else ""
    sig = ("{ item, onClaim }: { item: RepeatItem; onClaim?: (id: number) => void }"
           if lang == "ts" else "{ item, onClaim }")
    if rp["grid"].get("is_grid"):
        root = f'    <div className="relative shrink-0" style={{{{ width: {rp["W"]}, height: {rp["H"]} }}}}>'
    else:  # cum bat quy tac (so le) -> giu absolute theo item.x/item.y
        root = (f'    <div className="absolute" style={{{{ left: item.x, top: item.y, '
                f'width: {rp["W"]}, height: {rp["H"]} }}}}>')
    L = [head + imp, f"export default function {rp['comp']}({sig}) {{",
         "  return (", root]
    for sl in rp["slots"]:
        style = (f'{{{{ left: {sl["rx"]}, top: {sl["ry"]}, width: {sl["w"]}, height: {sl["h"]}, opacity: {sl["o"]}'
                 + (f', mixBlendMode: "{sl["blend"]}"' if sl.get("blend") else "") + " }}")
        if sl["kind"] == "button":
            L.append(f'      <button onClick={{() => onClaim && onClaim(item.id)}} title="{sl["alt"]}"')
            L.append(f'        className="absolute block cursor-pointer transition hover:brightness-110" style={style}>')
            L.append(f'        <img src="{sl["asset"]}" alt="{sl["alt"]}" className="block w-full h-full" />')
            L.append("      </button>")
        elif sl["kind"] == "var":
            L.append(f'      {{item.{sl["var"]} ? <img className="absolute block" style={style} '
                     f'src={{item.{sl["var"]} as string}} alt="{sl["alt"]}" /> : null}}'
                     if lang == "ts" else
                     f'      {{item.{sl["var"]} && <img className="absolute block" style={style} '
                     f'src={{item.{sl["var"]}}} alt="{sl["alt"]}" />}}')
        else:
            L.append(f'      <img className="absolute block" style={style} src="{sl["asset"]}" alt="{sl["alt"]}" />')
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
            body.append(f'      <div style={{{{ position: "absolute", left: {g["x"]}, top: {g["y"] - y0}, '
                        f'width: {g["w"]}, display: "flex", flexWrap: "wrap", justifyContent: "center", '
                        f'alignContent: "flex-start", gap: "{g["gy"]}px {g["gx"]}px" }}}}>')
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
      e.preventDefault();
      const act = a.getAttribute("data-action") || "other";
      const url = LINKS[act];
      if (url) { window.open(url, "_blank"); return; }
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
          style={{ position: "fixed", inset: 0, background: "rgba(4,8,20,.72)", display: "flex",
            alignItems: "center", justifyContent: "center", zIndex: 3000 }}>
          <div style={{ position: "relative", background: "#111a2e", border: "1px solid #33507e",
            borderRadius: 16, padding: "30px 34px", maxWidth: 420, width: "90%", color: "#e8eeff", textAlign: "center" }}>
            <button onClick={() => setModal(null)} style={{ position: "absolute", top: 8, right: 14,
              background: "none", border: 0, color: "#7d90b5", fontSize: 24, cursor: "pointer" }}>&times;</button>
            <h3 style={{ margin: "0 0 10px", fontSize: 20 }}>{modal.title}</h3>
            <p style={{ margin: "0 0 20px", color: "#9db0d6", fontSize: 14, lineHeight: 1.5 }}>{modal.desc}</p>
            <button onClick={() => setModal(null)} style={{ background: "linear-gradient(90deg,#2563eb,#3b82f6)",
              color: "#fff", border: 0, borderRadius: 9, padding: "11px 26px", fontWeight: 700, cursor: "pointer" }}>Đóng</button>
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
    const fit = () => { s = Math.min(1, deck.clientWidth / __W__); stage.style.transform = `scale(${s})`; };
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
    const onClick = (e) => { const a = e.target.closest(".hot"); if (!a || !deck.contains(a)) return; e.preventDefault();
      const act = a.getAttribute("data-action") || "other"; const url = LINKS[act];
      if (url) { window.open(url, "_blank"); return; }
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
    const fit = () => { const s = Math.min(1, window.innerWidth / __W__);
      root.querySelectorAll__QS__(".slide-stage").forEach((el) => { el.style.transform = `scale(${s})`; }); };
    fit(); window.addEventListener("resize", fit);
    // Ep repaint: tranh slide bi DEN (layer scale khong duoc ve cho toi khi repaint).
    const kick = () => { root.querySelectorAll__QS__(".slide-stage").forEach((el) => { el.style.transform = "none"; void el.offsetHeight; }); fit(); };
    requestAnimationFrame(kick); setTimeout(kick, 300);
    const navs = Array.from(root.querySelectorAll(".navitem"));
    const navH = navs.map((n, i) => { const h = (e) => { e.preventDefault();
      if (swiperRef.current) swiperRef.current.slideTo(Math.min(i, N - 1)); };
      n.addEventListener("click", h); return { n, h }; });
    const onClick = (e) => { const a = (e.target__ASH__).closest(".hot"); if (!a || !root.contains(a)) return; e.preventDefault();
      const act = a.getAttribute("data-action") || "other"; const url = LINKS[act];
      if (url) { window.open(url, "_blank"); return; }
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


def _gen_fluid_mobile(board, lang, client):
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
    L = [head + 'import { useEffect, useRef } from "react";\nimport { LINKS } from "../../landing.config";\n',
         "// Layout mobile co gian (fluid): sinh boi che do --fluid. Desktop dung ban rieng.",
         "export default function MobileFluid() {",
         f"  const onClaim = (id{_ann(lang, 'number')}) => {{ console.log('claim', id); }};",
         f"  const rootRef = useRef{refann}(null);",
         "  useEffect(() => {",
         "    const root = rootRef.current; if (!root) return;",
         "    const onClick = (e) => { const a = (e.target" + (" as HTMLElement" if lang == "ts" else "")
         + ').closest(".hot"); if (!a || !root.contains(a)) return;',
         '      const act = a.getAttribute("data-action"); if (!act) return;',
         "      const url = LINKS[act]; if (url) { e.preventDefault(); window.open(url, '_blank'); } };",
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


def _gen_landing(board, lang, client, stage_rel="../Stage", swiper=False, feats=None):
    head = '"use client";\n\n' if client else ""
    comp = board["landing_name"]
    has_fixed = bool(board.get("fixed"))
    W, H = board["W"], board["H"]
    secs = board["sections"]
    feats = feats or {}
    swiper_lib = bool(feats.get("swiper_lib")) and bool(secs)
    swiper = (swiper and bool(secs)) or swiper_lib
    use_navmenu = bool(feats.get("nav_menu")) and has_fixed
    nav_tag = "NavMenu" if use_navmenu else ("FixedNav" if has_fixed else None)
    ys = [s.get("y0", 0) for s in secs]
    bands = [(ys[i], max(1, (ys[i + 1] if i + 1 < len(secs) else H) - ys[i])) for i in range(len(secs))]

    imports = ['import { useState, useEffect, useRef } from "react";',
               'import { LINKS, LABELS } from "../../landing.config";']
    if swiper_lib:  # dung thu vien Swiper.js that (giong prod)
        imports.insert(1, 'import { Swiper, SwiperSlide } from "swiper/react";')
        imports.insert(2, 'import { Mousewheel, EffectFade } from "swiper/modules";')
        imports.insert(3, 'import "swiper/css";')
        imports.insert(4, 'import "swiper/css/effect-fade";')
    elif not swiper:  # swiper (fade tu viet) tu ve nen trong section, khong dung Stage/Background
        imports.insert(1, f'import Stage from "{stage_rel}";')
        imports.insert(2, 'import Background from "./Background";')
    if nav_tag:
        imports.append(f'import {nav_tag} from "./{nav_tag}";')
    popups = bool(feats.get("popups"))
    if popups:
        imports.append('import Popups from "./Popups";')
    for sec in secs:
        imports.append(f'import {sec["comp"]} from "./{sec["comp"]}";')

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
        L.append("  const openAction = (act) => setModal({ title: LABELS[act] || \"Thông báo\", "
                 "desc: 'Chức năng \"' + (LABELS[act] || act) + '\": điền URL vào LINKS.' + act + ' hoặc gọi API tại đây.' });")
    modal_block = ("      <Popups type={popup} onClose={() => setPopup(null)} />" if popups else _LANDING_MODAL)

    def _bg_imgs(y0, hb, indent):
        """JSX cho cac layer nen thuoc section [y0, y0+hb) (toa do doi ve goc section)."""
        out = []
        for bg in board.get("backgrounds", []):
            cy = bg["y"] + bg["h"] / 2
            if not (y0 <= cy < y0 + hb):
                continue
            blend = f', mixBlendMode: {json.dumps(bg["blend"])}' if bg.get("blend") else ""
            out.append(f'{indent}<img key={json.dumps(bg["id"])} src={json.dumps(bg["src"])} '
                       f'alt={json.dumps(bg.get("alt", ""))} loading="lazy" decoding="async" '
                       f'style={{{{ position: "absolute", left: {bg["x"]}, top: {bg["y"] - y0}, '
                       f'width: {bg["w"]}, height: {bg["h"]}, opacity: {bg.get("o", 1)}{blend} }}}} />')
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
        L.append('    <div ref={rootRef}>')
        if nav_tag:
            L.append(f"      <{nav_tag} />")
        L.append('      <Swiper direction="vertical" slidesPerView={1} effect="fade" fadeEffect={{ crossFade: true }}')
        L.append('        mousewheel={{ sensitivity: 0.3, thresholdDelta: 20, thresholdTime: 300, releaseOnEdges: true }}')
        L.append('        modules={[Mousewheel, EffectFade]} className="w-full" style={{ height: "100dvh" }}')
        L.append('        onSwiper={(sw) => { swiperRef.current = sw; }} onSlideChange={(sw) => setActiveIndex(sw.activeIndex)}>')
        for i, sec in enumerate(secs):
            y0, hb = bands[i]
            L.append(f"        <SwiperSlide key={{{i}}}>")
            L.append('          <div className="w-full flex items-center justify-center overflow-hidden" style={{ height: "100dvh" }}>')
            L.append(f'            <div className="slide-stage" style={{{{ position: "relative", flexShrink: 0, width: {W}, height: {hb}, transformOrigin: "center center" }}}}>')
            L += _bg_imgs(y0, hb, "              ")
            L.append(f"              <{sec['comp']} {{...props}} />")
            L.append("            </div>")
            L.append("          </div>")
            L.append("        </SwiperSlide>")
        L.append("      </Swiper>")
        L.append(modal_block)
        L += ["    </div>", "  );", "}", ""]
    elif swiper:
        max_sec_h = max(b[1] for b in bands)
        L.append(_LANDING_SWIPER_EFFECT.replace("useRef(null)", f"useRef{refann}(null)").replace("__W__", str(W)))
        L.append("  return (")
        L.append("    <>")
        if nav_tag:
            L.append(f"      <{nav_tag} />")
        L.append('      <div ref={ref} className="deck" style={{ position: "fixed", inset: 0, overflow: "hidden", '
                 'background: "#000", display: "flex", alignItems: "center", justifyContent: "center" }}>')
        L.append(f'        <div ref={{stageRef}} style={{{{ position: "relative", flexShrink: 0, width: {W}, height: {max_sec_h}, '
                 'transformOrigin: "center center" }}>')
        for i, sec in enumerate(secs):
            y0, hb = bands[i]
            L.append(f'          <div className="landing-sec" data-sec="{i}" style={{{{ position: "absolute", '
                     f'left: 0, top: 0, width: {W}, height: {hb} }}}}>')
            L += _bg_imgs(y0, hb, "            ")
            L.append(f"            <{sec['comp']} {{...props}} />")
            L.append("          </div>")
        L.append("        </div>")
        L.append("      </div>")
        L.append(modal_block)
        L += ["    </>", "  );", "}", ""]
    else:
        L.append(f"  const rootRef = useRef{refann}(null);")
        L.append(_LANDING_EFFECT)
        L.append("  return (")
        L.append('    <div ref={rootRef}>')
        if nav_tag:
            L.append(f"      <{nav_tag} />")
        L.append(f"      <Stage width={{{W}}} height={{{H}}}>")
        L.append("        <Background />")
        for i, sec in enumerate(secs):
            y0, hb = bands[i]
            rev = "" if i == 0 else " reveal"
            L.append(f'        <div className="landing-sec{rev}" data-sec="{i}" style={{{{ position: "absolute", '
                     f'left: 0, top: {y0}, width: {W}, height: {hb} }}}}>')
            L.append(f"          <{sec['comp']} {{...props}} />")
            L.append("        </div>")
        L.append("      </Stage>")
        L.append(modal_block)
        L += ["    </div>", "  );", "}", ""]
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
        "isolatedModules": True, "noEmit": True, "jsx": "react-jsx", "strict": False,
        "noUnusedLocals": False, "noUnusedParameters": False},
    "include": ["src"]}, indent=2)
TSCONFIG_NEXT = json.dumps({
    "compilerOptions": {"target": "ES2017", "lib": ["dom", "dom.iterable", "esnext"], "allowJs": True,
        "skipLibCheck": True, "strict": False, "noEmit": True, "esModuleInterop": True, "module": "esnext",
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


def _write_landing_dir(base_dir, board, lang, client, stage_rel, swiper=False, feats=None):
    """Ghi 1 bo component landing (desktop hoac mobile) vao base_dir."""
    base_dir.mkdir(parents=True, exist_ok=True)
    ext = _ext(lang)
    (base_dir / f"Layer.{ext}").write_text(_gen_layer(lang, client), encoding="utf-8")
    (base_dir / f"Background.{ext}").write_text(_gen_background(board, lang, client), encoding="utf-8")
    feats = feats or {}
    if board.get("fixed"):
        if feats.get("nav_menu"):
            (base_dir / f"NavMenu.{ext}").write_text(_gen_navmenu(board, lang, client), encoding="utf-8")
        else:
            (base_dir / f"FixedNav.{ext}").write_text(_gen_fixednav(board, lang, client), encoding="utf-8")
    if feats.get("popups"):
        (base_dir / f"Popups.{ext}").write_text(_gen_popups(lang, client), encoding="utf-8")
    for sec in board["sections"]:
        (base_dir / f"{sec['comp']}.{ext}").write_text(_gen_section(sec, lang, client), encoding="utf-8")
        for rp in sec["repeats"]:
            (base_dir / f"{rp['comp']}.{ext}").write_text(_gen_repeat(rp, lang, client), encoding="utf-8")
    (base_dir / f"{board['landing_name']}.{ext}").write_text(
        _gen_landing(board, lang, client, stage_rel, swiper=swiper, feats=feats), encoding="utf-8")
    if feats.get("fluid"):
        (base_dir / f"MobileFluid.{ext}").write_text(
            _gen_fluid_mobile(board, lang, client), encoding="utf-8")


def _api_hook(lang):
    ret = _ann(lang, "unknown")
    return ('import { useEffect, useState } from "react";\n\n'
            "// Hook lay data landing tu API cua BE. Dien endpoint that.\n"
            "export function useLandingData() {\n"
            f"  const [data, setData] = useState{('<unknown>' if lang=='ts' else '')}(null);\n"
            "  useEffect(() => {\n"
            "    // fetch('/api/landing').then((r) => r.json()).then(setData);\n"
            "  }, []);\n  return data;\n}\n")


# ---------- REACT (Vite) ----------

def _export_react(out_dir, layout, board, mobile, lang, swiper=False, feats=None):
    feats = feats or {}
    proj = Path(out_dir) / "react-app"
    ext = _ext(lang)
    src = proj / "src"
    # DON sach src cu truoc khi sinh - tranh lan file .jsx (JS) va .tsx (TS) trong
    # cung thu muc: import khong duoi (vd "./Landing") se nap NHAM ban cu (Vite uu
    # tien .jsx truoc .tsx) -> ra dung code cu. (node_modules/dist/package.json o
    # ngoai src nen khong bi xoa.)
    if src.exists():
        shutil.rmtree(src, ignore_errors=True)
    (src / "components").mkdir(parents=True, exist_ok=True)
    (src / "components" / f"Stage.{ext}").write_text(_gen_stage(lang, client=False), encoding="utf-8")
    _write_landing_dir(src / "components" / "landing", board, lang, False, "../Stage", swiper=swiper, feats=feats)
    if mobile:
        _write_landing_dir(src / "components" / "landing-mobile", mobile["board"], lang, False, "../Stage", swiper=swiper, feats=feats)
    if lang == "ts":
        (src / "types").mkdir(exist_ok=True)
        (src / "types" / "landing.ts").write_text(_gen_types(), encoding="utf-8")
        (src / "vite-env.d.ts").write_text('/// <reference types="vite/client" />\n', encoding="utf-8")
    (src / f"useLandingData.{_dext(lang)}").write_text(_api_hook(lang), encoding="utf-8")
    (src / f"landing.config.{_dext(lang)}").write_text(
        _gen_config(lang, feats.get("env_config"), client=False), encoding="utf-8")
    if feats.get("env_config"):
        (proj / ".env").write_text(_gen_env(client=False), encoding="utf-8")

    imp = [f'import Landing from "./components/landing/{board["landing_name"]}";']
    fluid = feats.get("fluid") and not mobile
    if mobile:
        imp.append(f'import MLanding from "./components/landing-mobile/{mobile["board"]["landing_name"]}";')
    elif fluid:
        imp.append('import MobileFluid from "./components/landing/MobileFluid";')
    if mobile:
        body = ('<div className="hidden md:block"><Landing /></div>\n'
                '      <div className="block md:hidden"><MLanding /></div>')
    elif fluid:
        body = ('<div className="hidden md:block"><Landing /></div>\n'
                '      <div className="block md:hidden"><MobileFluid /></div>')
    else:
        body = "<Landing />"
    (src / f"App.{ext}").write_text(
        'import "./index.css";\n' + "\n".join(imp) + "\n\n"
        "export default function App() {\n  return (\n    <>\n      " + body + "\n    </>\n  );\n}\n", encoding="utf-8")
    (src / "index.css").write_text(CSS_TW, encoding="utf-8")
    nn = "!" if lang == "ts" else ""
    (src / f"main.{ext}").write_text(
        'import { createRoot } from "react-dom/client";\nimport App from "./App";\n\n'
        f'createRoot(document.getElementById("root"){nn}).render(<App />);\n', encoding="utf-8")
    (proj / "index.html").write_text(
        '<!doctype html>\n<html lang="vi">\n<head>\n<meta charset="UTF-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0"/>\n'
        f'<title>{layout.get("source","Landing")}</title>\n</head>\n<body>\n'
        f'<div id="root"></div>\n<script type="module" src="/src/main.{ext}"></script>\n</body>\n</html>\n',
        encoding="utf-8")
    (proj / "vite.config.js").write_text(
        'import { defineConfig } from "vite";\nimport react from "@vitejs/plugin-react";\n\n'
        'export default defineConfig({ plugins: [react()] });\n', encoding="utf-8")
    (proj / "tailwind.config.js").write_text(TAILWIND_REACT, encoding="utf-8")
    (proj / "postcss.config.js").write_text(POSTCSS_ESM, encoding="utf-8")
    dev = {"@vitejs/plugin-react": "^4.3.1", "vite": "^5.4.0",
           "tailwindcss": "^3.4.10", "postcss": "^8.4.41", "autoprefixer": "^10.4.20"}
    if lang == "ts":
        dev.update({"typescript": "^5.5.4", "@types/react": "^18.3.3", "@types/react-dom": "^18.3.0"})
        (proj / "tsconfig.json").write_text(TSCONFIG_VITE, encoding="utf-8")
    deps = {"react": "^18.3.1", "react-dom": "^18.3.1"}
    if feats.get("swiper_lib"):
        deps["swiper"] = "^11.2.6"
    (proj / "package.json").write_text(json.dumps({
        "name": _slug(layout.get("source", "psd-landing")), "private": True, "version": "0.1.0", "type": "module",
        "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
        "dependencies": deps, "devDependencies": dev}, indent=2), encoding="utf-8")
    _copy_assets(out_dir, proj, "assets")
    if mobile:
        _copy_assets(mobile["dir"], proj, "assets-m")
    _write_readme(proj, board, mobile, "npm run dev", lang)
    return proj


# ---------- NEXT ----------

def _export_next(out_dir, layout, board, mobile, lang, swiper=False, feats=None):
    feats = feats or {}
    proj = Path(out_dir) / "next-app"
    ext = _ext(lang)
    # DON app/ + components/ cu (tranh lan .jsx/.tsx -> import khong duoi nap nham ban cu)
    for d in ("app", "components", "types", "lib"):
        p = proj / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    (proj / "app").mkdir(parents=True, exist_ok=True)
    (proj / "components").mkdir(parents=True, exist_ok=True)
    (proj / "components" / f"Stage.{ext}").write_text(_gen_stage(lang, client=True), encoding="utf-8")
    _write_landing_dir(proj / "components" / "landing", board, lang, True, "../Stage", swiper=swiper, feats=feats)
    if mobile:
        _write_landing_dir(proj / "components" / "landing-mobile", mobile["board"], lang, True, "../Stage", swiper=swiper, feats=feats)
    if lang == "ts":
        (proj / "types").mkdir(exist_ok=True)
        (proj / "types" / "landing.ts").write_text(_gen_types(), encoding="utf-8")
        (proj / "next-env.d.ts").write_text(
            '/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n', encoding="utf-8")
    (proj / "lib").mkdir(exist_ok=True)
    (proj / "lib" / f"useLandingData.{_dext(lang)}").write_text('"use client";\n' + _api_hook(lang), encoding="utf-8")
    (proj / f"landing.config.{_dext(lang)}").write_text(
        _gen_config(lang, feats.get("env_config"), client=True), encoding="utf-8")
    if feats.get("env_config"):
        (proj / ".env").write_text(_gen_env(client=True), encoding="utf-8")

    (proj / "app" / "globals.css").write_text(CSS_TW, encoding="utf-8")
    (proj / "app" / f"layout.{ext}").write_text(
        'import "./globals.css";\n\n'
        f'export const metadata = {{ title: "{layout.get("source","Landing")}" }};\n\n'
        f'export default function RootLayout({{ children }}{_ann(lang, "{ children: React.ReactNode }")}) {{\n'
        '  return (<html lang="vi"><body>{children}</body></html>);\n}\n', encoding="utf-8")
    imp = [f'import Landing from "../components/landing/{board["landing_name"]}";']
    fluid = feats.get("fluid") and not mobile
    if mobile:
        imp.append(f'import MLanding from "../components/landing-mobile/{mobile["board"]["landing_name"]}";')
    elif fluid:
        imp.append('import MobileFluid from "../components/landing/MobileFluid";')
    if mobile:
        body = ('<div className="hidden md:block"><Landing /></div>\n'
                '      <div className="block md:hidden"><MLanding /></div>')
    elif fluid:
        body = ('<div className="hidden md:block"><Landing /></div>\n'
                '      <div className="block md:hidden"><MobileFluid /></div>')
    else:
        body = "<Landing />"
    (proj / "app" / f"page.{ext}").write_text(
        "\n".join(imp) + "\n\nexport default function Page() {\n  return (\n    <>\n      " + body + "\n    </>\n  );\n}\n",
        encoding="utf-8")

    (proj / "next.config.js").write_text("/** @type {import('next').NextConfig} */\nmodule.exports = {};\n", encoding="utf-8")
    (proj / "tailwind.config.js").write_text(TAILWIND_NEXT, encoding="utf-8")
    (proj / "postcss.config.js").write_text(POSTCSS_CJS, encoding="utf-8")
    dev = {"tailwindcss": "^3.4.10", "postcss": "^8.4.41", "autoprefixer": "^10.4.20"}
    if lang == "ts":
        dev.update({"typescript": "^5.5.4", "@types/react": "^18.3.3", "@types/react-dom": "^18.3.0", "@types/node": "^20"})
        (proj / "tsconfig.json").write_text(TSCONFIG_NEXT, encoding="utf-8")
    ndeps = {"next": "^14.2.5", "react": "^18.3.1", "react-dom": "^18.3.1"}
    if feats.get("swiper_lib"):
        ndeps["swiper"] = "^11.2.6"
    (proj / "package.json").write_text(json.dumps({
        "name": _slug(layout.get("source", "psd-landing")), "private": True, "version": "0.1.0",
        "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
        "dependencies": ndeps,
        "devDependencies": dev}, indent=2), encoding="utf-8")
    _copy_assets(out_dir, proj, "assets")
    if mobile:
        _copy_assets(mobile["dir"], proj, "assets-m")
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
                                   detect_repeats=detect_repeats)
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
           swiper=False, feats=None):
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

    proj = _export_next(out_dir, layout, board, mobile, lang, swiper=swiper, feats=feats) if framework == "next" \
        else _export_react(out_dir, layout, board, mobile, lang, swiper=swiper, feats=feats)

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
