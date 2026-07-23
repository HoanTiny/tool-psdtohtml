"""
Giao dien WEB keo-tha cho psd2html (khong can go lenh).

Chay:
  venv\\Scripts\\python.exe -m psd2html.webapp
Roi mo http://localhost:5000

Luong (3 buoc):
  1) Keo PSD (desktop + tuy chon mobile) + chon chat luong anh -> bam "Phan tich".
  2) EDITOR: xem preview + danh sach anh (layer) nhom theo section. Tich giu/bo tung
     anh, hoac bat/tat ca section. Preview an/hien ngay theo lua chon.
  3) Chon dinh dang + tuy chon -> bam "Xuat web" -> tai ZIP / xem preview.

Parse (cham) tach roi Export (nhanh): doi lua chon anh roi xuat lai KHONG parse lai.
"""

import shutil
import threading
import zipfile
import json
import socket
import atexit
import subprocess
from pathlib import Path

from flask import (Flask, request, jsonify, send_from_directory, send_file,
                   abort, render_template)
from werkzeug.utils import secure_filename

from .parser import parse_psd
from .merge import parse_and_merge
from .render_slices import render as render_slices
from .export_web import export as export_web

app = Flask(__name__)
# Tool chay local: UI dang phat trien phai cap nhat ngay khi reload trinh duyet.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.jinja_env.auto_reload = True
# Cho phep tong upload rat nang (nhieu PSD section, moi file co the vai tram MB).
# 6GB - dieu chinh qua bien moi truong PSD2HTML_MAX_MB neu can.
import os as _os
_max_mb = int(_os.environ.get("PSD2HTML_MAX_MB", "6144"))
app.config["MAX_CONTENT_LENGTH"] = _max_mb * 1024 * 1024

BASE = Path(__file__).resolve().parent.parent
JOBS_DIR = BASE / "output_web"
JOBS_DIR.mkdir(exist_ok=True)


# LUON tra JSON khi loi (thay vi trang HTML) de frontend hien duoc thong bao.
@app.errorhandler(413)
def _too_large(e):
    return jsonify({"error": f"File qua lon (vuot {_max_mb}MB tong). "
                             "Tang bien moi truong PSD2HTML_MAX_MB roi chay lai."}), 413


@app.errorhandler(400)
def _bad_request(e):
    return jsonify({"error": f"Yeu cau khong hop le: {getattr(e, 'description', e)}"}), 400


@app.errorhandler(500)
def _server_error(e):
    return jsonify({"error": f"Loi server: {getattr(e, 'description', e)}"}), 500

jobs = {}          # job_id -> {phase, status, step, error, manifest, ...}
_counter = [0]


def _new_job_id():
    _counter[0] += 1
    return f"job{_counter[0]}"


# Muc chat luong anh -> (fmt, webp_quality, webp_lossless_max)
QUALITY_PRESETS = {
    "balanced": ("webp", 92, 300000),   # can bang (mac dinh)
    "high":     ("webp", 97, 800000),   # net cao (webp), nang hon chut
    "png":      ("png", None, None),    # anh goc PNG (net nhat, nang nhat)
}


def _parse_input(psd_list, out_dir, quality="balanced"):
    """1 file -> parse thuong; nhieu file -> moi file 1 section, ghep doc."""
    fmt, q, lm = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])
    if len(psd_list) == 1:
        return parse_psd(str(psd_list[0]), str(out_dir), fmt, q, lm)
    return parse_and_merge([str(p) for p in psd_list], str(out_dir),
                           asset_fmt=fmt, webp_quality=q, webp_lossless_max=lm)


# ----------------------------------------------------------------------------
# BUOC 1: PARSE (cham) -> tao layout.json + assets, roi build MANIFEST cho editor
# ----------------------------------------------------------------------------

# ---------------- GOP LAYER (group) ----------------
# Nguoi dung chon nhieu layer -> ghep thanh 1 anh (nhu group trong PSD) de web gon.
# Luu 'groups.json' (danh sach group) canh layout; layout HIEU LUC = pristine + groups.

def _pristine_layout(vdir):
    """Tra ve layout GOC (chua group/loc). Tao layout.orig.json tu layout.json lan dau."""
    vdir = Path(vdir)
    orig = vdir / "layout.orig.json"
    if not orig.exists():
        shutil.copyfile(vdir / "layout.json", orig)
    return json.loads(orig.read_text(encoding="utf-8"))


def _groups_path(vdir):
    return Path(vdir) / "groups.json"


def _load_groups(vdir):
    p = _groups_path(vdir)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save_groups(vdir, groups):
    _groups_path(vdir).write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------- CHINH SUA per-layer (editor kieu Photoshop) ----------------
# edits.json = { "<layerId>": {bbox?, z?, text?, link?, alt?} }. Nen chung cho
# ca 3 tru cot: keo/resize/z-order (bbox+z), chu that (text), link/nut+alt.
def _edits_path(vdir):
    return Path(vdir) / "edits.json"


def _load_edits(vdir):
    p = _edits_path(vdir)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_edits(vdir, edits):
    _edits_path(vdir).write_text(json.dumps(edits, ensure_ascii=False, indent=2), encoding="utf-8")


# Khoa ghi edits.json: FE co the ban nhieu /edit gan nhu dong thoi (vd doi link +
# alt cung luc) -> read-modify-write phai tuan tu, khong se ghi de mat key.
_EDIT_LOCK = threading.Lock()


