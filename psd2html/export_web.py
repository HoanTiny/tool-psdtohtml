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

from .render_slices import _is_interactive, _content_bottom_from_image, _norm
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
                        "slots": slots, "instances": instances, "count": len(instances)})
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
        bands = [(s["y0"], s["y1"]) for s in split_sections(layout)]
    except Exception:
        bands = [(0, H)]
    if not bands:
        bands = [(0, H)]

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


def _artboards_from_layout(layout, asset_dir="assets", comp_prefix=""):
    cw, ch = layout["canvas"]["width"], layout["canvas"]["height"]
    by_id, children = _index(layout)
    ab = {"x": 0, "y": 0, "width": cw, "height": ch}
    repeats, consumed = _detect_repeats(layout, ab, by_id, children, asset_dir)
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
        "  href?: string | null; menu?: boolean; toggle?: boolean;\n}\n\n"
        "export interface SlotItem { src: string; x: number; y: number; w: number; h: number; alt?: string; }\n\n"
        "export interface RepeatItem {\n"
        "  id: number; x: number; y: number; claimed?: boolean;\n"
        "  items?: SlotItem[]; [key: string]: unknown;\n}\n\n"
        "export interface SectionProps {\n"
        "  onClaim?: (id: number) => void; menuOpen?: boolean; onToggleMenu?: () => void;\n}\n"
    )


def _gen_stage(lang, client):
    head = '"use client";\n\n' if client else ""
    if lang == "ts":
        return head + (
            'import { useRef, useEffect, useState } from "react";\n'
            'import type { ReactNode } from "react";\n\n'
            "export default function Stage({ width, height, children }: "
            "{ width: number; height: number; children: ReactNode }) {\n"
            "  const ref = useRef<HTMLDivElement>(null);\n"
            "  const [scale, setScale] = useState(1);\n"
            "  useEffect(() => {\n"
            "    const el = ref.current;\n    if (!el) return;\n"
            "    const fit = () => setScale(Math.min(1, el.clientWidth / width));\n"
            "    fit();\n    window.addEventListener('resize', fit);\n"
            "    return () => window.removeEventListener('resize', fit);\n  }, [width]);\n"
            "  return (\n"
            '    <div ref={ref} className="w-full overflow-hidden" style={{ height: height * scale }}>\n'
            '      <div className="relative" style={{ width, height, transformOrigin: "top left", transform: `scale(${scale})` }}>\n'
            "        {children}\n      </div>\n    </div>\n  );\n}\n")
    return head + (
        'import { useRef, useEffect, useState } from "react";\n\n'
        "export default function Stage({ width, height, children }) {\n"
        "  const ref = useRef(null);\n  const [scale, setScale] = useState(1);\n"
        "  useEffect(() => {\n    const el = ref.current;\n    if (!el) return;\n"
        "    const fit = () => setScale(Math.min(1, el.clientWidth / width));\n"
        "    fit();\n    window.addEventListener('resize', fit);\n"
        "    return () => window.removeEventListener('resize', fit);\n  }, [width]);\n"
        "  return (\n"
        '    <div ref={ref} className="w-full overflow-hidden" style={{ height: height * scale }}>\n'
        '      <div className="relative" style={{ width, height, transformOrigin: "top left", transform: `scale(${scale})` }}>\n'
        "        {children}\n      </div>\n    </div>\n  );\n}\n")


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
        '        <img src={l.src} alt={l.alt} className="block w-full h-full" />\n'
        "      </button>\n    );\n  }\n"
        "  if (l.menu && !menuOpen) return null;\n"
        "  return l.href ? (\n"
        '    <a href={l.href} title={l.alt} className="absolute block cursor-pointer transition hover:brightness-110" style={style}>\n'
        '      <img src={l.src} alt={l.alt} className="block w-full h-full" />\n'
        "    </a>\n  ) : (\n"
        '    <img src={l.src} alt={l.alt} className="absolute block" style={style} />\n  );\n}\n')


def _flat_json(items):
    keep = []
    for it in items:
        o = {"id": it["id"], "src": it["src"], "x": it["x"], "y": it["y"],
             "w": it["w"], "h": it["h"], "o": it["o"], "alt": it["alt"]}
        if it.get("blend"):
            o["blend"] = it["blend"]
        if it.get("href"):
            o["href"] = it["href"]
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
        '        <img key={l.id} src={l.src} alt={l.alt} className="absolute block"\n'
        "          style={{ left: l.x, top: l.y, width: l.w, height: l.h, opacity: l.o }} />\n"
        "      ))}\n    </>\n  );\n}\n")


