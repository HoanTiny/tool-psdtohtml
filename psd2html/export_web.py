"""
Xuat sang du an REACT (Vite) hoac NEXT (app router), dung Tailwind.

Diem manh: TU DONG PHAT HIEN GROUP LAP (vd 7 the diem danh, 3 goi nap...) va
sinh thanh 1 component render bang .map() qua mang DATA -> de tich hop API tu BE:
  - Moi cum lap co 1 mang data (id, vi tri, o vat pham, trang thai claimed...).
  - Nut "Nhan Qua" goi callback onClaim(id) -> cam API vao day.
  - O vat pham (items) render tu data BE tra ve.
  - Kem hook fetch stub (useLandingData) de dien endpoint.

Dung:
  from psd2html.export_web import export
  export("output", framework="react")   # hoac "next"
"""

import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from .render_slices import _is_interactive, _content_bottom_from_image, _norm


# ---------- tien ich ----------

def _pascal(s):
    parts = re.split(r"[^0-9a-zA-Z]+", s or "")
    name = "".join(p[:1].upper() + p[1:] for p in parts if p)
    if not name:
        name = "Item"
    if name[0].isdigit():
        name = "G" + name
    return name


def _slug(s):
    s = re.sub(r"[^0-9a-zA-Z]+", "-", (s or "").lower()).strip("-")
    return s or "page"


def _norm_name(name):
    """Chuan hoa ten group: bo hau to ' copy' / ' copy N' de gom cac ban sao."""
    n = (name or "").strip().lower()
    n = re.sub(r"\s*copy(\s*\d+)?\s*$", "", n)
    return n.strip()


def _index(layout):
    by_id = {l["id"]: l for l in layout["layers"]}
    children = defaultdict(list)
    for l in layout["layers"]:
        children[l.get("parent")].append(l["id"])
    return by_id, children


def _leaves(gid, by_id, children):
    """Tat ca layer con (co asset) cua 1 group, de quy."""
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
    """Duong dan anh trong project: /<asset_dir>/<ten-file>."""
    return f"/{asset_dir}/{Path(asset).name}"


# ---------- phat hien group lap ----------