def _apply_edits(vdir, layout):
    """Ap edits len layout HIEU LUC: bbox override, z-order (sort on dinh), text/link/alt.
    Gan l['z'] cho MOI layer de manifest doc lai duoc. z mac dinh 0 (giu thu tu goc)."""
    edits = _load_edits(vdir)
    for l in layout["layers"]:
        e = edits.get(l["id"]) or {}
        if e.get("bbox"):
            l["bbox"] = {**l["bbox"], **{k: e["bbox"][k] for k in ("x", "y", "width", "height")
                                         if k in e["bbox"]}}
        if e.get("alt") is not None:
            l["alt"] = e["alt"]
        if e.get("link"):
            l["link"] = e["link"]
        if e.get("text"):
            t = dict(l.get("text") or {})
            t.update(e["text"])
            l["text"] = t
        if e.get("fname"):
            l["export_name"] = e["fname"]   # ten file mong muon khi xuat (slug hoa sau)
        if e.get("fx"):
            l["fx"] = e["fx"]               # hieu ung gan tay cho layer (shine/glow/float...)
        l["z"] = e.get("z", 0)
    # sort on dinh theo z (Python sort stable -> z bang nhau giu nguyen thu tu ve)
    layout["layers"].sort(key=lambda l: l.get("z", 0))
    return layout


def _norm_group_name(name):
    """Chuan hoa ten de gom nhom goi y: bo ' copy', ' copy 2', duoi so/khoang trang."""
    import re
    s = (name or "").lower()
    s = re.sub(r"\s+copy(\s+\d+)?$", "", s)
    s = re.sub(r"[\s_\-]*\d+$", "", s)
    return s.strip()


def _blend_over(base, top, mode):
    """Ghep 'top' len 'base' (deu HxWx4 float 0..1, straight alpha) theo blend mode.
    Xap xi cac mode pho bien; mode la khong ho tro -> normal (source-over)."""
    import numpy as np
    Cb, ab = base[..., :3], base[..., 3:4]
    Cs, as_ = top[..., :3], top[..., 3:4]
    if mode == "multiply":
        Bl = Cb * Cs
    elif mode == "screen":
        Bl = 1 - (1 - Cb) * (1 - Cs)
    elif mode == "overlay":
        Bl = np.where(Cb <= 0.5, 2 * Cb * Cs, 1 - 2 * (1 - Cb) * (1 - Cs))
    elif mode in ("hard-light",):
        Bl = np.where(Cs <= 0.5, 2 * Cb * Cs, 1 - 2 * (1 - Cb) * (1 - Cs))
    elif mode == "darken":
        Bl = np.minimum(Cb, Cs)
    elif mode == "lighten":
        Bl = np.maximum(Cb, Cs)
    elif mode in ("soft-light",):
        Bl = (1 - 2 * Cs) * Cb * Cb + 2 * Cs * Cb        # xap xi Pegtop
    elif mode in ("color-dodge", "plus-lighter"):
        Bl = np.minimum(1.0, Cb / np.clip(1 - Cs, 1e-4, 1))
    else:
        Bl = Cs                                          # normal + mode chua ho tro
    Cs_eff = (1 - ab) * Cs + ab * Bl
    ao = as_ + ab * (1 - as_)
    Co = (Cs_eff * as_ + Cb * ab * (1 - as_)) / np.clip(ao, 1e-6, None)
    return np.concatenate([Co, ao], axis=-1)


def _composite_members(vdir, members):
    """Ghep danh sach layer (theo thu tu ve, duoi->tren) thanh 1 anh RGBA + union bbox.
    members: list dict layer co 'bbox','asset','opacity','blend'."""
    import numpy as np
    from PIL import Image
    vdir = Path(vdir)
    xs = [m["bbox"]["x"] for m in members]
    ys = [m["bbox"]["y"] for m in members]
    ex = max(m["bbox"]["x"] + m["bbox"]["width"] for m in members)
    ey = max(m["bbox"]["y"] + m["bbox"]["height"] for m in members)
    ux, uy = min(xs), min(ys)
    W, H = ex - ux, ey - uy
    base = np.zeros((H, W, 4), dtype=float)
    for m in members:
        p = vdir / m["asset"]
        if not p.exists():
            continue
        im = Image.open(p).convert("RGBA")
        arr = np.asarray(im).astype(float) / 255.0
        op = m.get("opacity", 1)
        if op is None:
            op = 1
        arr[..., 3] *= op
        bx, by = m["bbox"]["x"] - ux, m["bbox"]["y"] - uy
        ih, iw = arr.shape[:2]
        ih, iw = min(ih, H - by), min(iw, W - bx)
        if ih <= 0 or iw <= 0:
            continue
        top = np.zeros((H, W, 4), dtype=float)
        top[by:by + ih, bx:bx + iw] = arr[:ih, :iw]
        base = _blend_over(base, top, m.get("blend"))
    out = (np.clip(base, 0, 1) * 255).astype("uint8")
    return Image.fromarray(out, "RGBA"), {"x": ux, "y": uy, "width": W, "height": H}