def _gen_repeat(rp, lang, client):
    head = '"use client";\n\n' if client else ""
    imp = 'import type { RepeatItem } from "../../types/landing";\n\n' if lang == "ts" else ""
    sig = ("{ item, onClaim }: { item: RepeatItem; onClaim?: (id: number) => void }"
           if lang == "ts" else "{ item, onClaim }")
    L = [head + imp, f"export default function {rp['comp']}({sig}) {{",
         "  return (",
         f'    <div className="absolute" style={{{{ left: item.x, top: item.y, width: {rp["W"]}, height: {rp["H"]} }}}}>']
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
    imports = ['import Layer from "./Layer";']
    for rp in sec["repeats"]:
        imports.append(f'import {rp["comp"]} from "./{rp["comp"]}";')
    if lang == "ts":
        imports.append('import type { SectionProps, LayerItem, RepeatItem } from "../../types/landing";')
    blocks = [head + "\n".join(imports) + "\n"]
    blocks.append(f"const flat{_ann(lang, 'LayerItem[]')} = {_flat_json(sec['flat'])};\n")
    for rp in sec["repeats"]:
        var = rp["comp"][0].lower() + rp["comp"][1:] + "Data"
        data = []
        for inst in rp["instances"]:
            e = {"id": inst["id"], "x": inst["x"], "y": inst["y"]}
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
        body.append(f"      {{{var}.map((it) => (")
        body.append(f'        <{rp["comp"]} key={{it.id}} item={{it}} onClaim={{onClaim}} />')
        body.append("      ))}")
    body += ["    </>", "  );", "}", ""]
    return "\n".join(blocks) + "\n".join(body)


def _gen_landing(board, lang, client, stage_rel="../Stage"):
    head = '"use client";\n\n' if client else ""
    comp = board["landing_name"]
    imports = ['import { useState } from "react";', f'import Stage from "{stage_rel}";',
               'import Background from "./Background";']
    for sec in board["sections"]:
        imports.append(f'import {sec["comp"]} from "./{sec["comp"]}";')
    L = [head + "\n".join(imports) + "\n"]
    L.append(f"export default function {comp}() {{")
    L.append(f"  const [menuOpen, setMenuOpen] = useState(false);")
    L.append("  // TODO: goi API nhan qua o day (vd fetch POST /api/claim)")
    L.append(f"  const onClaim = (id{_ann(lang, 'number')}) => {{ console.log('claim', id); }};")
    L.append("  const onToggleMenu = () => setMenuOpen((o) => !o);")
    L.append("  const props = { onClaim, menuOpen, onToggleMenu };")
    L.append("  return (")
    L.append(f"    <Stage width={{{board['W']}}} height={{{board['H']}}}>")
    L.append("      <Background />")
    for sec in board["sections"]:
        L.append(f"      <{sec['comp']} {{...props}} />")
    L += ["    </Stage>", "  );", "}", ""]
    return "\n".join(L)


# ================= cau hinh du an =================

TAILWIND_REACT = ('/** @type {import(\'tailwindcss\').Config} */\nexport default {\n'
                  '  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],\n  theme: { extend: {} },\n  plugins: [],\n};\n')
TAILWIND_NEXT = ('/** @type {import(\'tailwindcss\').Config} */\nmodule.exports = {\n'
                 '  content: ["./app/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,jsx,ts,tsx}"],\n  theme: { extend: {} },\n  plugins: [],\n};\n')
POSTCSS_ESM = "export default {\n  plugins: { tailwindcss: {}, autoprefixer: {} },\n};\n"
POSTCSS_CJS = "module.exports = {\n  plugins: { tailwindcss: {}, autoprefixer: {} },\n};\n"
CSS_TW = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n\nbody { background: #000; }\n"

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


def _write_landing_dir(base_dir, board, lang, client, stage_rel):
    """Ghi 1 bo component landing (desktop hoac mobile) vao base_dir."""
    base_dir.mkdir(parents=True, exist_ok=True)
    ext = _ext(lang)
    (base_dir / f"Layer.{ext}").write_text(_gen_layer(lang, client), encoding="utf-8")
    (base_dir / f"Background.{ext}").write_text(_gen_background(board, lang, client), encoding="utf-8")
    for sec in board["sections"]:
        (base_dir / f"{sec['comp']}.{ext}").write_text(_gen_section(sec, lang, client), encoding="utf-8")
        for rp in sec["repeats"]:
            (base_dir / f"{rp['comp']}.{ext}").write_text(_gen_repeat(rp, lang, client), encoding="utf-8")
    (base_dir / f"{board['landing_name']}.{ext}").write_text(
        _gen_landing(board, lang, client, stage_rel), encoding="utf-8")


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

def _export_react(out_dir, layout, board, mobile, lang):
    proj = Path(out_dir) / "react-app"
    ext = _ext(lang)
    src = proj / "src"
    (src / "components").mkdir(parents=True, exist_ok=True)
    (src / "components" / f"Stage.{ext}").write_text(_gen_stage(lang, client=False), encoding="utf-8")
    _write_landing_dir(src / "components" / "landing", board, lang, False, "../Stage")
    if mobile:
        _write_landing_dir(src / "components" / "landing-mobile", mobile["board"], lang, False, "../Stage")
    if lang == "ts":
        (src / "types").mkdir(exist_ok=True)
        (src / "types" / "landing.ts").write_text(_gen_types(), encoding="utf-8")
        (src / "vite-env.d.ts").write_text('/// <reference types="vite/client" />\n', encoding="utf-8")
    (src / f"useLandingData.{_dext(lang)}").write_text(_api_hook(lang), encoding="utf-8")

    imp = [f'import Landing from "./components/landing/{board["landing_name"]}";']
    if mobile:
        imp.append(f'import MLanding from "./components/landing-mobile/{mobile["board"]["landing_name"]}";')
    body = ('<div className="hidden md:block"><Landing /></div>\n'
            '      <div className="block md:hidden"><MLanding /></div>') if mobile else "<Landing />"
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
    (proj / "package.json").write_text(json.dumps({
        "name": _slug(layout.get("source", "psd-landing")), "private": True, "version": "0.1.0", "type": "module",
        "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
        "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"}, "devDependencies": dev}, indent=2), encoding="utf-8")
    _copy_assets(out_dir, proj, "assets")
    if mobile:
        _copy_assets(mobile["dir"], proj, "assets-m")
    _write_readme(proj, board, mobile, "npm run dev", lang)
    return proj