def _detect_repeats(layout, ab_bbox, by_id, children, asset_dir="assets"):
    """
    Tim cac cum group lap (>=3 sibling cung ten chuan hoa, kich thuoc tuong tu).
    Tra ve (repeats, consumed_leaf_ids).

    Moi repeat:
      {
        comp, W, H,
        slots: [ {rx,ry,w,h, kind:'static'|'var'|'button', asset, var, alt, blend, o} ],
        instances: [ {id, x, y, vars:{var:asset}} ],
        item_area: {x,y,w,h},   # goi y vung dat vat pham
      }
    """
    ax, ay = ab_bbox["x"], ab_bbox["y"]
    groups = [l for l in layout["layers"] if l.get("kind") == "group"]

    clusters = defaultdict(list)
    for g in groups:
        b = g["bbox"]
        cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        if not (ax <= cx < ax + ab_bbox["width"] and ay <= cy < ay + ab_bbox["height"]):
            continue
        clusters[(g.get("parent"), _norm_name(g["name"]))].append(g)

    # Xu ly cum to truoc; tranh long nhau
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

    consumed_groups = set()
    consumed_leaves = set()
    repeats = []
    used_names = {}

    for _, nm, members in cand:
        if any(m["id"] in consumed_groups for m in members):
            continue
        members.sort(key=lambda m: (round(m["bbox"]["y"] / 20), m["bbox"]["x"]))

        inst_leaves = []
        for m in members:
            inst_leaves.append((m, _leaves(m["id"], by_id, children)))
        counts = {len(lv) for _, lv in inst_leaves}
        aligned = []
        same = len(counts) == 1 and next(iter(counts)) > 0
        take = inst_leaves if same else inst_leaves[:1]
        for m, lv in take:
            ox, oy = m["bbox"]["x"], m["bbox"]["y"]
            s = sorted(lv, key=lambda n: (round((n["bbox"]["y"] - oy) / 8), n["bbox"]["x"] - ox))
            aligned.append((m, ox, oy, s))
        if not aligned or len(aligned[0][3]) == 0:
            continue

        # ten component doc nhat
        comp = _pascal(nm) or "Item"
        used_names[comp] = used_names.get(comp, 0) + 1
        if used_names[comp] > 1:
            comp = f"{comp}{used_names[comp]}"

        tpl_m, tox, toy, tpl_leaves = aligned[0]
        nslots = len(tpl_leaves)
        slots = []
        var_idx = 0
        for si in range(nslots):
            tnode = tpl_leaves[si]
            # So theo TEN layer: khung the (cung ten) -> static dung chung;
            # chi cai khac ten (vd 'Ngay 1' vs 'Ngay 2') moi la bien.
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
                slot["kind"] = "var"
                slot["var"] = f"s{var_idx}"
                var_idx += 1
            else:
                slot["kind"] = "static"
            slots.append(slot)

        instances = []
        for idx, (m, ox, oy, s) in enumerate(aligned, start=1):
            vars_ = {}
            for si, slot in enumerate(slots):
                if slot["kind"] == "var":
                    vars_[slot["var"]] = _src(s[si]["asset"], asset_dir)
            instances.append({
                "id": idx,
                "x": m["bbox"]["x"] - ax, "y": m["bbox"]["y"] - ay,
                "vars": vars_,
            })

        # vung goi y dat vat pham = bao cua cac slot static lon nhat (khong phai button)
        area = None
        big = [sl for sl in slots if sl["kind"] != "button"]
        if big:
            x0 = min(sl["rx"] for sl in big); y0 = min(sl["ry"] for sl in big)
            x1 = max(sl["rx"] + sl["w"] for sl in big); y1 = max(sl["ry"] + sl["h"] for sl in big)
            area = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}

        repeats.append({
            "comp": comp,
            "W": tpl_m["bbox"]["width"], "H": tpl_m["bbox"]["height"],
            "slots": slots, "instances": instances, "item_area": area,
            "count": len(instances),
        })

        for m in members:
            consumed_groups.add(m["id"])
            for gid in _descendant_groups(m["id"], by_id, children):
                consumed_groups.add(gid)
            for lf in _leaves(m["id"], by_id, children):
                consumed_leaves.add(lf["id"])

    return repeats, consumed_leaves


def _detect_menu(layout, ab_bbox, by_id, children):
    """
    Phat hien menu bat/tat: 1 nut hamburger + 1 panel menu (overlay).
    Tra ve (menu_leaf_ids, toggle_id). Chi tra ve khi CO CA nut lan panel
    (neu chi co menu luon hien - vd nav desktop - thi khong dung, tra rong).
    """
    ax, ay = ab_bbox["x"], ab_bbox["y"]
    aw, ah = ab_bbox["width"], ab_bbox["height"]

    def inside(b):
        cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        return ax <= cx < ax + aw and ay <= cy < ay + ah

    # nut hamburger: layer nho co 'menu'/'nut'/'ham' trong ten, gan dinh trang
    toggle = None
    for l in layout["layers"]:
        if l.get("kind") == "group" or not l.get("asset"):
            continue
        nm = _norm(l.get("name", ""))
        b = l["bbox"]
        if not inside(b):
            continue
        if (("menu" in nm) or ("nut" in nm) or ("ham" in nm)) and b["width"] < 160 and b["height"] < 160:
            if toggle is None or b["y"] < toggle["bbox"]["y"]:
                toggle = l
    if toggle is None:
        return set(), None

    # panel menu: group lon nhat co 'menu' trong ten (overlay)
    best, best_area = None, 0
    for g in layout["layers"]:
        if g.get("kind") != "group":
            continue
        if "menu" not in _norm(g.get("name", "")):
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