def _effective_layout(vdir):
    """Layout HIEU LUC = pristine + ap dung cac group (ghep asset). Dam bao asset gop
    ton tai tren dia (assets/<gid>.webp). Tra ve dict layout."""
    vdir = Path(vdir)
    layout = _pristine_layout(vdir)
    groups = _load_groups(vdir)
    if not groups:
        return _apply_edits(vdir, layout)
    by_id = {l["id"]: l for l in layout["layers"]}
    # THU TU VE GOC trong PSD (index nho = duoi/nen, lon = tren). Dung de ghep group
    # DUNG chong lop - khong theo thu tu NGUOI DUNG CLICK chon (Set, tuy tien) nen
    # tranh loi kieu 'layer dang le o tren lai bi ghep xuong duoi layer khac'.
    paint_order = {l["id"]: i for i, l in enumerate(layout["layers"])}
    assets_dir = vdir / "assets"
    for g in groups:
        members = [by_id[i] for i in g["members"] if i in by_id]
        members = [m for m in members if m.get("asset")]
        members.sort(key=lambda m: paint_order.get(m["id"], 0))   # duoi -> tren (dung z-order)
        if len(members) < 2:
            continue
        gid = g["id"]
        asset_rel = f"assets/{gid}.webp"
        asset_path = vdir / asset_rel
        if not asset_path.exists():
            try:
                img, ubbox = _composite_members(vdir, members)
                img.save(asset_path, "WEBP", quality=92, method=4)
            except Exception:
                continue
        else:
            xs = [m["bbox"]["x"] for m in members]; ys = [m["bbox"]["y"] for m in members]
            ubbox = {"x": min(xs), "y": min(ys),
                     "width": max(m["bbox"]["x"] + m["bbox"]["width"] for m in members) - min(xs),
                     "height": max(m["bbox"]["y"] + m["bbox"]["height"] for m in members) - min(ys)}
        mset = set(g["members"])
        idxs = [i for i, l in enumerate(layout["layers"]) if l["id"] in mset]
        pos = min(idxs) if idxs else len(layout["layers"])
        node = {"id": gid, "name": g.get("name") or gid, "kind": "pixel",
                "bbox": ubbox, "opacity": 1.0,
                "parent": (members[0].get("parent") if members else None),  # giu trong folder goc
                "asset": asset_rel, "grouped": [m["id"] for m in members]}
        layout["layers"] = ([l for l in layout["layers"][:pos] if l["id"] not in mset]
                            + [node]
                            + [l for l in layout["layers"][pos:] if l["id"] not in mset])
    return _apply_edits(vdir, layout)


def _suggest_groups(layout):
    """Goi y nhom: layer co asset, CUNG SECTION + cung ten chuan hoa, >=2 -> 1 goi y.
    Rang buoc cung section de tranh gom nham layer ten chung ('Layer') o cac section khac."""
    from collections import defaultdict
    secs = layout.get("sections") or [{"y0": 0, "y1": layout["canvas"]["height"]}]

    def sec_of(cy):
        for i, s in enumerate(secs):
            if s["y0"] <= cy < s["y1"]:
                return i
        return len(secs) - 1

    buckets = defaultdict(list)
    for l in layout["layers"]:
        if not l.get("asset") or l.get("grouped"):
            continue
        key = _norm_group_name(l.get("name"))
        if not key:
            continue
        b = l["bbox"]
        buckets[(sec_of(b["y"] + b["height"] / 2), key)].append(l["id"])
    out = [{"name": k[1], "section": k[0], "members": v}
           for k, v in buckets.items() if len(v) >= 2]
    out.sort(key=lambda g: (g["section"], -len(g["members"])))
    return out


def _collect_psd_groups(layout):
    """Lay cac GROUP (folder) co san trong PSD -> de gop nguyen folder thanh 1 anh.
    Tra ve list {id, name, members(id la anh la con-chau), n} - bo group bao trum
    toan bo trang, sort folder nho truoc (huu ich hon). Dung tu layout PRISTINE."""
    from collections import defaultdict
    children = defaultdict(list)
    node = {}
    for l in layout["layers"]:
        node[l["id"]] = l
        children[l.get("parent")].append(l["id"])

    def leaves(gid):
        out = []
        for cid in children.get(gid, []):
            c = node[cid]
            if c.get("kind") == "group":
                out += leaves(cid)
            elif c.get("asset"):
                out.append(cid)
        return out

    total = sum(1 for l in layout["layers"] if l.get("asset"))
    groups = []
    for l in layout["layers"]:
        if l.get("kind") != "group":
            continue
        mem = leaves(l["id"])
        if 2 <= len(mem) < max(total, 3):     # bo folder bao trum ca trang
            groups.append({"id": l["id"], "name": (l.get("name") or l["id"]),
                           "members": mem, "n": len(mem)})
    groups.sort(key=lambda g: g["n"])
    return groups[:60]


def _variant_manifest(job_id, vdir, url_prefix):
    """
    Doc layout HIEU LUC (pristine + group) cua 1 bien the -> manifest cho frontend:
    canvas, section, tung ANH (layer co asset) kem section index, group hien co, goi y.
    """
    layout = _effective_layout(vdir)
    canvas = layout["canvas"]
    # Route /result/<job>/<path> da tro thang vao thu muc out -> URL KHONG kem 'out/'.
    base = f"/result/{job_id}/{url_prefix}"

    secs = layout.get("sections")
    if not secs:   # 1 file -> chua chia section -> coi ca trang la 1 section
        secs = [{"name": "Trang", "y0": 0, "y1": canvas["height"]}]

    def _section_of(cy):
        for i, s in enumerate(secs):
            if s["y0"] <= cy < s["y1"]:
                return i
        return len(secs) - 1 if cy >= secs[-1]["y1"] else 0

    # vi tri goc trong PSD (thu tu ve): dung de dung cay layer DUNG THU TU nhu Photoshop
    order_of = {l["id"]: i for i, l in enumerate(layout["layers"])}

    items = []
    for l in layout["layers"]:
        if not l.get("asset"):   # bo group/layer khong co anh
            continue
        b = l["bbox"]
        tx = l.get("text") or {}
        items.append({
            "id": l["id"],
            "name": (l.get("name") or l["id"]),
            "kind": l.get("kind"),
            "parent": l.get("parent"),         # id folder cha (dựng cây kiểu PTS)
            "order": order_of.get(l["id"], 0),  # vi tri trong PSD (ve: nho=duoi/nen)
            "bbox": b,
            "asset": base + l["asset"],
            "text": bool(tx.get("content")),
            "section": _section_of(b["y"] + b["height"] / 2),
            "group": bool(l.get("grouped")),          # la layer GOP (nhieu layer)
            "count": len(l.get("grouped") or []),     # so layer thanh vien
            "z": l.get("z", 0),                       # thu tu lop (edits)
            # du lieu cho tru cot 2/3 (chinh sua text, gan link/alt)
            "textData": {"content": tx.get("content", ""), "size": tx.get("size"),
                         "color": tx.get("color"), "asText": bool(tx.get("asText"))} if tx.get("content") else None,
            "link": l.get("link"),
            "alt": l.get("alt", ""),
            "fname": l.get("export_name", ""),        # ten file xuat tuy chinh (rong = mac dinh)
            "fx": l.get("fx", ""),                     # hieu ung gan tay (rong = khong)
        })

    # Group co san trong PSD (folder) -> goi y gop nguyen folder
    pristine = _pristine_layout(vdir)
    pbb = {l["id"]: l.get("bbox") for l in pristine["layers"]}
    psd_groups = []
    for g in _collect_psd_groups(pristine):
        ys = [pbb[m]["y"] + pbb[m]["height"] / 2 for m in g["members"] if pbb.get(m)]
        psd_groups.append({**g, "section": _section_of(sum(ys) / len(ys)) if ys else 0})

    return {
        "canvas": canvas,
        "screenshot": base + layout.get("screenshot", "screenshot.png"),
        "sections": [{"name": s["name"], "y0": s["y0"], "y1": s["y1"]} for s in secs],
        "layers": items,
        "groups": _load_groups(vdir),
        "suggestions": _suggest_groups(layout),
        "psdGroups": psd_groups,
        # cac node FOLDER (group PSD) de dung cay layer kieu Photoshop (kem order)
        "nodes": [{"id": l["id"], "name": (l.get("name") or l["id"]), "parent": l.get("parent"),
                   "order": order_of.get(l["id"], 0)}
                  for l in layout["layers"] if l.get("kind") == "group"],
    }