# ---------- NEXT ----------

def _export_next(out_dir, layout, board, mobile, lang):
    proj = Path(out_dir) / "next-app"
    ext = _ext(lang)
    (proj / "app").mkdir(parents=True, exist_ok=True)
    (proj / "components").mkdir(parents=True, exist_ok=True)
    (proj / "components" / f"Stage.{ext}").write_text(_gen_stage(lang, client=True), encoding="utf-8")
    _write_landing_dir(proj / "components" / "landing", board, lang, True, "../Stage")
    if mobile:
        _write_landing_dir(proj / "components" / "landing-mobile", mobile["board"], lang, True, "../Stage")
    if lang == "ts":
        (proj / "types").mkdir(exist_ok=True)
        (proj / "types" / "landing.ts").write_text(_gen_types(), encoding="utf-8")
        (proj / "next-env.d.ts").write_text(
            '/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n', encoding="utf-8")
    (proj / "lib").mkdir(exist_ok=True)
    (proj / "lib" / f"useLandingData.{_dext(lang)}").write_text('"use client";\n' + _api_hook(lang), encoding="utf-8")

    (proj / "app" / "globals.css").write_text(CSS_TW, encoding="utf-8")
    (proj / "app" / f"layout.{ext}").write_text(
        'import "./globals.css";\n\n'
        f'export const metadata = {{ title: "{layout.get("source","Landing")}" }};\n\n'
        f'export default function RootLayout({{ children }}{_ann(lang, "{ children: React.ReactNode }")}) {{\n'
        '  return (<html lang="vi"><body>{children}</body></html>);\n}\n', encoding="utf-8")
    imp = [f'import Landing from "../components/landing/{board["landing_name"]}";']
    if mobile:
        imp.append(f'import MLanding from "../components/landing-mobile/{mobile["board"]["landing_name"]}";')
    body = ('<div className="hidden md:block"><Landing /></div>\n'
            '      <div className="block md:hidden"><MLanding /></div>') if mobile else "<Landing />"
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
    (proj / "package.json").write_text(json.dumps({
        "name": _slug(layout.get("source", "psd-landing")), "private": True, "version": "0.1.0",
        "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
        "dependencies": {"next": "^14.2.5", "react": "^18.3.1", "react-dom": "^18.3.1"},
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

def _load_variant(vdir, asset_dir, comp_prefix):
    vdir = Path(vdir)
    layout = json.loads((vdir / "layout.json").read_text(encoding="utf-8"))
    board = _artboards_from_layout(layout, asset_dir, comp_prefix)
    if not layout.get("artboards"):
        board["H"] = _content_bottom_from_image(
            vdir / layout.get("screenshot", "screenshot.png"), layout["canvas"]["height"])
    _split_sections(board, layout)
    return layout, board


def export(out_dir, framework="react", lang="js", mobile_dir=None):
    out_dir = Path(out_dir)
    if lang not in ("ts", "js"):
        lang = "js"
    layout, board = _load_variant(out_dir, "assets", "")
    mobile = None
    if mobile_dir:
        m_layout, m_board = _load_variant(mobile_dir, "assets-m", "M")
        mobile = {"dir": Path(mobile_dir), "layout": m_layout, "board": m_board}

    proj = _export_next(out_dir, layout, board, mobile, lang) if framework == "next" \
        else _export_react(out_dir, layout, board, mobile, lang)

    nsec = len(board["sections"])
    nrep = sum(len(s["repeats"]) for s in board["sections"])
    print(f"[{framework}/{lang}{' +mobile' if mobile else ''}] {nsec} section, {nrep} cum lap -> {proj}")
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