def _build_flat(layers, ab_bbox, exclude, asset_dir="assets", menu_ids=None, toggle_id=None):
    """Layer khong thuoc cum lap -> render phang nhu che do slices."""
    ax, ay = ab_bbox["x"], ab_bbox["y"]
    items = []
    for l in layers:
        if not l.get("asset") or l["id"] in exclude:
            continue
        b = l["bbox"]
        cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        if not (ax <= cx < ax + ab_bbox["width"] and ay <= cy < ay + ab_bbox["height"]):
            continue
        item = {
            "id": l["id"], "src": _src(l["asset"], asset_dir),
            "x": b["x"] - ax, "y": b["y"] - ay, "w": b["width"], "h": b["height"],
            "o": l.get("opacity", 1), "blend": l.get("blend"),
            "alt": _alt_of(l), "href": "#" if _is_interactive(l) else None,
        }
        if toggle_id and l["id"] == toggle_id:
            item["toggle"] = True
            item["href"] = None
        elif menu_ids and l["id"] in menu_ids:
            item["menu"] = True
        items.append(item)
    return items


def _artboards_from_layout(layout, asset_dir="assets", comp_prefix=""):
    cw, ch = layout["canvas"]["width"], layout["canvas"]["height"]
    by_id, children = _index(layout)
    abs_ = layout.get("artboards") or []
    defs = abs_ if abs_ else [{
        "name": layout.get("source", "Page"),
        "bbox": {"x": 0, "y": 0, "width": cw, "height": ch},
    }]
    result = []
    for ab in defs:
        repeats, consumed = _detect_repeats(layout, ab["bbox"], by_id, children, asset_dir)
        menu_ids, toggle_id = _detect_menu(layout, ab["bbox"], by_id, children)
        flat = _build_flat(layout["layers"], ab["bbox"], consumed, asset_dir, menu_ids, toggle_id)
        name = ab["name"]
        stem = Path(name).stem  # bo duoi .psd neu la ten file nguon
        result.append({
            "name": name, "comp": comp_prefix + _pascal(stem), "slug": _slug(stem),
            "W": ab["bbox"]["width"], "H": ab["bbox"]["height"],
            "flat": flat, "repeats": repeats,
            "has_menu": bool(toggle_id),
        })
    return result


# ---------- sinh JSX ----------

STAGE_JSX = """import { useRef, useEffect, useState } from "react";

// Khung co dinh WxH, tu thu nho vua chieu rong man hinh (responsive).
export default function Stage({ width, height, children }) {
  const ref = useRef(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => setScale(Math.min(1, el.clientWidth / width));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [width]);
  return (
    <div ref={ref} className="w-full overflow-hidden" style={{ height: height * scale }}>
      <div className="relative" style={{ width, height, transformOrigin: "top left", transform: `scale(${scale})` }}>
        {children}
      </div>
    </div>
  );
}
"""