def _build_manifest(job_id):
    out = JOBS_DIR / job_id / "out"
    man = {"desktop": _variant_manifest(job_id, out, ""), "mobile": None, "popups": []}
    if (out / "_mobile" / "layout.json").exists():
        man["mobile"] = _variant_manifest(job_id, out / "_mobile", "_mobile/")
    pdir = out / "_popups"
    if pdir.exists():
        for d in sorted(pdir.iterdir()):
            if not (d / "layout.json").exists():
                continue
            pid = d.name
            vm = _variant_manifest(job_id, d, f"_popups/{pid}/")
            nm = (d / "name.txt").read_text(encoding="utf-8").strip() if (d / "name.txt").exists() else pid
            man["popups"].append({"id": pid, "name": nm, **vm})
    return man


def _ensure_job(job_id):
    """Tra job trong RAM; neu mat (server restart) nhung du lieu con tren dia
    (output_web/<job>/out/layout.json) thi PHUC HOI lai job -> export/preview/edit
    khong bi 'Job khong ton tai' sau khi restart."""
    existing = jobs.get(job_id)
    if existing:
        return existing
    if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
        return None
    out = JOBS_DIR / job_id / "out"
    if not ((out / "layout.json").exists() or (out / "layout.orig.json").exists()):
        return None
    job = {"phase": "parse", "status": "done", "step": "San sang chinh sua",
           "sections": 0, "error": None, "manifest": None,
           "preview": None, "download": None, "files": []}
    try:
        job["manifest"] = _build_manifest(job_id)
    except Exception:
        pass
    jobs[job_id] = job
    return job


def _run_parse(job_id, desktop_psds, mobile_psds, quality="balanced", popup_psds=None):
    job = jobs[job_id]
    out = JOBS_DIR / job_id / "out"
    if out.exists():                       # don ket qua cu (tranh lan file section cu)
        shutil.rmtree(out, ignore_errors=True)
    try:
        n = len(desktop_psds)
        job["step"] = f"Doc PSD desktop ({n} section)..." if n > 1 else "Doc PSD desktop..."
        _parse_input(desktop_psds, out, quality)

        if mobile_psds:
            job["step"] = "Doc PSD mobile..."
            _parse_input(mobile_psds, out / "_mobile", quality)

        # POPUP: moi file -> 1 popup rieng out/_popups/p<i> (1 file/popup, khong ghep)
        for i, pf in enumerate(popup_psds or []):
            pid = f"p{i}"
            job["step"] = f"Doc PSD popup {i + 1}..."
            pdir = out / "_popups" / pid
            _parse_input([pf], pdir, quality)
            (pdir / "name.txt").write_text(Path(pf).stem, encoding="utf-8")   # ten hien thi

        job["step"] = "Dung trinh chinh sua..."
        job["manifest"] = _build_manifest(job_id)
        job["status"] = "done"
        job["step"] = "San sang chinh sua"
    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"] = f"{e}"
        job["trace"] = traceback.format_exc()[-1500:]


# ----------------------------------------------------------------------------
# BUOC 3: EXPORT (nhanh) -> loc layer bi bo roi render code + ZIP
# ----------------------------------------------------------------------------

def _slug_name(s):
    """Chuan hoa ten do user nhap -> ten file an toan (khong dau, khong khoang trang)."""
    import re, unicodedata
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = s.encode("ascii", "ignore").decode()      # bo dau tieng Viet
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", s).strip("-._").lower()
    return s or "img"


def _apply_export_names(vdir, layout):
    """Doi ten file asset khi xuat: layer co 'export_name' -> tao ban COPY assets/<slug>.<ext>
    (ten khong trung) va tro layer sang ban do. KHONG xoa ban goc (chia se voi cache parse)."""
    vdir = Path(vdir)
    used = {Path(l["asset"]).name for l in layout["layers"] if l.get("asset")}
    for l in layout["layers"]:
        nm = l.get("export_name")
        if not nm or not l.get("asset"):
            continue
        src = vdir / l["asset"]
        if not src.exists():
            continue
        ext = src.suffix
        base = _slug_name(Path(str(nm)).stem)      # bo duoi neu user go kem .webp
        cand, k = base + ext, 1
        while cand in used and cand != src.name:   # tranh dung ten layer khac
            k += 1
            cand = f"{base}-{k}{ext}"
        used.add(cand)
        dst = src.parent / cand
        if dst != src:
            try:
                shutil.copyfile(src, dst)
            except OSError:
                continue
        l["asset"] = f"assets/{cand}"
    return layout


def _apply_selection(vdir, disabled):
    """
    Ghi layout.json = layout HIEU LUC (pristine + group) roi BO cac layer id trong
    `disabled`. Luon dung tu pristine + groups nen export lai nhieu lan deu dung.
    """
    vdir = Path(vdir)
    layout = _effective_layout(vdir)
    dis = set(disabled or [])
    if dis:
        layout["layers"] = [l for l in layout["layers"] if l.get("id") not in dis]
    layout = _apply_export_names(vdir, layout)     # doi ten file asset theo yeu cau user
    (vdir / "layout.json").write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")


def _reset_project_dir(p):
    """Xoa code sinh cu trong project react/next NHUNG GIU LAI node_modules -> tranh
    cai lai npm moi lan + tranh loi [WinError 5] khoa file esbuild.exe khi con server
    xem truoc/build cu dang giu (Windows khong cho xoa file dang mo)."""
    import stat
    p = Path(p)
    if not p.exists():
        return

    def _onerr(func, path, exc):   # file read-only/locked -> bo write-protect roi thu lai
        try:
            _os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass
    for child in p.iterdir():
        if child.name == "node_modules":     # GIU: khong dung toi -> khong dinh khoa esbuild
            continue
        if child.is_dir():
            shutil.rmtree(child, onerror=_onerr)
        else:
            try:
                child.unlink()
            except OSError:
                pass


def _run_export(job_id, fmt, lang, swiper, feats, disabled_d, disabled_m, disabled_p=None):
    job = jobs[job_id]
    out = JOBS_DIR / job_id / "out"
    try:
        job["status"] = "running"
        job["step"] = "Ap dung lua chon anh..."
        _apply_selection(out, disabled_d)
        mobile_dir = out / "_mobile"
        has_mobile = (mobile_dir / "layout.json").exists()
        if has_mobile:
            _apply_selection(mobile_dir, disabled_m)

        # POPUP: ap lua chon anh cho tung popup + gom danh sach thu muc popup
        disabled_p = disabled_p or {}
        popup_dirs = []
        pdir = out / "_popups"
        if pdir.exists():
            for d in sorted(pdir.iterdir()):
                if not (d / "layout.json").exists():
                    continue
                pid = d.name
                _apply_selection(d, disabled_p.get(pid) or [])
                nm = (d / "name.txt").read_text(encoding="utf-8").strip() if (d / "name.txt").exists() else pid
                popup_dirs.append({"id": pid, "name": nm, "dir": str(d)})

        # Don ket qua render cu (tranh lan file section cu khi xuat lai). Dung preview
        # TRUOC (nha khoa file). react/next: GIU node_modules (khong xoa -> khong dinh
        # khoa esbuild.exe). 'sections' (slices) khong co node_modules -> xoa han.
        _kill_preview(job_id)
        _reset_project_dir(out / "react-app")
        _reset_project_dir(out / "next-app")
        p = out / "sections"
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

        job["step"] = "Sinh code..."
        asset_names = None
        if fmt == "slices":
            render_slices(str(out), swiper=swiper)
            job["preview"] = f"/result/{job_id}/index.html"
            job["files"] = []
            zip_src = out
            zip_include = ["index.html", "style.css", "assets", "sections"]
            asset_names = _used_asset_names(out)   # chi zip anh dang dung
        else:
            proj = export_web(str(out), framework=fmt, lang=lang,
                              mobile_dir=str(mobile_dir) if has_mobile else None,
                              detect_repeats=feats.get("fluid", False),
                              swiper=swiper, feats=feats, popup_dirs=popup_dirs)
            # bo anh thua (layer an / thanh vien da gop) khoi ban copy trong project
            _prune_assets(Path(proj) / "public" / "assets", _used_asset_names(out))
            if has_mobile:
                _prune_assets(Path(proj) / "public" / "assets-m", _used_asset_names(mobile_dir))
            for p in popup_dirs:   # popup: don asset thua trong /assets-<id>
                _prune_assets(Path(proj) / "public" / f"assets-{p['id']}",
                              _used_asset_names(Path(p["dir"])))
            job["preview"] = None
            zip_src = Path(proj)
            zip_include = None  # zip toan bo project
            job["files"] = sorted(p.name for p in Path(proj).glob("**/*")
                                  if p.is_file() and "node_modules" not in str(p))[:60]

        job["step"] = "Nen ZIP..."
        zip_path = JOBS_DIR / job_id / "result.zip"
        _make_zip(zip_src, zip_path, zip_include, asset_names=asset_names)
        job["download"] = f"/download/{job_id}"

        job["status"] = "done"
        job["step"] = "Hoan tat"
    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"] = f"{e}"
        job["trace"] = traceback.format_exc()[-1500:]


def _run_preview(job_id, swiper, disabled_d, disabled_m):
    """
    Xem thu NHANH: render slices (HTML thuan, khong can npm) theo lua chon anh
    hien tai roi tra ve URL de nhung iframe. Khong nen ZIP - chi de review.
    Slices dung duoc cho MOI format vi chi de xem truoc bo cuc + anh se xuat.
    """
    job = jobs[job_id]
    out = JOBS_DIR / job_id / "out"
    try:
        job.update(phase="preview", status="running", step="Ap dung lua chon...",
                   error=None, trace=None, preview=None)
        _apply_selection(out, disabled_d)
        mobile_dir = out / "_mobile"
        if (mobile_dir / "layout.json").exists():
            _apply_selection(mobile_dir, disabled_m)

        job["step"] = "Dung ban xem thu (HTML)..."
        render_slices(str(out), swiper=swiper)
        job["preview"] = f"/result/{job_id}/index.html"
        job["status"] = "done"
        job["step"] = "San sang xem"
    except Exception as e:
        import traceback
        job["status"] = "error"
        job["error"] = f"{e}"
        job["trace"] = traceback.format_exc()[-1500:]