def _repeat_component_code(rp):
    """Sinh 1 function component cho cum lap."""
    lines = []
    lines.append(f"function {rp['comp']}({{ item, onClaim }}) {{")
    lines.append("  return (")
    lines.append(f'    <div className="absolute" style={{{{ left: item.x, top: item.y, width: {rp["W"]}, height: {rp["H"]} }}}}>')
    for sl in rp["slots"]:
        style = (f'{{{{ left: {sl["rx"]}, top: {sl["ry"]}, width: {sl["w"]}, height: {sl["h"]}'
                 f', opacity: {sl["o"]}'
                 + (f', mixBlendMode: "{sl["blend"]}"' if sl.get("blend") else "") + " }}")
        if sl["kind"] == "button":
            lines.append(f'      <button onClick={{() => onClaim && onClaim(item.id)}} title="{sl["alt"]}"')
            lines.append(f'        className="absolute block cursor-pointer transition hover:brightness-110" style={style}>')
            lines.append(f'        <img src="{sl["asset"]}" alt="{sl["alt"]}" className="block w-full h-full" />')
            lines.append('      </button>')
        elif sl["kind"] == "var":
            lines.append(f'      {{item.{sl["var"]} && <img className="absolute block" style={style} src={{item.{sl["var"]}}} alt="{sl["alt"]}" />}}')
        else:
            lines.append(f'      <img className="absolute block" style={style} src="{sl["asset"]}" alt="{sl["alt"]}" />')
    # o vat pham tu API
    if rp.get("item_area"):
        a = rp["item_area"]
        lines.append(f'      {{/* Vat pham do BE tra ve: item.items = [{{src,x,y,w,h}}] (toa do trong the) */}}')
        lines.append('      {(item.items || []).map((it, i) => (')
        lines.append('        <img key={i} className="absolute block" src={it.src} alt={it.alt || ""}')
        lines.append('          style={{ left: it.x, top: it.y, width: it.w, height: it.h }} />')
        lines.append('      ))}')
    # trang thai da nhan
    lines.append('      {item.claimed && <div className="absolute inset-0 bg-black/40" />}')
    lines.append("    </div>")
    lines.append("  );")
    lines.append("}")
    return "\n".join(lines)


def _gen_component(board, client=False):
    head = '"use client";\n\n' if client else ""
    flat_json = json.dumps(board["flat"], ensure_ascii=False, indent=2)

    # data cua tung cum lap
    data_blocks = []
    repeat_render = []
    repeat_comps = []
    for rp in board["repeats"]:
        var_name = rp["comp"][0].lower() + rp["comp"][1:] + "Data"
        data = []
        for inst in rp["instances"]:
            entry = {"id": inst["id"], "x": inst["x"], "y": inst["y"]}
            entry.update(inst["vars"])
            entry["claimed"] = False
            entry["items"] = []      # BE dien vat pham vao day
            data.append(entry)
        data_blocks.append(f"// {rp['count']} phan tu lap - thay bang data tu API\n"
                           f"const {var_name} = {json.dumps(data, ensure_ascii=False, indent=2)};")
        repeat_comps.append(_repeat_component_code(rp))
        repeat_render.append(
            f"      {{{var_name}.map((it) => (\n"
            f"        <{rp['comp']} key={{it.id}} item={{it}} onClaim={{onClaim}} />\n"
            f"      ))}}")

    menu_branch = """        if (l.toggle) {
          return (
            <button key={l.id} onClick={() => setMenuOpen((o) => !o)} title={l.alt}
              className="absolute block cursor-pointer transition hover:brightness-110" style={style}>
              <img src={l.src} alt={l.alt} className="block w-full h-full" />
            </button>
          );
        }
        if (l.menu && !menuOpen) return null;
""" if board.get("has_menu") else ""
    flat_render = """      {flatLayers.map((l) => {
        const style = { left: l.x, top: l.y, width: l.w, height: l.h, opacity: l.o, mixBlendMode: l.blend || undefined };
""" + menu_branch + """        return l.href ? (
          <a key={l.id} href={l.href} title={l.alt} className="absolute block cursor-pointer transition hover:brightness-110" style={style}>
            <img src={l.src} alt={l.alt} className="block w-full h-full" />
          </a>
        ) : (
          <img key={l.id} src={l.src} alt={l.alt} className="absolute block" style={style} />
        );
      })}"""

    parts = [head]
    if board.get("has_menu"):
        parts.append('import { useState } from "react";\n')
    parts.append('import Stage from "./Stage";\n')
    parts.append(f"const W = {board['W']};\nconst H = {board['H']};\n")
    parts.append(f"const flatLayers = {flat_json};\n")
    if data_blocks:
        parts.append("\n".join(data_blocks) + "\n")
    if repeat_comps:
        parts.append("\n\n".join(repeat_comps) + "\n")

    parts.append(f"export default function {board['comp']}() {{")
    if board.get("has_menu"):
        parts.append("  const [menuOpen, setMenuOpen] = useState(false);  // menu bat/tat")
    parts.append("  // TODO: goi API nhan qua o day (vd fetch POST /api/claim)")
    parts.append("  const onClaim = (id) => { console.log('claim', id); };")
    parts.append("  return (")
    parts.append("    <Stage width={W} height={H}>")
    parts.append(flat_render)
    if repeat_render:
        parts.append("\n".join(repeat_render))
    parts.append("    </Stage>")
    parts.append("  );")
    parts.append("}")
    return "\n".join(parts) + "\n"