# ============ BUILD + XEM TRUOC REACT/NEXT (npm) ============
#
# react/next KHONG the xem truoc bang HTML thuan (can bundler). Nut "Build & Xem
# truoc" se: npm install (neu chua co node_modules) -> npm run build -> chay server
# tinh (vite preview / next start) tren 1 cong rieng, roi frontend nhung iframe tro
# thang vao http://127.0.0.1:<cong> (giu nguyen duong dan tuyet doi /assets/...).
#
# Moi job giu 1 tien trinh server; build lai se kill cai cu truoc.
PREVIEW_SERVERS = {}   # job_id -> {"proc": Popen, "port": int, "fmt": str}
_NPM = shutil.which("npm") or "npm"


def _free_port():
    """Xin 1 cong TCP dang ranh tu OS (tranh dung trung)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _port_alive(port, timeout=0.5):
    """True neu co ai dang lang nghe tren cong (server da san sang)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _kill_preview(job_id):
    """Dung tien trinh server xem truoc cua job (neu dang chay)."""
    info = PREVIEW_SERVERS.pop(job_id, None)
    if not info:
        return
    proc = info.get("proc")
    if proc and proc.poll() is None:
        try:
            if _os.name == "nt":
                # npm.cmd tao tien trinh con (vite/next). terminate tien trinh cha
                # khong dam bao tien trinh con dung, nen can dung ca cay tien trinh.
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, timeout=10, check=False)
            else:
                proc.terminate()
                proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _kill_all_previews():
    for jid in list(PREVIEW_SERVERS):
        _kill_preview(jid)


atexit.register(_kill_all_previews)


def _proj_dir(job_id, fmt):
    out = JOBS_DIR / job_id / "out"
    return out / ("next-app" if fmt == "next" else "react-app")


def _npm(args, cwd, timeout=None):
    """Chay npm dong bo, tra (ok, log). Windows: npm la .cmd -> can shell tren mot
    so cau hinh; dung duong dan da resolve + shell=False cho on dinh."""
    try:
        r = subprocess.run([_NPM, *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=timeout,
                           shell=(_os.name == "nt" and _NPM == "npm"))
        log = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, log[-3000:]
    except subprocess.TimeoutExpired:
        return False, f"npm {' '.join(args)}: qua thoi gian ({timeout}s)"
    except Exception as e:
        return False, f"npm {' '.join(args)}: {e}"


def _node_dependencies_ready(proj, fmt):
    """Kiem tra dependency build THUC SU san sang, khong chi nhin thu muc.

    Mot lan xoa bi gian doan co the de lai node_modules rong/do dang. Khi do viec
    chi kiem tra node_modules.exists() se bo qua npm install du vite/next da mat.
    """
    tool = "next" if fmt == "next" else "vite"
    shim = f"{tool}.cmd" if _os.name == "nt" else tool
    return ((proj / "node_modules" / tool / "package.json").is_file()
            and (proj / "node_modules" / ".bin" / shim).is_file())


def _run_build_preview(job_id, fmt):
    """Build project react/next roi chay server tinh -> job['build'] mang tien do."""
    job = jobs[job_id]
    proj = _proj_dir(job_id, fmt)
    b = {"status": "running", "step": "Chuan bi...", "url": None, "error": None, "log": None}
    job["build"] = b
    try:
        if not (proj / "package.json").exists():
            raise RuntimeError("Chua co project. Hay bam Xuat web (react/next) truoc.")

        # 1) cai dependency neu chua co HOAC node_modules bi xoa do dang.
        if not _node_dependencies_ready(proj, fmt):
            b["step"] = "npm install (thieu dependency, co the vai phut)..."
            ok, log = _npm(["install", "--no-audit", "--no-fund"], proj, timeout=900)
            if not ok:
                raise RuntimeError("npm install that bai")
            b["log"] = log
            if not _node_dependencies_ready(proj, fmt):
                raise RuntimeError("npm install xong nhung vite/next van bi thieu")

        # 2) build tinh
        b["step"] = "npm run build..."
        ok, log = _npm(["run", "build"], proj, timeout=900)
        b["log"] = log
        if not ok:
            raise RuntimeError("npm run build that bai")

        # 3) chay server xem truoc tren cong rieng
        _kill_preview(job_id)
        port = _free_port()
        if fmt == "next":
            cmd = [_NPM, "start", "--", "-p", str(port)]
        else:  # react / vite
            cmd = [_NPM, "run", "preview", "--", "--port", str(port),
                   "--strictPort", "--host", "127.0.0.1"]
        b["step"] = f"Khoi dong server (cong {port})..."
        proc = subprocess.Popen(cmd, cwd=str(proj),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                shell=(_os.name == "nt" and _NPM == "npm"))
        PREVIEW_SERVERS[job_id] = {"proc": proc, "port": port, "fmt": fmt}

        # cho server len (toi da ~40s)
        for _ in range(80):
            if proc.poll() is not None:
                raise RuntimeError("Server xem truoc thoat som (xem log build).")
            if _port_alive(port):
                break
            import time
            time.sleep(0.5)
        else:
            raise RuntimeError("Server xem truoc khong phan hoi kip.")

        b["url"] = f"http://127.0.0.1:{port}/"
        b["step"] = "San sang"
        b["status"] = "done"
    except Exception as e:
        import traceback
        b["status"] = "error"
        b["error"] = f"{e}"
        b["log"] = (b.get("log") or "") + "\n" + traceback.format_exc()[-800:]


def _used_asset_names(vdir):
    """Ten cac file asset THUC SU dung trong layout.json da loc (bo layer an + thanh
    vien da gop). Dung de KHONG dong goi anh thua vao source web."""
    p = Path(vdir) / "layout.json"
    if not p.exists():
        return None
    try:
        lay = json.loads(p.read_text(encoding="utf-8"))
        return {Path(l["asset"]).name for l in lay.get("layers", []) if l.get("asset")}
    except Exception:
        return None


def _prune_assets(assets_dir, used):
    """Xoa cac file trong assets_dir khong nam trong `used` (chi ap cho ban COPY
    trong project react/next, khong dung vao cache parse)."""
    if used is None:
        return
    d = Path(assets_dir)
    if not d.exists():
        return
    for f in d.iterdir():
        if f.is_file() and f.name not in used:
            try:
                f.unlink()
            except OSError:
                pass


def _make_zip(src, zip_path, include=None, asset_names=None):
    src = Path(src)

    def _skip(p):
        # bo anh khong dung (asset an / thanh vien da gop) khoi ZIP
        return (asset_names is not None and p.suffix.lower() in (".webp", ".png")
                and "assets" in p.parts and p.name not in asset_names)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if include is None:
            for p in src.rglob("*"):
                if p.is_file() and "node_modules" not in str(p) and not _skip(p):
                    zf.write(p, p.relative_to(src))
        else:
            for name in include:
                item = src / name
                if item.is_file():
                    zf.write(item, name)
                elif item.is_dir():
                    for p in item.rglob("*"):
                        if p.is_file() and not _skip(p):
                            zf.write(p, p.relative_to(src))


def _save_uploads(files, jdir, prefix):
    """
    Luu cac file upload vao thu muc con rieng (d/ hoac m/), GIU TEN GOC de buoc
    merge dat ten section sach (01-hero.psd -> 'hero'). Sort theo ten file.
    """
    sub = jdir / prefix
    sub.mkdir(parents=True, exist_ok=True)
    files = sorted([f for f in files if f and f.filename], key=lambda f: f.filename.lower())
    saved, used = [], set()
    for i, f in enumerate(files):
        name = secure_filename(f.filename) or f"section{i:02d}.psd"
        if name in used:                       # tranh trung ten (hiem)
            name = f"{i:02d}_{name}"
        used.add(name)
        path = sub / name
        f.save(path)
        saved.append(path)
    return saved


@app.route("/parse", methods=["POST"])
def parse():
    """Buoc 1: nhan PSD, parse (cham) -> tra job_id. Manifest lay qua /status."""
    desktops = [f for f in request.files.getlist("desktop") if f and f.filename]
    if not desktops:
        return jsonify({"error": "Chua chon file PSD desktop"}), 400
    quality = request.form.get("quality", "balanced")
    if quality not in QUALITY_PRESETS:
        quality = "balanced"

    job_id = _new_job_id()
    jdir = JOBS_DIR / job_id
    jdir.mkdir(parents=True, exist_ok=True)

    d_paths = _save_uploads(desktops, jdir, "d")
    m_paths = _save_uploads(request.files.getlist("mobile"), jdir, "m")
    # POPUP: moi file = 1 popup rieng (khong ghep doc nhu section)
    p_files = [f for f in request.files.getlist("popup") if f and f.filename]
    p_paths = _save_uploads(p_files, jdir, "p") if p_files else []

    jobs[job_id] = {"phase": "parse", "status": "running", "step": "Bat dau...",
                    "sections": len(d_paths), "error": None, "manifest": None,
                    "preview": None, "download": None, "files": []}
    threading.Thread(target=_run_parse, args=(job_id, d_paths, m_paths, quality, p_paths),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/export", methods=["POST"])
def export():
    """Buoc 3: nhan lua chon (format/option + danh sach anh bo) -> render + ZIP."""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    job = _ensure_job(job_id)
    if not job:
        return jsonify({"error": "Job khong ton tai hoac da het han. Hay phan tich lai."}), 400
    if not (JOBS_DIR / job_id / "out" / "layout.json").exists():
        return jsonify({"error": "Chua co du lieu parse. Hay phan tich lai."}), 400

    fmt = data.get("format", "slices")
    if fmt not in ("slices", "react", "next"):
        fmt = "slices"
    lang = data.get("lang", "js")
    if lang not in ("js", "ts"):
        lang = "js"

    def _flag(v):
        return v in (True, 1, "1", "true", "on", "yes")

    swiper = _flag(data.get("swiper"))
    feats = {"swiper_lib": _flag(data.get("swiper_lib")), "popups": _flag(data.get("popups")),
             "env_config": _flag(data.get("env_config")), "nav_menu": _flag(data.get("nav_menu")),
             "ai_enhance": _flag(data.get("ai_enhance")), "fluid": _flag(data.get("fluid")),
             "fx": _flag(data.get("fx")), "fx_reveal": _flag(data.get("fx_reveal"))}
    disabled_d = data.get("disabled_desktop") or []
    disabled_m = data.get("disabled_mobile") or []
    disabled_p = data.get("disabled_popup") or {}   # {pid: [layerIds]}

    job.update(phase="export", status="running", format=fmt, lang=lang,
               step="Bat dau xuat...", error=None, trace=None,
               preview=None, download=None, files=[])
    threading.Thread(target=_run_export,
                     args=(job_id, fmt, lang, swiper, feats, disabled_d, disabled_m, disabled_p),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/build_preview", methods=["POST"])
def build_preview():
    """Build project react/next (npm) roi chay server xem truoc. Chay nen; frontend
    doc tien do qua /status (truong 'build')."""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    job = _ensure_job(job_id)
    if not job:
        return jsonify({"error": "Job khong ton tai. Hay phan tich lai."}), 400
    fmt = job.get("format")
    if fmt not in ("react", "next"):
        return jsonify({"error": "Chi build duoc project react/next. Hay Xuat web truoc."}), 400
    if not (_proj_dir(job_id, fmt) / "package.json").exists():
        return jsonify({"error": "Chua co project. Hay bam Xuat web (react/next) truoc."}), 400
    threading.Thread(target=_run_build_preview, args=(job_id, fmt), daemon=True).start()
    return jsonify({"job_id": job_id})


def _variant_dir(job_id, variant):
    out = JOBS_DIR / job_id / "out"
    if variant == "mobile":
        return out / "_mobile"
    if isinstance(variant, str) and variant.startswith("popup:"):
        return out / "_popups" / variant.split(":", 1)[1]
    return out


@app.route("/group", methods=["POST"])
def group():
    """Gop nhieu layer thanh 1 anh (nhu group PSD). Tra manifest moi de editor ve lai."""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    variant = data.get("variant", "desktop")
    members = [m for m in (data.get("members") or []) if m]
    name = (data.get("name") or "Group").strip()[:40]
    job = _ensure_job(job_id)
    vdir = _variant_dir(job_id, variant)
    if not job or not (vdir / "layout.json").exists():
        return jsonify({"error": "Chua co du lieu parse."}), 400
    if len(members) < 2:
        return jsonify({"error": "Chon it nhat 2 anh de gop."}), 400
    # id group on dinh theo tap thanh vien
    import hashlib
    gid = "G" + hashlib.md5(",".join(sorted(members)).encode()).hexdigest()[:8]
    groups = _load_groups(vdir)
    # bo cac group cu co thanh vien trung (tranh 1 layer thuoc 2 group)
    mset = set(members)
    groups = [g for g in groups if not (set(g["members"]) & mset)]
    groups.append({"id": gid, "name": name, "members": members})
    _save_groups(vdir, groups)
    try:
        man = _build_manifest(job_id)
        job["manifest"] = man
        return jsonify({"manifest": man, "group_id": gid})
    except Exception as e:
        import traceback
        return jsonify({"error": f"{e}", "trace": traceback.format_exc()[-800:]}), 500


@app.route("/ungroup", methods=["POST"])
def ungroup():
    """Tach 1 group -> tra lai cac layer thanh vien."""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    variant = data.get("variant", "desktop")
    gid = data.get("group_id")
    job = _ensure_job(job_id)
    vdir = _variant_dir(job_id, variant)
    if not job or not (vdir / "layout.json").exists():
        return jsonify({"error": "Chua co du lieu parse."}), 400
    groups = [g for g in _load_groups(vdir) if g["id"] != gid]
    _save_groups(vdir, groups)
    asset = vdir / "assets" / f"{gid}.webp"    # don asset gop cu
    try:
        asset.unlink()
    except OSError:
        pass
    man = _build_manifest(job_id)
    job["manifest"] = man
    return jsonify({"manifest": man})


@app.route("/edit", methods=["POST"])
def edit():
    """Luu chinh sua per-layer (bbox/z/text/link/alt). Merge vao edits.json.
    Fire-and-forget tu frontend; export/preview doc lai qua _effective_layout."""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    variant = data.get("variant", "desktop")
    job = _ensure_job(job_id)
    vdir = _variant_dir(job_id, variant)
    if not job or not (vdir / "layout.json").exists():
        return jsonify({"error": "Chua co du lieu parse."}), 400
    patch = data.get("patch") or {}       # {layerId: {bbox?/z?/text?/link?/alt?}}
    with _EDIT_LOCK:                       # tuan tu hoa read-modify-write edits.json
        edits = _load_edits(vdir)
        for lid, p in (patch.items() if isinstance(patch, dict) else []):
            if not isinstance(p, dict):
                continue
            cur = edits.get(lid) or {}
            for k, v in p.items():
                if k in ("bbox", "text", "link") and isinstance(v, dict):
                    cur[k] = {**(cur.get(k) or {}), **v}   # merge sau (giu key cu)
                elif v is None:
                    cur.pop(k, None)          # gui null -> xoa override key do
                else:
                    cur[k] = v
            if cur:
                edits[lid] = cur
            else:
                edits.pop(lid, None)
        _save_edits(vdir, edits)
    return jsonify({"ok": True})


@app.route("/preview", methods=["POST"])
def preview():
    """Xem thu: render slices theo lua chon anh hien tai (khong ZIP)."""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    job = _ensure_job(job_id)
    if not job or not (JOBS_DIR / job_id / "out" / "layout.json").exists():
        return jsonify({"error": "Chua co du lieu parse. Hay phan tich lai."}), 400

    def _flag(v):
        return v in (True, 1, "1", "true", "on", "yes")

    swiper = _flag(data.get("swiper"))
    disabled_d = data.get("disabled_desktop") or []
    disabled_m = data.get("disabled_mobile") or []
    threading.Thread(target=_run_preview,
                     args=(job_id, swiper, disabled_d, disabled_m), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    job = _ensure_job(job_id)
    if not job:
        return jsonify({"error": "khong tim thay job"}), 404
    return jsonify(job)


@app.route("/result/<job_id>/<path:filename>")
def result(job_id, filename):
    d = JOBS_DIR / job_id / "out"
    if not d.exists():
        abort(404)
    return send_from_directory(d, filename)


@app.route("/download/<job_id>")
def download(job_id):
    z = JOBS_DIR / job_id / "result.zip"
    if not z.exists():
        abort(404)
    return send_file(z, as_attachment=True,
                     download_name=f"psd2html-{jobs.get(job_id, {}).get('format', 'out')}.zip")


@app.route("/")
def index():
    return render_template("index.html")


def main():
    # Host/port cau hinh qua bien moi truong:
    #   PSD2HTML_HOST=0.0.0.0  -> may khac cung mang LAN truy cap duoc (qua IP may nay)
    #   PSD2HTML_PORT=5000
    host = _os.environ.get("PSD2HTML_HOST", "127.0.0.1")
    port = int(_os.environ.get("PSD2HTML_PORT", "5000"))
    print(f"psd2html web UI: dang chay tren {host}:{port}")
    if host == "0.0.0.0":
        print("  -> May khac cung mang mo: http://<IP-may-nay>:%d" % port)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