# ---------- cau hinh du an ----------

TAILWIND_CFG_REACT = """/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: { extend: {} },
  plugins: [],
};
"""

TAILWIND_CFG_NEXT = """/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx}", "./components/**/*.{js,jsx}"],
  theme: { extend: {} },
  plugins: [],
};
"""

POSTCSS_CFG_CJS = "module.exports = {\n  plugins: { tailwindcss: {}, autoprefixer: {} },\n};\n"
POSTCSS_CFG_ESM = "export default {\n  plugins: { tailwindcss: {}, autoprefixer: {} },\n};\n"
CSS_TW = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n\nbody { background: #000; }\n"


def _copy_assets(out_dir, project_dir, dest="assets"):
    src = Path(out_dir) / "assets"
    dst = Path(project_dir) / "public" / dest
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def _api_hook(boards):
    """Sinh 1 hook fetch stub de BE cam API."""
    return (
        '// Hook lay data cho landing tu API cua BE.\n'
        '// Dien endpoint that va tra ve data theo dung shape cac *Data trong component.\n'
        'import { useEffect, useState } from "react";\n\n'
        'export function useLandingData() {\n'
        '  const [data, setData] = useState(null);\n'
        '  useEffect(() => {\n'
        '    // TODO: thay bang API that\n'
        '    // fetch("/api/landing").then((r) => r.json()).then(setData);\n'
        '  }, []);\n'
        '  return data;\n'
        '}\n'
    )


# ---------- xuat REACT (Vite) ----------

def _responsive_body(boards, mobile):
    """JSX than trang: neu co mobile -> an/hien theo breakpoint md."""
    d = "\n        ".join(f"<{b['comp']} />" for b in boards)
    if not mobile:
        return d
    m = "\n        ".join(f"<{b['comp']} />" for b in mobile["boards"])
    return (f'<div className="hidden md:block">\n        {d}\n      </div>\n'
            f'      <div className="block md:hidden">\n        {m}\n      </div>')


def _export_react(out_dir, layout, boards, mobile=None):
    proj = Path(out_dir) / "react-app"
    (proj / "src" / "components").mkdir(parents=True, exist_ok=True)
    all_boards = list(boards) + (mobile["boards"] if mobile else [])
    for ab in all_boards:
        (proj / "src" / "components" / f"{ab['comp']}.jsx").write_text(
            _gen_component(ab, client=False), encoding="utf-8")
    (proj / "src" / "components" / "Stage.jsx").write_text(STAGE_JSX, encoding="utf-8")
    (proj / "src" / "useLandingData.js").write_text(_api_hook(all_boards), encoding="utf-8")

    imports = "\n".join(f'import {b["comp"]} from "./components/{b["comp"]}";' for b in all_boards)
    body = _responsive_body(boards, mobile)
    (proj / "src" / "App.jsx").write_text(
        f'import "./index.css";\n{imports}\n\n'
        f'export default function App() {{\n  return (\n    <>\n      {body}\n    </>\n  );\n}}\n',
        encoding="utf-8")
    (proj / "src" / "index.css").write_text(CSS_TW, encoding="utf-8")
    (proj / "src" / "main.jsx").write_text(
        'import React from "react";\nimport { createRoot } from "react-dom/client";\n'
        'import App from "./App";\n\ncreateRoot(document.getElementById("root")).render(<App />);\n',
        encoding="utf-8")
    (proj / "index.html").write_text(
        '<!doctype html>\n<html lang="vi">\n<head>\n<meta charset="UTF-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0"/>\n'
        f'<title>{layout.get("source","Landing")}</title>\n</head>\n<body>\n'
        '<div id="root"></div>\n<script type="module" src="/src/main.jsx"></script>\n</body>\n</html>\n',
        encoding="utf-8")
    (proj / "vite.config.js").write_text(
        'import { defineConfig } from "vite";\nimport react from "@vitejs/plugin-react";\n\n'
        'export default defineConfig({ plugins: [react()] });\n', encoding="utf-8")
    (proj / "tailwind.config.js").write_text(TAILWIND_CFG_REACT, encoding="utf-8")
    (proj / "postcss.config.js").write_text(POSTCSS_CFG_ESM, encoding="utf-8")
    (proj / "package.json").write_text(json.dumps({
        "name": _slug(layout.get("source", "psd-landing")),
        "private": True, "version": "0.1.0", "type": "module",
        "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
        "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
        "devDependencies": {"@vitejs/plugin-react": "^4.3.1", "vite": "^5.4.0",
                            "tailwindcss": "^3.4.10", "postcss": "^8.4.41", "autoprefixer": "^10.4.20"},
    }, indent=2), encoding="utf-8")
    _copy_assets(out_dir, proj, "assets")
    if mobile:
        _copy_assets(mobile["dir"], proj, "assets-m")
    _write_readme(proj, boards, "npm run dev", mobile)
    return proj


# ---------- xuat NEXT ----------

def _export_next(out_dir, layout, boards, mobile=None):
    proj = Path(out_dir) / "next-app"
    (proj / "app").mkdir(parents=True, exist_ok=True)
    (proj / "components").mkdir(parents=True, exist_ok=True)
    (proj / "components" / "Stage.jsx").write_text('"use client";\n\n' + STAGE_JSX, encoding="utf-8")
    boards_all = list(boards) + (mobile["boards"] if mobile else [])
    for ab in boards_all:
        (proj / "components" / f"{ab['comp']}.jsx").write_text(
            _gen_component(ab, client=True), encoding="utf-8")
    (proj / "lib").mkdir(exist_ok=True)
    (proj / "lib" / "useLandingData.js").write_text('"use client";\n' + _api_hook(boards_all), encoding="utf-8")

    (proj / "app" / "globals.css").write_text(CSS_TW, encoding="utf-8")
    (proj / "app" / "layout.jsx").write_text(
        'import "./globals.css";\n\n'
        f'export const metadata = {{ title: "{layout.get("source","Landing")}" }};\n\n'
        'export default function RootLayout({ children }) {\n'
        '  return (<html lang="vi"><body>{children}</body></html>);\n}\n', encoding="utf-8")
    # Trang chu: render responsive desktop + mobile (board dau moi ben)
    home_boards = [boards[0]] + ([mobile["boards"][0]] if mobile else [])
    imports = "\n".join(f'import {b["comp"]} from "../components/{b["comp"]}";' for b in home_boards)
    body = _responsive_body([boards[0]], {"boards": [mobile["boards"][0]]} if mobile else None)
    (proj / "app" / "page.jsx").write_text(
        f'{imports}\n\nexport default function Page() {{\n  return (\n    <>\n      {body}\n    </>\n  );\n}}\n',
        encoding="utf-8")
    # Cac artboard khac (neu co) -> route rieng (chi desktop)
    for b in boards[1:]:
        d = proj / "app" / b["slug"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "page.jsx").write_text(
            f'import {b["comp"]} from "../../components/{b["comp"]}";\n\n'
            f'export default function Page() {{\n  return <{b["comp"]} />;\n}}\n', encoding="utf-8")

    (proj / "next.config.js").write_text(
        "/** @type {import('next').NextConfig} */\nmodule.exports = {};\n", encoding="utf-8")
    (proj / "tailwind.config.js").write_text(TAILWIND_CFG_NEXT, encoding="utf-8")
    (proj / "postcss.config.js").write_text(POSTCSS_CFG_CJS, encoding="utf-8")
    (proj / "package.json").write_text(json.dumps({
        "name": _slug(layout.get("source", "psd-landing")),
        "private": True, "version": "0.1.0",
        "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
        "dependencies": {"next": "^14.2.5", "react": "^18.3.1", "react-dom": "^18.3.1"},
        "devDependencies": {"tailwindcss": "^3.4.10", "postcss": "^8.4.41", "autoprefixer": "^10.4.20"},
    }, indent=2), encoding="utf-8")
    _copy_assets(out_dir, proj, "assets")
    if mobile:
        _copy_assets(mobile["dir"], proj, "assets-m")
    _write_readme(proj, boards, "npm run dev", mobile)
    return proj


def _write_readme(proj, boards, run_cmd, mobile=None):
    reps = []
    for b in boards:
        for rp in b["repeats"]:
            reps.append(f"- `{rp['comp']}` x{rp['count']} (data: `{rp['comp'][0].lower()+rp['comp'][1:]}Data`)")
    rep_txt = "\n".join(reps) if reps else "- (khong phat hien cum lap)"
    mob = ""
    if mobile:
        mob = ("\n## Desktop / Mobile\n\n"
               "Co ban design MOBILE rieng. Desktop hien tu breakpoint `md` tro len,\n"
               "mobile hien duoi `md` (xem App.jsx / page.jsx). Component mobile co tien to `M`,\n"
               "anh mobile o `public/assets-m`.\n")
    (proj / "README.md").write_text(
        f"# Export\n\n```bash\nnpm install\n{run_cmd}\n```\n{mob}\n"
        "## Tich hop API\n\n"
        "Cac cum lap da thanh component render bang `.map()` qua mang data:\n\n"
        f"{rep_txt}\n\n"
        "- Thay cac mang `*Data` bang data that tu BE (xem `useLandingData`).\n"
        "- Nut nhan qua goi `onClaim(id)` - cam API vao ham nay trong component.\n"
        "- O vat pham: dien `item.items = [{src,x,y,w,h}]` (toa do trong the).\n"
        "- `item.claimed = true` -> hien lop mo danh dau da nhan.\n",
        encoding="utf-8")


def _load_variant(vdir, asset_dir, comp_prefix):
    vdir = Path(vdir)
    layout = json.loads((vdir / "layout.json").read_text(encoding="utf-8"))
    boards = _artboards_from_layout(layout, asset_dir, comp_prefix)
    if not layout.get("artboards"):
        boards[0]["H"] = _content_bottom_from_image(
            vdir / layout.get("screenshot", "screenshot.png"), layout["canvas"]["height"])
    return layout, boards


def export(out_dir, framework="react", mobile_dir=None):
    out_dir = Path(out_dir)
    layout, boards = _load_variant(out_dir, "assets", "")
    mobile = None
    if mobile_dir:
        m_layout, m_boards = _load_variant(mobile_dir, "assets-m", "M")
        mobile = {"dir": Path(mobile_dir), "layout": m_layout, "boards": m_boards}

    proj = _export_next(out_dir, layout, boards, mobile) if framework == "next" \
        else _export_react(out_dir, layout, boards, mobile)

    nrep = sum(len(b["repeats"]) for b in boards)
    nflat = sum(len(b["flat"]) for b in boards)
    tag = " + mobile" if mobile else ""
    print(f"[{framework}{tag}] {len(boards)} trang, {nrep} cum lap, {nflat} anh phang -> {proj}")
    for b in boards:
        for rp in b["repeats"]:
            print(f"    lap: {rp['comp']} x{rp['count']}")
    if mobile:
        mrep = sum(len(b['repeats']) for b in mobile['boards'])
        print(f"    mobile: {len(mobile['boards'])} trang, {mrep} cum lap")
    return proj


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "output"
    fw = sys.argv[2] if len(sys.argv) > 2 else "react"
    export(d, fw)
