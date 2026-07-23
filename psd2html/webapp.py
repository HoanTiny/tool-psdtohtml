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

from flask import Flask, request, jsonify, send_from_directory, send_file, abort
from werkzeug.utils import secure_filename

from .parser import parse_psd
from .merge import parse_and_merge
from .render_slices import render as render_slices
from .export_web import export as export_web

app = Flask(__name__)
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
    return INDEX_HTML


INDEX_HTML = """<!doctype html>
<html lang="vi"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>psd2html — Chuyển PSD sang web</title>
<style>
  :root{--bg:#0b1120;--bg2:#0f1a30;--card:#141f38;--card2:#1a2744;--line:#2a3a5c;
    --txt:#e8eef8;--muted:#93a4c4;--brand:#3b82f6;--brand2:#60a5fa;--ok:#22c55e;
    --sky:#38bdf8;--danger:#f87171;--grp:#22a06b;--r:12px;--shadow:0 8px 30px rgba(0,0,0,.35)}
  *{box-sizing:border-box}
  body{margin:0;font-family:'Segoe UI',system-ui,-apple-system,Arial,sans-serif;line-height:1.45;
    background:radial-gradient(1100px 560px at 82% -12%,#13284d 0,transparent 60%),var(--bg);color:var(--txt)}
  .wrap{max-width:1440px;margin:0 auto;padding:22px}
  h1{font-size:22px;margin:0;display:flex;align-items:center;gap:9px}
  .sub{color:var(--muted);margin:6px 0 16px;font-size:13.5px}
  /* thanh buoc */
  .steps{display:flex;gap:8px;align-items:center;margin:12px 0 20px;flex-wrap:wrap}
  .steps .st{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px;font-weight:600}
  .steps .st .n{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;background:var(--card);border:1px solid var(--line);font-size:12px}
  .steps .st.on{color:var(--txt)} .steps .st.on .n{background:var(--brand);border-color:var(--brand);color:#fff}
  .steps .st.done .n{background:var(--ok);border-color:var(--ok);color:#04220f}
  .steps .sep{flex:0 0 24px;height:2px;background:var(--line);border-radius:2px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  @media(max-width:700px){.grid{grid-template-columns:1fr}}
  .drop{border:2px dashed var(--line);border-radius:var(--r);padding:28px;text-align:center;cursor:pointer;background:var(--card);transition:.15s}
  .drop:hover,.drop.over{border-color:var(--brand);background:var(--card2);transform:translateY(-1px)}
  .drop .big{font-size:15px}.drop .fname{color:#5eead4;margin-top:8px;font-size:13px;word-break:break-all}
  .drop small{color:var(--muted)}
  .row{display:flex;gap:14px;align-items:center;margin:16px 0;flex-wrap:wrap}
  .lbl{color:var(--muted);font-size:13px;font-weight:600}
  .fmt{display:flex;gap:8px;flex-wrap:wrap}
  .fmt label{border:1px solid var(--line);border-radius:9px;padding:8px 13px;cursor:pointer;background:var(--card);font-size:13.5px;transition:.12s;display:inline-flex;align-items:center}
  .fmt label:hover{border-color:var(--brand2)}
  .fmt input{margin-right:7px}
  .fmt input:checked+span{color:#bfdbfe;font-weight:600}
  .fmt label:has(input:checked){border-color:var(--brand);background:var(--card2)}
  button{background:linear-gradient(180deg,var(--brand2),var(--brand));color:#fff;border:0;border-radius:10px;padding:11px 22px;font-size:14.5px;font-weight:600;cursor:pointer;transition:.12s;box-shadow:0 2px 8px rgba(37,99,235,.3)}
  button:hover{filter:brightness(1.07)} button:active{transform:translateY(1px)}
  button:disabled{opacity:.5;cursor:default;box-shadow:none}
  button.ghost{background:var(--card2);box-shadow:none;border:1px solid var(--line);color:var(--txt)}
  button.ghost:hover{border-color:var(--brand2)}
  button.sm{padding:6px 12px;font-size:12.5px;border-radius:8px}
  .panel{margin-top:18px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;display:none;box-shadow:var(--shadow)}
  .panel.show{display:block}
  .bar{height:8px;background:#22304d;border-radius:6px;overflow:hidden;margin:10px 0}
  .bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--brand),var(--sky));width:40%;animation:pulse 1.2s infinite}
  @keyframes pulse{0%{opacity:.5}50%{opacity:1}100%{opacity:.5}}
  iframe{width:100%;height:600px;border:1px solid var(--line);border-radius:10px;background:#fff;margin-top:12px}
  a.dl{display:inline-block;background:linear-gradient(180deg,#34d399,#16a34a);color:#04220f;padding:11px 20px;border-radius:10px;text-decoration:none;margin-top:12px;font-weight:700}
  .err{color:#fecaca;white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12px;background:#2a1418;border:1px solid #7f1d1d;border-radius:8px;padding:8px;margin-top:8px}
  .files{color:var(--muted);font-size:12px;font-family:ui-monospace,monospace;max-height:170px;overflow:auto;margin-top:10px;background:var(--bg2);border-radius:8px;padding:8px}
  /* thanh cong cu editor */
  .etool{position:sticky;top:0;z-index:40;display:flex;align-items:center;gap:10px;flex-wrap:wrap;
    background:rgba(15,26,48,.97);backdrop-filter:blur(6px);border:1px solid var(--line);border-radius:12px;padding:9px 12px;margin:0 0 14px}
  .etool .title{font-size:15px;font-weight:700;display:flex;align-items:center;gap:7px}
  .etool .spacer{flex:1}
  .chip{font-size:12.5px;color:var(--muted);background:var(--bg2);border:1px solid var(--line);border-radius:20px;padding:5px 11px;white-space:nowrap}
  .tabs{display:inline-flex;background:var(--bg2);border:1px solid var(--line);border-radius:9px;overflow:hidden}
  .tabs button{padding:7px 13px;font-size:13px;background:transparent;box-shadow:none;border:0;border-radius:0;color:var(--muted);font-weight:600}
  .tabs button.active{background:var(--brand);color:#fff}
  #grpMode{background:var(--card2);box-shadow:none;border:1px solid var(--line);color:var(--txt);padding:7px 13px;font-size:13px;border-radius:9px}
  #grpMode.active{background:var(--grp);color:#eafff3;border-color:var(--grp)}
  /* editor split */
  .ed{display:grid;grid-template-columns:minmax(440px,1.35fr) minmax(300px,1fr);gap:18px}
  @media(max-width:860px){.ed{grid-template-columns:1fr}}
  .prevBox{position:sticky;top:66px;align-self:start;background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:12px;max-height:90vh;overflow:auto}
  .prevBox .cap{font-size:11px;color:var(--muted);text-align:center;margin-bottom:8px}
  .pvtop{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:11px;color:var(--muted);margin-bottom:8px}
  .zoom{display:inline-flex;align-items:center;gap:2px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:2px}
  .zoom button{background:transparent;box-shadow:none;border:0;color:var(--txt);font-size:15px;font-weight:700;padding:2px 9px;border-radius:6px;line-height:1}
  .zoom button:hover{background:var(--card2)}
  .zoom b{font-size:11px;min-width:38px;text-align:center;color:var(--muted)}
  .secNav{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:9px}
  .secNav button{padding:5px 10px;font-size:12px;background:var(--bg2);border:1px solid var(--line);color:var(--muted);box-shadow:none;border-radius:7px;font-weight:600}
  .secNav button:hover{border-color:var(--brand2)}
  .secNav button.active{background:var(--brand);color:#fff;border-color:var(--brand)}
  .stageClip{overflow:hidden;border-radius:6px;margin:0 auto}
  .stage{position:relative;margin:0 auto;touch-action:none;border-radius:6px;background-color:#fff;
    background-image:linear-gradient(45deg,#dbe3ef 25%,transparent 25%,transparent 75%,#dbe3ef 75%),linear-gradient(45deg,#dbe3ef 25%,#fff 25%,#fff 75%,#dbe3ef 75%);background-size:18px 18px;background-position:0 0,9px 9px}
  .stage img,.stage .lyr{position:absolute;display:block}
  .stage .lyr.off,.stage img.off{display:none}
  .stage .txt{overflow:hidden}
  .stage .lyr.sel{outline:2px solid var(--sky);z-index:50}
  /* DEMO hieu ung ngay trong editor (khop voi FX_CSS khi xuat) */
  @keyframes fxLaluot{from{-webkit-mask-position:150% 0;mask-position:150% 0}to{-webkit-mask-position:0% 0;mask-position:0% 0}}
  @keyframes fxGlow{0%,100%{filter:drop-shadow(0 0 5px rgba(255,255,220,.8)) drop-shadow(0 0 15px rgba(255,215,0,.5))}50%{filter:drop-shadow(0 0 8px #fff) drop-shadow(0 0 25px rgba(255,215,0,.85)) drop-shadow(0 0 45px rgba(255,160,0,.5))}}
  @keyframes fxFloat{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-3%) scale(1.03)}}
  .stage .fx-glow{animation:fxGlow 3s ease-in-out infinite}
  .stage .fx-float{animation:fxFloat 2s ease-in-out infinite}
  .stage .lyr-fxshine{position:absolute;pointer-events:none;filter:brightness(2);
    -webkit-mask-image:-webkit-linear-gradient(45deg,rgba(255,255,255,0) 40%,#fff 50%,rgba(255,255,255,0) 60%);
    mask-image:-webkit-linear-gradient(45deg,rgba(255,255,255,0) 40%,#fff 50%,rgba(255,255,255,0) 60%);
    -webkit-mask-size:300% 200%;mask-size:300% 200%;-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;
    animation:fxLaluot 2.5s linear infinite 1s;z-index:40}
  .secmark{position:absolute;left:0;right:0;border-top:2px dashed rgba(56,189,248,.55);pointer-events:none}
  .secmark span{position:absolute;top:2px;left:4px;font-size:10px;background:rgba(56,189,248,.9);color:#04212e;font-weight:700;padding:1px 6px;border-radius:0 0 6px 0}
  .selov{position:absolute;border:1.5px solid var(--sky);box-shadow:0 0 0 9999px rgba(2,6,20,.04);z-index:60}
  .selov .mv{position:absolute;inset:0;cursor:move;touch-action:none}
  .selov .hnd{position:absolute;width:11px;height:11px;background:var(--sky);border:1px solid #fff;border-radius:2px;touch-action:none}
  .selov .hnd.nw{left:-6px;top:-6px;cursor:nwse-resize}.selov .hnd.ne{right:-6px;top:-6px;cursor:nesw-resize}
  .selov .hnd.sw{left:-6px;bottom:-6px;cursor:nesw-resize}.selov .hnd.se{right:-6px;bottom:-6px;cursor:nwse-resize}
  .selov .hnd.n{left:50%;margin-left:-6px;top:-6px;cursor:ns-resize}.selov .hnd.s{left:50%;margin-left:-6px;bottom:-6px;cursor:ns-resize}
  .selov .hnd.w{top:50%;margin-top:-6px;left:-6px;cursor:ew-resize}.selov .hnd.e{top:50%;margin-top:-6px;right:-6px;cursor:ew-resize}
  /* danh sach layer */
  .listhead{display:flex;align-items:center;gap:8px;margin-bottom:10px}
  .search{flex:1;display:flex;align-items:center;gap:7px;background:var(--bg2);border:1px solid var(--line);border-radius:9px;padding:7px 11px}
  .search input{flex:1;background:transparent;border:0;color:var(--txt);font-size:13px;outline:none}
  .sec{border:1px solid var(--line);border-radius:11px;margin-bottom:10px;overflow:hidden;background:var(--card)}
  .sec>h4{margin:0;padding:10px 12px;background:var(--card2);font-size:13.5px;display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none}
  .sec>h4 .cnt{color:var(--muted);font-weight:400;font-size:12px}
  .sec>h4 .toggle{margin-left:auto;font-size:12px;color:#bfdbfe;background:var(--bg2);border:1px solid var(--line);padding:4px 9px;border-radius:7px}
  .sec>h4 .toggle:hover{border-color:var(--brand2)}
  .layers{padding:8px;display:grid;grid-template-columns:1fr 1fr;gap:7px}
  @media(max-width:560px){.layers{grid-template-columns:1fr}}
  .item{display:flex;align-items:center;gap:8px;padding:6px;border:1px solid var(--line);border-radius:9px;background:var(--bg2);cursor:pointer;transition:.1s}
  .item:hover{border-color:var(--brand2)}
  .item.off{opacity:.42}
  .item .th{width:46px;height:46px;object-fit:contain;background:#0e1830;border-radius:6px;flex:0 0 46px}
  .item .nm{font-size:12px;line-height:1.28;word-break:break-word;flex:1;min-width:0}
  .item .badge{font-size:9px;padding:1px 5px;border-radius:4px;background:#33507e;color:#dbeafe;margin-left:4px}
  .item input{flex:0 0 auto;width:16px;height:16px}
  .item.gsel{outline:2px solid var(--brand);background:#12233f}
  .item.grp{background:#0e2119;border-color:#1f7a4d}
  .item .gbadge{font-size:9px;padding:1px 5px;border-radius:4px;background:var(--grp);color:#d1fae5;margin-left:4px}
  .item .untie{margin-left:auto;font-size:11px;color:#fca5a5;background:#2a1418;border:1px solid #7f1d1d;border-radius:6px;padding:2px 7px;cursor:pointer;flex:0 0 auto}
  .item.sel{outline:2px solid var(--sky)}
  .gmode .item{cursor:copy}
  /* cây layer kiểu Photoshop */
  .tree{display:flex;flex-direction:column;gap:1px}
  .tree .item{border:0;background:transparent;border-radius:7px;padding:4px 6px;margin:0;gap:7px}
  .tree .item:hover{background:var(--card2)}
  .tree .item .th{width:30px;height:30px;flex:0 0 30px}
  .tree .item.gsel{outline:2px solid var(--brand);background:#12233f}
  .tree .item.grp{background:#0e2119}
  .tree .item.sel{outline:2px solid var(--sky)}
  .frow{display:flex;align-items:center;gap:7px;padding:5px 6px;border-radius:7px;cursor:pointer;user-select:none}
  .frow:hover{background:var(--card2)}
  .frow .tw{width:14px;flex:0 0 14px;text-align:center;color:var(--muted);font-size:11px}
  .frow .fico{flex:0 0 auto}
  .frow .fname{flex:1;min-width:0;font-weight:600;word-break:break-word;font-size:12.5px}
  .frow .fcnt{color:var(--muted);font-size:11px;flex:0 0 auto}
  .frow .fgroup{flex:0 0 auto;font-size:10px;color:#a7f3d0;background:#0e2119;border:1px solid #1f7a4d;border-radius:6px;padding:2px 7px}
  .frow .fgroup:hover{background:#123726}
  .eye{cursor:pointer;font-size:13px;flex:0 0 auto;line-height:1}
  .eye.off{opacity:.5;filter:grayscale(1)}
  .sug-chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;background:#12233f;border:1px solid #2f4a75;color:#bcd3f5;border-radius:20px;padding:6px 12px;margin:0 6px 6px 0;cursor:pointer}
  .sug-chip:hover{background:#17335c}
  .sug-chip.psd{background:#0e2119;border-color:#1f7a4d;color:#a7f3d0}
  .sug-chip.psd:hover{background:#123726}
  .hint{color:var(--muted);font-size:13px;margin:0 0 12px;background:var(--bg2);border-left:3px solid var(--brand);border-radius:0 8px 8px 0;padding:9px 12px}
  /* inspector (layer dang chon) */
  .selPanel{background:linear-gradient(180deg,#0d2136,#0b1b2e);border:1px solid var(--sky);border-radius:12px;padding:12px 14px;margin-bottom:14px}
  .selPanel .t{font-size:14px;font-weight:700;color:#bae6fd;word-break:break-word;display:flex;align-items:center;gap:6px}
  .selPanel .grpttl{font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);margin:12px 0 5px;font-weight:700}
  .selPanel .r{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin-top:6px}
  .selPanel input,.selPanel select,.selPanel textarea{padding:6px 8px;background:#0a1526;border:1px solid var(--line);border-radius:7px;color:#e8eeff;font-size:12.5px}
  .selPanel .num{width:66px}
  .selPanel button{padding:6px 11px;font-size:12.5px;border-radius:8px}
  /* tuy chon xuat (accordion) */
  .acc{border:1px solid var(--line);border-radius:12px;margin-top:16px;overflow:hidden;background:var(--card)}
  .acc>summary{padding:13px 15px;background:var(--card2);font-weight:700;font-size:14px;cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px}
  .acc>summary::-webkit-details-marker{display:none}
  .acc>summary .arw{margin-left:auto;transition:.2s;color:var(--muted)}
  .acc[open]>summary .arw{transform:rotate(90deg)}
  .acc .body{padding:6px 15px 14px}
  .actionbar{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px;padding-top:14px;border-top:1px solid var(--line)}
  kbd{background:var(--bg2);border:1px solid var(--line);border-bottom-width:2px;border-radius:5px;padding:1px 6px;font-size:11px;font-family:inherit}
</style></head><body>
<div class="wrap">
  <h1>&#127912; psd2html <span style="font-size:13px;font-weight:400;color:var(--muted)">— Chuyển PSD sang web</span></h1>
  <p class="sub">Kéo file PSD vào &rarr; <b>Phân tích</b> &rarr; <b>chỉnh sửa &amp; chọn ảnh</b> &rarr; <b>Xuất web</b>.
    Nhiều file = mỗi file một section, ghép dọc theo <b>thứ tự tên file</b> (vd: <code>01-hero.psd</code>, <code>02-tinh-nang.psd</code>).</p>

  <div class="steps">
    <span class="st on" id="stp1"><span class="n">1</span> Tải PSD</span>
    <span class="sep"></span>
    <span class="st" id="stp2"><span class="n">2</span> Chỉnh sửa</span>
    <span class="sep"></span>
    <span class="st" id="stp3"><span class="n">3</span> Xuất web</span>
  </div>

  <!-- BƯỚC 1: tải PSD -->
  <div id="step1">
    <div class="grid">
      <div class="drop" id="dropD">
        <div class="big">&#128196; Kéo thả PSD <b>Desktop</b></div>
        <small>1 file, hoặc nhiều file (mỗi file một section)</small>
        <div class="fname" id="nameD"></div>
        <input type="file" id="fileD" accept=".psd" multiple hidden>
      </div>
      <div class="drop" id="dropM">
        <div class="big">&#128241; Kéo thả PSD <b>Mobile</b></div>
        <small>tuỳ chọn — 1 hoặc nhiều file</small>
        <div class="fname" id="nameM"></div>
        <input type="file" id="fileM" accept=".psd" multiple hidden>
      </div>
    </div>
    <div class="drop" id="dropP" style="margin-top:14px">
      <div class="big">&#129525; Kéo thả PSD <b>Popup</b></div>
      <small>tuỳ chọn — <b>mỗi file = 1 popup</b> (thể lệ, nạp đầu, sự kiện…). Gán "click mở popup" ở bước chỉnh sửa.</small>
      <div class="fname" id="nameP"></div>
      <input type="file" id="fileP" accept=".psd" multiple hidden>
    </div>
    <div class="row">
      <span class="lbl">Chất lượng ảnh:</span>
      <div class="fmt">
        <label title="WebP nhẹ, cân bằng — khuyên dùng"><input type="radio" name="quality" value="balanced" checked><span>Cân bằng (WebP)</span></label>
        <label title="WebP nét hơn, nặng hơn chút"><input type="radio" name="quality" value="high"><span>Nét cao (WebP)</span></label>
        <label title="Ảnh gốc PNG — nét nhất, nặng nhất"><input type="radio" name="quality" value="png"><span>Ảnh gốc (PNG)</span></label>
      </div>
    </div>
    <div class="row">
      <button id="goParse">&#128269; Phân tích PSD</button>
      <small style="color:var(--muted)">PSD lớn có thể mất 1–3 phút để đọc.</small>
    </div>
  </div>

  <!-- tiến trình phân tích -->
  <div class="panel" id="parsePanel">
    <b id="parseStep">Đang xử lý…</b>
    <div class="bar"><i></i></div>
    <div id="parseErr" class="err"></div>
  </div>

  <!-- BƯỚC 2: TRÌNH CHỈNH SỬA -->
  <div class="panel" id="editor">
    <div class="etool">
      <span class="title">&#9986;&#65039; Trình chỉnh sửa</span>
      <span class="tabs" id="tabs"></span>
      <button id="grpMode" title="Gộp nhiều ảnh thành một (như group trong PSD)">&#129513; Gộp ảnh</button>
      <span class="spacer"></span>
      <span class="chip" id="selInfo"></span>
      <button class="ghost sm" id="goReview" title="Xem trước bản HTML thật theo ảnh đang chọn">&#128065; Xem thử</button>
      <button class="sm" id="goExport">&#128190; Xuất web</button>
    </div>
    <p class="hint" id="edHint">Bấm vào ảnh (trên khung xem trước hoặc trong danh sách) để <b>chọn</b> &rarr; kéo để di chuyển,
      kéo góc để đổi kích thước, phím <kbd>← ↑ ↓ →</kbd> để nhích. Bỏ tích = không xuất ảnh đó.</p>

    <!-- Tuỳ chọn xuất (đưa lên đầu để chọn định dạng trước) -->
    <details class="acc" id="exportAcc" style="margin-top:0;margin-bottom:14px">
      <summary>&#9881;&#65039; Tuỳ chọn xuất web <span style="color:var(--muted);font-weight:400;font-size:12.5px">— định dạng, ngôn ngữ, swiper…</span> <span class="arw">&#9656;</span></summary>
      <div class="body">
        <div class="row" style="margin-top:10px">
          <span class="lbl">Định dạng:</span>
          <div class="fmt">
            <label title="HTML tĩnh — xem ngay, không cần cài đặt"><input type="radio" name="fmt" value="slices" checked><span>HTML (xem ngay)</span></label>
            <label title="Dự án React + Tailwind"><input type="radio" name="fmt" value="react"><span>React + Tailwind</span></label>
            <label title="Dự án Next.js"><input type="radio" name="fmt" value="next"><span>Next.js</span></label>
          </div>
        </div>
        <div class="row" id="langRow" style="display:none">
          <span class="lbl">Ngôn ngữ:</span>
          <div class="fmt">
            <label><input type="radio" name="lang" value="js" checked><span>JavaScript</span></label>
            <label><input type="radio" name="lang" value="ts"><span>TypeScript</span></label>
          </div>
        </div>
        <div class="row">
          <label class="fmt" style="cursor:pointer"><input type="checkbox" id="swiper" style="margin-right:6px">
            <span>Full-page (swiper): lăn/vuốt snap từng section</span></label>
        </div>
        <div id="reactOpts" style="display:none">
          <div class="lbl" style="margin:6px 0 8px">Tuỳ chọn React/Next (bám prod):</div>
          <div class="fmt" style="flex-direction:column;gap:9px;align-items:flex-start">
            <label style="cursor:pointer"><input type="checkbox" id="swiper_lib" style="margin-right:6px"><span>Dùng Swiper.js thật (hiệu ứng fade như prod)</span></label>
            <label style="cursor:pointer"><input type="checkbox" id="env_config" style="margin-right:6px"><span>Cấu hình link/API bằng <code>.env</code> (VITE_APP_*)</span></label>
            <label style="cursor:pointer"><input type="checkbox" id="nav_menu" style="margin-right:6px"><span>Nav chữ + slideTo (cấu hình được)</span></label>
            <label style="cursor:pointer"><input type="checkbox" id="popups" style="margin-right:6px"><span>Popup mẫu (đăng nhập / thể lệ / lịch sử / nạp đầu)</span></label>
            <label style="cursor:pointer"><input type="checkbox" id="fx" style="margin-right:6px"><span>&#10024; Hiệu ứng chữ &amp; nút (nút lướt sáng + hover, quầng vàng; tiêu đề trôi nhẹ + phát sáng)</span></label>
            <label style="cursor:pointer"><input type="checkbox" id="fx_reveal" style="margin-right:6px"><span>&#127916; Hiệu ứng xuất hiện khi cuộn (section nảy/zoom vào khi cuộn tới)</span></label>
            <label style="cursor:pointer"><input type="checkbox" id="fluid" style="margin-right:6px"><span>&#128241; Mobile co giãn thật (section xếp dọc, lưới reflow 4&rarr;2&rarr;1 cột) — không dùng khi đã có PSD mobile</span></label>
            <label style="cursor:pointer"><input type="checkbox" id="ai_enhance" style="margin-right:6px"><span>&#10024; AI prod-hoá (chữ thật + hover) — cần API key trong <code>.env</code></span></label>
          </div>
        </div>
      </div>
    </details>

    <div id="grpBar" style="display:none">
      <div class="selPanel" style="border-color:var(--grp);margin-bottom:12px">
        <div class="r" style="margin-top:0">
          <b style="color:#7ee2b8" id="grpCount">0 ảnh đã chọn</b>
          <input id="grpName" placeholder="Tên nhóm (vd: Nền, Nhân vật)" style="flex:1;min-width:150px">
          <button class="sm" id="grpDo">&#129513; Gộp thành 1 ảnh</button>
          <button class="ghost sm" id="grpClear">Bỏ chọn</button>
        </div>
      </div>
    </div>
    <div id="grpSug" style="margin-bottom:12px"></div>
    <div class="selPanel" id="selPanel" style="display:none"></div>

    <div class="ed">
      <div class="prevBox">
        <div class="secNav" id="secNav"></div>
        <div class="pvtop">
          <span>Nhấp để chọn &middot; kéo để chỉnh</span>
          <span class="zoom"><button id="zOut" title="Thu nhỏ">&minus;</button><b id="zLbl">100%</b><button id="zIn" title="Phóng to">+</button></span>
        </div>
        <div class="stageClip" id="stageClip"><div class="stage" id="stage"></div></div>
      </div>
      <div>
        <div class="listhead">
          <div class="search">&#128269;<input id="layerSearch" placeholder="Tìm ảnh theo tên…" autocomplete="off"></div>
        </div>
        <div id="secList"></div>
      </div>
    </div>

    <div class="actionbar">
      <button class="ghost" id="restart">&#8617; Phân tích file khác</button>
      <span style="flex:1"></span>
      <span class="chip">💡 Chỉnh xong bấm <b>Xuất web</b> (góc trên)</span>
    </div>

    <div id="reviewBox" style="display:none;margin-top:6px">
      <div class="row" style="margin:0 0 6px">
        <b id="reviewStep" style="font-size:14px">Đang dựng bản xem thử…</b>
        <span style="color:var(--muted);font-size:12px">Bản HTML thật theo ảnh đang chọn (chưa tính responsive của React/Next).</span>
        <button class="ghost sm" id="reviewOpen" style="margin-left:auto;display:none">&#8599; Mở tab mới</button>
      </div>
      <div class="bar" id="reviewBar"><i></i></div>
      <iframe id="reviewFrame" style="display:none;height:640px"></iframe>
      <div id="reviewErr" class="err"></div>
    </div>
  </div>

  <!-- tiến trình xuất + kết quả -->
  <div class="panel" id="exportPanel">
    <div id="exProgress">
      <b id="exStep">Đang xuất…</b>
      <div class="bar"><i></i></div>
    </div>
    <div id="result" style="display:none"></div>
  </div>
</div>
<script>
let filesD=[], filesM=[], filesP=[];
let JOB=null, MAN=null, curTab='desktop';
const disabled={desktop:new Set(), mobile:new Set()};
let groupMode=false;
const groupSel={desktop:new Set(), mobile:new Set()};
const collapsed={desktop:new Set(), mobile:new Set()};   // folder dang gap trong cay layer
let sel=null, curScale=1;   // layer dang chon (thao tac canvas) + he so scale preview
let layerQuery="";          // tu khoa tim trong danh sach layer
let curSec=-1;              // section dang xem rieng (-1 = tat ca)
let previewZoom=1;          // he so phong khung xem truoc (1 = vua be rong cot)
function setStep(n){ [1,2,3].forEach(i=>{ const e=document.getElementById("stp"+i);
  e.classList.toggle("on", i===n); e.classList.toggle("done", i<n); }); }

function showList(nameEl, arr, unit){
  unit=unit||"section";
  if(!arr.length){ nameEl.innerHTML=""; return; }
  const sorted=[...arr].sort((a,b)=>a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
  if(sorted.length===1){ nameEl.textContent="\\u2713 "+sorted[0].name; return; }
  nameEl.innerHTML="\\u2713 "+sorted.length+" "+unit+":<br>"
    + sorted.map((f,i)=>(i+1)+". "+f.name).join("<br>");
}
function setupDrop(dropId, inputId, nameId, get, set, unit){
  const drop=document.getElementById(dropId), input=document.getElementById(inputId), name=document.getElementById(nameId);
  drop.onclick=()=>input.click();
  input.onchange=()=>{ if(input.files.length){ set([...input.files]); showList(name,get(),unit); } };
  ["dragover","dragenter"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("over")}));
  ["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("over")}));
  drop.addEventListener("drop",ev=>{ const fs=[...ev.dataTransfer.files].filter(f=>/\\.psd$/i.test(f.name));
    if(fs.length){ set(fs); showList(name,get(),unit); }});
}
setupDrop("dropD","fileD","nameD",()=>filesD,a=>filesD=a,"section");
setupDrop("dropM","fileM","nameM",()=>filesM,a=>filesM=a,"section");
setupDrop("dropP","fileP","nameP",()=>filesP,a=>filesP=a,"popup");

document.querySelectorAll('input[name=fmt]').forEach(r=>r.addEventListener('change',()=>{
  const f=document.querySelector('input[name=fmt]:checked').value;
  const isRN=(f==='react'||f==='next');
  document.getElementById('langRow').style.display=isRN?'flex':'none';
  document.getElementById('reactOpts').style.display=isRN?'block':'none';
  if(isRN) document.getElementById('exportAcc').open=true;   // mo tuy chon de thay
}));
// tim kiem layer trong danh sach
document.getElementById('layerSearch').addEventListener('input',function(e){
  layerQuery=(e.target.value||'').trim().toLowerCase(); render(); });
// zoom khung xem truoc
document.getElementById('zIn').onclick=()=>{ previewZoom=Math.min(3, previewZoom+0.25); render(); };
document.getElementById('zOut').onclick=()=>{ previewZoom=Math.max(0.5, previewZoom-0.25); render(); };
// doi be rong cua so -> ve lai khung cho vua cot
let _rzT=null; window.addEventListener('resize',()=>{
  if(!document.getElementById('editor').classList.contains('show')) return;
  clearTimeout(_rzT); _rzT=setTimeout(render,150); });

const parsePanel=document.getElementById("parsePanel"), parseStep=document.getElementById("parseStep"),
      parseErr=document.getElementById("parseErr"), editor=document.getElementById("editor"),
      exportPanel=document.getElementById("exportPanel"), exProgress=document.getElementById("exProgress"),
      exStep=document.getElementById("exStep"), result=document.getElementById("result"),
      goParse=document.getElementById("goParse"), goExport=document.getElementById("goExport");

// ---- BUOC 1: parse ----
goParse.onclick=async()=>{
  if(!filesD.length){ alert("Hãy chọn file PSD Desktop trước"); return; }
  const fd=new FormData();
  filesD.forEach(f=>fd.append("desktop",f));
  filesM.forEach(f=>fd.append("mobile",f));
  filesP.forEach(f=>fd.append("popup",f));
  fd.append("quality",(document.querySelector('input[name=quality]:checked')||{}).value||'balanced');
  goParse.disabled=true; parsePanel.classList.add("show"); parseErr.textContent="";
  editor.classList.remove("show"); parseStep.textContent="Đang tải file lên…";
  let r;
  try{
    const resp=await fetch("/parse",{method:"POST",body:fd});
    const ct=resp.headers.get("content-type")||"";
    if(ct.includes("application/json")){ r=await resp.json(); }
    else{ const txt=await resp.text();
      parseStep.textContent="Loi "+resp.status+": "+(txt.replace(/<[^>]*>/g,"").trim().slice(0,200)||"server khong tra JSON");
      goParse.disabled=false; return; }
  }catch(e){ parseStep.textContent="Loi tai len: "+e; goParse.disabled=false; return; }
  if(r.error){ parseStep.textContent="Loi: "+r.error; goParse.disabled=false; return; }
  JOB=r.job_id; pollParse();
};

async function pollParse(){
  let s; try{ s=await (await fetch("/status/"+JOB)).json(); }
  catch(e){ setTimeout(pollParse,1500); return; }
  parseStep.textContent=s.step||"Đang xử lý…";
  if(s.status==="done" && s.manifest){ MAN=s.manifest; goParse.disabled=false;
    parsePanel.classList.remove("show"); openEditor(); return; }
  if(s.status==="error"){ parseErr.textContent=(s.error||"")+"\\n"+(s.trace||""); goParse.disabled=false; return; }
  setTimeout(pollParse,1500);
}

// ---- BUOC 2: editor ----
// State theo TAB (desktop/mobile/popup:<id>) -> tao Set moi cho moi tab khi mo editor.
function resetTabState(tabList){
  [disabled,groupSel,collapsed].forEach(o=>{
    Object.keys(o).forEach(k=>delete o[k]);
    tabList.forEach(t=>o[t]=new Set());
  });
}
// Danh sach popup dang co (dung cho tab + dropdown 'Mo popup')
function popupsList(){ return MAN&&MAN.popups?MAN.popups:[]; }
// Map anh bi tat theo tung popup: {pid:[layerIds]} de gui khi export
function disabledPopupMap(){ const m={}; popupsList().forEach(p=>{ const s=disabled['popup:'+p.id];
  if(s&&s.size) m[p.id]=[...s]; }); return m; }

function openEditor(){
  document.getElementById("step1").style.display="none";
  const tabList=[{tab:'desktop',label:'\\u{1F4BB} Desktop'}];
  if(MAN.mobile) tabList.push({tab:'mobile',label:'\\u{1F4F1} Mobile'});
  popupsList().forEach(p=>tabList.push({tab:'popup:'+p.id,label:'\\u{1F9E9} '+p.name}));
  resetTabState(tabList.map(t=>t.tab));
  groupMode=false; sel=null; curSec=-1; layerQuery=""; previewZoom=1; document.getElementById("grpMode").classList.remove("active");
  curTab='desktop';
  const tabs=document.getElementById("tabs");
  tabs.innerHTML="";
  if(tabList.length>1){
    tabList.forEach(({tab,label})=>{ const b=document.createElement("button");
      b.textContent=label; b.dataset.tab=tab; b.className=tab===curTab?'active':'';
      b.onclick=()=>{curTab=tab; groupSel[tab].clear(); sel=null; curSec=-1; render();}; tabs.appendChild(b); });
  }
  // Co PSD popup -> he popup dung tu PSD (auto bat khi xuat), bao cho user biet
  const popChk=document.getElementById('popups');
  if(popChk){
    const popLbl=popChk.parentElement.querySelector('span');
    if(popupsList().length){ popChk.checked=true; popChk.disabled=true;
      if(popLbl) popLbl.textContent='Popup từ PSD ('+popupsList().length+' popup) — bật sẵn theo file đã tải';
    }else{ popChk.disabled=false;
      if(popLbl) popLbl.textContent='Popup mẫu (đăng nhập / thể lệ / lịch sử / nạp đầu)';
    }
  }
  editor.classList.add("show"); setStep(2); render();
}

function variant(){
  if(curTab.indexOf('popup:')===0){ const pid=curTab.slice(6); return popupsList().find(p=>p.id===pid); }
  return MAN[curTab];
}

function render(){
  document.querySelectorAll('#tabs button').forEach(b=>b.className=(b.dataset.tab===curTab)?'active':'');
  const v=variant(), dis=disabled[curTab];
  if(sel && !v.layers.some(l=>l.id===sel)) sel=null;   // sel khong con -> bo
  v.layers.sort((a,b)=>(a.z||0)-(b.z||0));              // thu tu lop (z), stable
  // preview stage
  const stage=document.getElementById("stage");
  const box=document.querySelector('.prevBox');
  const avail=box?Math.max(280, box.clientWidth-26):380;   // be rong kha dung cua cot preview
  const fit=Math.min(1, avail/v.canvas.width);
  curScale=Math.min(1, fit*previewZoom);
  const scale=curScale;
  const zl=document.getElementById('zLbl'); if(zl) zl.textContent=Math.round(previewZoom*100)+'%';
  stage.style.width=(v.canvas.width*scale)+"px";
  stage.style.height=(v.canvas.height*scale)+"px";
  let html="";
  // DEMO hieu ung: map l.fx -> class demo trong preview (+ lop luot sang neu can)
  const FX_BASE={glow:'fx-glow',float:'fx-float','float-glow':'fx-float fx-glow','shine-glow':'fx-glow',btn:'fx-glow'};
  const FX_SHINE=new Set(['shine','shine-glow','btn']);
  v.layers.forEach(l=>{ const b=l.bbox, off=dis.has(l.id)?" off":"", ss=(sel===l.id)?" sel":"";
    const st='left:'+(b.x*scale)+'px;top:'+(b.y*scale)+'px;width:'+(b.width*scale)+'px;height:'+(b.height*scale)+'px';
    const fxc=(l.fx&&FX_BASE[l.fx])?(' '+FX_BASE[l.fx]):'';
    const td=l.textData;
    if(td && td.asText){   // chu that -> hien text ngay trong preview (WYSIWYG)
      html+='<div class="lyr txt'+off+ss+fxc+'" data-id="'+l.id+'" style="'+st
        +';display:flex;align-items:center;justify-content:center;text-align:center;overflow:hidden'
        +';font-weight:700;line-height:1.15;white-space:pre-wrap;font-size:'+((td.size||20)*scale)+'px;color:'+(td.color||'#fff')+'">'+esc(td.content||'')+'</div>';
    }else{
      html+='<img class="lyr'+off+ss+fxc+'" data-id="'+l.id+'" src="'+l.asset+'" loading="lazy" style="'+st+'">';
      if(!off && l.fx && FX_SHINE.has(l.fx))   // lop anh phu luot sang (demo)
        html+='<img class="lyr-fxshine" src="'+l.asset+'" style="'+st+'">';
    }
  });
  v.sections.forEach((s,i)=>{ if(i===0)return;
    html+='<div class="secmark" style="top:'+(s.y0*scale)+'px"><span>'+esc(s.name)+'</span></div>'; });
  stage.innerHTML=html;
  drawSel();
  // xem riêng 1 section: cắt khung theo chiều cao section + dịch stage lên
  const clip=document.getElementById("stageClip");
  clip.style.width=(v.canvas.width*scale)+"px";
  if(curSec>=0 && v.sections[curSec]){
    const sc=v.sections[curSec];
    clip.style.height=((sc.y1-sc.y0)*scale)+"px";
    stage.style.transform="translateY("+(-sc.y0*scale)+"px)";
  }else{
    clip.style.height=(v.canvas.height*scale)+"px";
    stage.style.transform="none";
  }
  renderSecNav();

  renderList();
  renderSug(); updGrpBar(); updInfo();
  if(sel && !groupMode) ensurePanel(); else document.getElementById("selPanel").style.display="none";
}

// ================= CÂY LAYER kiểu Photoshop (folder lồng nhau + ẩn/hiện) =================
function renderList(){
  const v=variant(), dis=disabled[curTab], gsel=groupSel[curTab], col=collapsed[curTab];
  const list=document.getElementById("secList"); list.innerHTML="";
  list.classList.toggle("gmode", groupMode);

  // Chế độ tìm kiếm: danh sách phẳng các ảnh khớp tên
  if(layerQuery){
    const wrap=document.createElement("div"); wrap.className="tree";
    v.layers.filter(l=>(l.name||'').toLowerCase().includes(layerQuery) && (curSec<0||l.section===curSec))
      .forEach(l=>wrap.appendChild(leafRow(l,0)));
    if(!wrap.children.length) wrap.innerHTML='<div class="hint" style="margin:0">Không tìm thấy ảnh nào.</div>';
    list.appendChild(wrap); return;
  }

  // Dựng cây theo folder PSD (parent -> con)
  const kids={};
  const add=(p,it)=>{ (kids[p||"__root"]=kids[p||"__root"]||[]).push(it); };
  (v.nodes||[]).forEach(g=>add(g.parent,{t:"g",n:g}));
  v.layers.forEach(l=>add(l.parent,{t:"l",n:l}));
  // sắp đúng thứ tự PSD: order lớn = lớp TRÊN (front) -> hiện trước; xen kẽ folder/layer đúng vị trí
  Object.keys(kids).forEach(k=>kids[k].sort((a,b)=>(b.n.order||0)-(a.n.order||0)));
  // gom id anh (là con-cháu) dưới 1 folder
  function leavesOf(gid){ let out=[]; (kids[gid]||[]).forEach(it=>{
    if(it.t==="g") out=out.concat(leavesOf(it.n.id)); else out.push(it.n); }); return out; }

  const wrap=document.createElement("div"); wrap.className="tree";
  (kids["__root"]||[]).forEach(it=>renderNode(it,wrap,0));
  list.appendChild(wrap);

  function renderNode(it,parentEl,depth){
    if(it.t==="l"){ const l=it.n;
      if(curSec>=0 && l.section!==curSec) return;
      parentEl.appendChild(leafRow(l,depth)); return; }
    // folder
    const g=it.n, leaves=leavesOf(g.id).filter(l=>curSec<0||l.section===curSec);
    if(!leaves.length) return;                        // ẩn folder rỗng / ngoài section
    const kept=leaves.filter(l=>!dis.has(l.id)).length;
    const open=!col.has(g.id);
    const row=document.createElement("div"); row.className="frow"; row.style.paddingLeft=(6+depth*15)+"px";
    row.innerHTML='<span class="tw">'+(open?'&#9662;':'&#9656;')+'</span>'
      +'<span class="eye'+(kept?'':' off')+'" title="Ẩn/hiện cả nhóm">'+(kept?'&#128065;':'&#128584;')+'</span>'
      +'<span class="fico">&#128193;</span><span class="fname">'+esc(g.name)+'</span>'
      +'<span class="fcnt">'+kept+'/'+leaves.length+'</span>'
      +(leaves.length>=2&&!groupMode?'<span class="fgroup" title="Gộp cả folder thành 1 ảnh">&#129513; gộp</span>':'');
    row.querySelector('.tw').onclick=(e)=>{ e.stopPropagation();
      if(col.has(g.id)) col.delete(g.id); else col.add(g.id); renderList(); };
    row.querySelector('.eye').onclick=(e)=>{ e.stopPropagation();
      const allOn=leaves.every(l=>!dis.has(l.id));
      leaves.forEach(l=>{ if(allOn) dis.add(l.id); else dis.delete(l.id); });
      applyVis(); renderList(); updInfo(); };
    const fg=row.querySelector('.fgroup'); if(fg) fg.onclick=(e)=>{ e.stopPropagation();
      doGroup(leaves.map(l=>l.id), g.name); };
    row.onclick=()=>{ if(col.has(g.id)) col.delete(g.id); else col.add(g.id); renderList(); };
    parentEl.appendChild(row);
    if(open){ const childBox=document.createElement("div");
      (kids[g.id]||[]).forEach(c=>renderNode(c,childBox,depth+1)); parentEl.appendChild(childBox); }
  }
}
function leafRow(l,depth){
  const dis=disabled[curTab], gsel=groupSel[curTab], on=!dis.has(l.id);
  const it=document.createElement("div"); it.dataset.id=l.id;
  it.className="item lrow"+(on?"":" off")+(l.group?" grp":"")+(gsel.has(l.id)?" gsel":"")+(sel===l.id?" sel":"");
  it.style.paddingLeft=(6+depth*15)+"px";
  it.innerHTML='<span class="eye'+(on?'':' off')+'" title="Ẩn/hiện ảnh">'+(on?'&#128065;':'&#128584;')+'</span>'
    +'<img class="th" src="'+l.asset+'" loading="lazy">'
    +'<span class="nm">'+esc(l.name)
      +(l.text?'<span class="badge">T</span>':'')
      +(l.group?'<span class="gbadge">gộp '+l.count+'</span>':'')+'</span>'
    +(l.group?'<span class="untie" title="Tách nhóm">&#9986; tách</span>':'');
  it.querySelector('.eye').onclick=(e)=>{ e.stopPropagation();
    if(dis.has(l.id)) dis.delete(l.id); else dis.add(l.id);
    const off=dis.has(l.id); it.classList.toggle("off",off);
    it.querySelector('.eye').classList.toggle("off",off);
    it.querySelector('.eye').innerHTML=off?'&#128584;':'&#128065;';
    const im=document.querySelector('#stage .lyr[data-id="'+cssq(l.id)+'"]'); if(im) im.classList.toggle("off",off);
    updInfo(); };
  const untie=it.querySelector('.untie');
  if(untie) untie.onclick=(e)=>{ e.stopPropagation(); doUngroup(l.id); };
  it.onclick=()=>{ if(groupMode){
      if(gsel.has(l.id)) gsel.delete(l.id); else gsel.add(l.id);
      it.classList.toggle("gsel", gsel.has(l.id)); updGrpBar(); return; }
    selectLayer(l.id, true); };
  return it;
}
// đồng bộ ẩn/hiện lên preview (sau khi bật/tắt cả folder)
function applyVis(){ const dis=disabled[curTab];
  document.querySelectorAll('#stage .lyr').forEach(im=>{
    im.classList.toggle('off', dis.has(im.dataset.id)); }); }
// goi y nhom gop (cung ten chuan hoa) + group hien co
function renderSug(){
  const box=document.getElementById("grpSug"); const v=variant();
  if(!groupMode){ box.innerHTML=""; return; }
  const secName=i=>(v.sections[i]||{}).name||('S'+(i+1));
  const pg=(v.psdGroups||[]);
  const sug=(v.suggestions||[]).filter(s=>s.members.length>=2);
  let h='';
  if(pg.length){
    h+='<div style="color:var(--muted);font-size:12px;margin-bottom:6px">&#128193; Group có sẵn trong PSD — bấm để gộp nguyên folder thành 1 ảnh:</div>';
    pg.forEach((g,i)=>{ h+='<span class="sug-chip psd" data-src="psd" data-i="'+i+'">&#128193; '+esc(g.name)
      +' &middot; '+g.n+' ảnh <span style="opacity:.6">('+esc(secName(g.section))+')</span></span>'; });
  }
  if(sug.length){
    h+='<div style="color:var(--muted);font-size:12px;margin:'+(pg.length?'9px':'0')+' 0 6px">&#129513; Gợi ý theo tên (ảnh trùng tên cùng section):</div>';
    sug.forEach((s,i)=>{ h+='<span class="sug-chip" data-src="name" data-i="'+i+'">&#129513; '+esc(s.name||'nhóm')
      +' &middot; '+s.members.length+' ảnh <span style="opacity:.6">('+esc(secName(s.section))+')</span></span>'; });
  }
  if(!h) h='<div style="color:var(--muted);font-size:12px">Không có group PSD / gợi ý sẵn. Bấm chọn ảnh trong danh sách rồi bấm "Gộp thành 1 ảnh".</div>';
  box.innerHTML=h;
  box.querySelectorAll('.sug-chip').forEach(c=>{ c.onclick=()=>{
    const g = c.dataset.src==='psd' ? v.psdGroups[+c.dataset.i] : sug[+c.dataset.i];
    if(g) doGroup(g.members, g.name); }; });
}
function updGrpBar(){
  const bar=document.getElementById("grpBar"); const gsel=groupSel[curTab];
  bar.style.display=groupMode?"flex":"none";
  document.getElementById("grpCount").textContent=gsel.size+" ảnh đã chọn";
}
function updInfo(){
  const v=variant(), dis=disabled[curTab], tot=v.layers.length, kept=tot-[...dis].filter(id=>v.layers.some(l=>l.id===id)).length;
  document.getElementById("selInfo").textContent="Giữ "+kept+"/"+tot+" ảnh";
}
function esc(s){ return (s==null?"":String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function cssq(s){ return (s||"").replace(/"/g,'\\\\"'); }
function renderSecNav(){
  const nav=document.getElementById("secNav"); const v=variant();
  if(!v.sections || v.sections.length<=1){ nav.innerHTML=""; return; }
  let h='<button data-s="-1"'+(curSec<0?' class="active"':'')+'>&#128196; Tất cả</button>';
  v.sections.forEach((s,i)=>{ h+='<button data-s="'+i+'"'+(curSec===i?' class="active"':'')
    +'>'+(i+1)+'. '+esc(s.name||('Section '+(i+1)))+'</button>'; });
  nav.innerHTML=h;
  nav.querySelectorAll('button').forEach(b=>b.onclick=()=>{ curSec=+b.dataset.s; render(); });
}

// ================= THAO TAC CANVAS: chon / keo / resize / z-order / nudge =================
function curLayer(){ return sel ? variant().layers.find(l=>l.id===sel) : null; }
function positionImg(l){
  const im=document.querySelector('#stage .lyr[data-id="'+cssq(l.id)+'"]');
  if(im){ const b=l.bbox; im.style.left=(b.x*curScale)+'px'; im.style.top=(b.y*curScale)+'px';
    im.style.width=(b.width*curScale)+'px'; im.style.height=(b.height*curScale)+'px';
    if(im.classList.contains('txt') && l.textData) im.style.fontSize=((l.textData.size||20)*curScale)+'px'; }
}
function selectLayer(id, scrollList){
  if(groupMode) return;
  sel=id;
  document.querySelectorAll('#stage .lyr.sel').forEach(i=>i.classList.remove('sel'));
  const im=document.querySelector('#stage .lyr[data-id="'+cssq(id)+'"]'); if(im) im.classList.add('sel');
  document.querySelectorAll('.item.sel').forEach(i=>i.classList.remove('sel'));
  const it=document.querySelector('.item[data-id="'+cssq(id)+'"]');
  if(it){ it.classList.add('sel'); if(scrollList) it.scrollIntoView({block:'nearest'}); }
  drawSel(); ensurePanel();
}
function deselect(){ sel=null;
  const ov=document.querySelector('#stage .selov'); if(ov) ov.remove();
  document.querySelectorAll('.item.sel,#stage .lyr.sel').forEach(i=>i.classList.remove('sel'));
  document.getElementById('selPanel').style.display='none'; }
function drawSel(){
  const stage=document.getElementById('stage'); const old=stage.querySelector('.selov'); if(old) old.remove();
  const l=curLayer(); if(groupMode || !l || disabled[curTab].has(l.id)) return;
  const b=l.bbox;
  const ov=document.createElement('div'); ov.className='selov';
  ov.style.left=(b.x*curScale)+'px'; ov.style.top=(b.y*curScale)+'px';
  ov.style.width=(b.width*curScale)+'px'; ov.style.height=(b.height*curScale)+'px';
  ov.innerHTML='<div class="mv"></div>'+['nw','n','ne','e','se','s','sw','w']
    .map(d=>'<div class="hnd '+d+'" data-d="'+d+'"></div>').join('');
  stage.appendChild(ov);
  ov.querySelector('.mv').addEventListener('pointerdown',e=>{e.stopPropagation(); startDrag(e,'move');});
  ov.querySelectorAll('.hnd').forEach(h=>h.addEventListener('pointerdown',
    e=>{e.stopPropagation(); startDrag(e,h.dataset.d);}));
}
function startDrag(e, mode){
  e.preventDefault(); const l=curLayer(); if(!l) return;
  const s={x:e.clientX,y:e.clientY, bx:l.bbox.x,by:l.bbox.y,bw:l.bbox.width,bh:l.bbox.height};
  function mv(ev){
    const dx=(ev.clientX-s.x)/curScale, dy=(ev.clientY-s.y)/curScale;
    let bx=s.bx,by=s.by,bw=s.bw,bh=s.bh;
    if(mode==='move'){ bx=s.bx+dx; by=s.by+dy; }
    else{
      if(mode.indexOf('e')>=0) bw=Math.max(4,s.bw+dx);
      if(mode.indexOf('s')>=0) bh=Math.max(4,s.bh+dy);
      if(mode.indexOf('w')>=0){ bw=Math.max(4,s.bw-dx); bx=s.bx+(s.bw-bw); }
      if(mode.indexOf('n')>=0){ bh=Math.max(4,s.bh-dy); by=s.by+(s.bh-bh); }
    }
    l.bbox.x=Math.round(bx); l.bbox.y=Math.round(by); l.bbox.width=Math.round(bw); l.bbox.height=Math.round(bh);
    positionImg(l); drawSel(); syncNums();
  }
  function up(){ document.removeEventListener('pointermove',mv); document.removeEventListener('pointerup',up);
    recomputeSection(l); saveEdit(l.id,{bbox:l.bbox}); }
  document.addEventListener('pointermove',mv); document.addEventListener('pointerup',up);
}
function recomputeSection(l){
  const v=variant(), cy=l.bbox.y+l.bbox.height/2, S=v.sections; let si=0;
  S.forEach((s,i)=>{ if(s.y0<=cy && cy<s.y1) si=i; });
  if(cy>=S[S.length-1].y1) si=S.length-1;
  l.section=si;
}
function bringFront(){ const l=curLayer(); if(!l) return;
  l.z=Math.max(0,...variant().layers.map(x=>x.z||0))+1; saveEdit(l.id,{z:l.z}); render(); selectLayer(l.id); }
function sendBack(){ const l=curLayer(); if(!l) return;
  l.z=Math.min(0,...variant().layers.map(x=>x.z||0))-1; saveEdit(l.id,{z:l.z}); render(); selectLayer(l.id); }
const LINK_ACTIONS=[['','(khong)'],['download','Tai game'],['login','Dang nhap'],['register','Dang ky'],
  ['topup','Nap'],['gift','Nhan qua'],['rules','The le'],['history','Lich su'],['social','Facebook'],
  ['check','Kiem tra'],['custom','Link tuy chinh']];
function inp(id,val,ph,st){ return '<input id="'+id+'" value="'+esc(val||'')+'"'+(ph?' placeholder="'+ph+'"':'')
  +' style="'+(st||'')+'">'; }
function ensurePanel(){
  const l=curLayer(); const p=document.getElementById('selPanel');
  if(!l){ p.style.display='none'; return; }
  p.style.display='block';
  const lk=l.link||{}, td=l.textData;
  let h='<div class="t">&#9995; '+esc(l.name)+(l.group?' <span class="gbadge">gộp '+l.count+'</span>':'')
      +(td?' <span class="badge">T</span>':'')+'</div>'
   +'<div class="grpttl">Vị trí &amp; kích thước</div>'
   +'<div class="r">X<input class="num" id="sX">Y<input class="num" id="sY">'
   +'Rộng<input class="num" id="sW">Cao<input class="num" id="sH"></div>'
   +'<div class="r"><button class="sm" id="sFront">&#8593; Lên trên cùng</button>'
   +'<button class="sm ghost" id="sBack">&#8595; Xuống dưới cùng</button>'
   +'<button class="ghost sm" id="sDesel">Bỏ chọn (Esc)</button></div>';
  // --- CHỮ THẬT (chỉ layer chữ) ---
  if(td){
    h+='<div class="grpttl">Chữ</div>'
      +'<div class="r"><label style="cursor:pointer"><input type="checkbox" id="sAsText"'+(td.asText?' checked':'')
      +'> <b style="color:#bae6fd">Xuất CHỮ THẬT</b> <span style="opacity:.7">(SEO · nét · nhẹ)</span></label></div>'
      +'<div class="r"><textarea id="sTxt" rows="2" style="width:100%;resize:vertical">'+esc(td.content||'')+'</textarea></div>'
      +'<div class="r">Cỡ<input class="num" id="sTsize" value="'+esc(td.size||'')+'">'
      +'Màu<input type="color" id="sTcolor" value="'+(td.color||'#ffffff')+'" style="width:44px;height:28px;padding:1px"></div>';
  }
  // --- LIÊN KẾT / NÚT / ALT (mọi layer) ---
  h+='<div class="grpttl">Liên kết &amp; SEO</div>'
    +'<div class="r">Hành động<select id="sAct">'
    +LINK_ACTIONS.map(a=>'<option value="'+a[0]+'"'+(((lk.action)||'')===a[0]?' selected':'')+'>'+a[1]+'</option>').join('')
    +'</select><label style="cursor:pointer"><input type="checkbox" id="sBtn"'+(lk.button?' checked':'')+'> là nút</label></div>'
    +'<div class="r"><input id="sUrl" value="'+esc(lk.url||'')+'" placeholder="https://… (URL thật)" style="width:100%"></div>';
  // --- MỞ POPUP (chỉ ở tab desktop/mobile, khi dự án có PSD popup) ---
  const pops=(curTab.indexOf('popup:')===0)?[]:popupsList();
  if(pops.length){
    h+='<div class="r" title="Click layer này (khi xuất web) sẽ mở popup đã chọn">'
      +'&#129525; Mở popup<select id="sPopup" style="flex:1;min-width:120px"><option value="">(không)</option>'
      +pops.map(p=>'<option value="'+esc(p.id)+'"'+((lk.popup||'')===p.id?' selected':'')+'>'+esc(p.name)+'</option>').join('')
      +'</select></div>';
  }
  h+='<div class="r">Alt<input id="sAlt" value="'+esc(l.alt||'')+'" placeholder="mô tả ảnh (SEO)" style="flex:1;min-width:120px"></div>';
  // --- TÊN FILE XUẤT (đổi tên ảnh trong web xuất ra) ---
  const fdef=((l.asset||'').split('/').pop()||'').replace(/\.[^.]+$/,'');   // ten mac dinh (khong ext)
  const fext=(((l.asset||'').match(/\.[^.]+$/)||['.webp'])[0]);
  h+='<div class="grpttl">Tên file xuất</div>'
    +'<div class="r"><input id="sFname" value="'+esc(l.fname||'')+'" placeholder="'+esc(fdef)+'" style="flex:1;min-width:120px"><span style="color:var(--muted);font-size:12px">'+esc(fext)+'</span></div>'
    +'<div class="r" style="color:var(--muted);font-size:11.5px;margin-top:-4px">Để trống = giữ mặc định (<b>'+esc(fdef+fext)+'</b>). Dấu/khoảng trắng sẽ tự chuẩn hoá.</div>';
  // --- HIỆU ỨNG (gán tay cho từng layer, chỉ áp khi xuất React/Next) ---
  const FX_OPTS=[['','(không)'],['shine','Lướt sáng (vệt sáng lướt qua)'],
    ['shine-glow','Lướt sáng + phát sáng (như Mở Lối Xưng Bá)'],['glow','Phát sáng (quầng vàng)'],
    ['float','Trôi nhẹ lên xuống'],['float-glow','Trôi + phát sáng'],['btn','Nút: lướt sáng + hover to + glow']];
  h+='<div class="grpttl">&#10024; Hiệu ứng (React/Next)</div>'
    +'<div class="r"><select id="sFx" style="flex:1;min-width:150px">'
    +FX_OPTS.map(o=>'<option value="'+o[0]+'"'+((l.fx||'')===o[0]?' selected':'')+'>'+o[1]+'</option>').join('')
    +'</select></div>'
    +'<div class="r" style="color:var(--muted);font-size:11.5px;margin-top:-4px">Gán tay sẽ tự áp khi Xuất React/Next (không cần bật ô hiệu ứng chung). Lướt sáng đẹp nhất cho chữ tiêu đề.</div>';
  p.innerHTML=h;
  syncNums();
  ['sX','sY','sW','sH'].forEach(k=>{ document.getElementById(k).onchange=onNumChange; });
  document.getElementById('sFront').onclick=bringFront;
  document.getElementById('sBack').onclick=sendBack;
  document.getElementById('sDesel').onclick=deselect;
  if(td){
    const upT=()=>{ td.content=document.getElementById('sTxt').value;
      td.size=+document.getElementById('sTsize').value||td.size; td.color=document.getElementById('sTcolor').value;
      td.asText=document.getElementById('sAsText').checked;
      saveEdit(l.id,{text:{content:td.content,size:td.size,color:td.color,asText:td.asText}});
      render(); selectLayer(l.id); };
    ['sAsText','sTxt','sTsize','sTcolor'].forEach(k=>document.getElementById(k).onchange=upT);
  }
  const upL=()=>{ l.link=l.link||{};
    l.link.action=document.getElementById('sAct').value||null;
    l.link.url=document.getElementById('sUrl').value.trim()||null;
    l.link.button=document.getElementById('sBtn').checked;
    const sp=document.getElementById('sPopup'); if(sp) l.link.popup=sp.value||null;
    saveEdit(l.id,{link:{action:l.link.action,url:l.link.url,button:l.link.button,popup:l.link.popup||null}}); };
  ['sAct','sUrl','sBtn','sPopup'].forEach(k=>{ const el=document.getElementById(k); if(el) el.onchange=upL; });
  document.getElementById('sAlt').onchange=()=>{ l.alt=document.getElementById('sAlt').value; saveEdit(l.id,{alt:l.alt}); };
  const sf=document.getElementById('sFname');
  if(sf) sf.onchange=()=>{ const v=sf.value.trim(); l.fname=v; saveEdit(l.id,{fname:v||null}); };
  const sfx=document.getElementById('sFx');
  if(sfx) sfx.onchange=()=>{ l.fx=sfx.value; saveEdit(l.id,{fx:l.fx||null}); render(); };
}
function syncNums(){ const l=curLayer(); if(!l) return; const b=l.bbox;
  const set=(k,val)=>{const el=document.getElementById(k); if(el && document.activeElement!==el) el.value=Math.round(val);};
  set('sX',b.x); set('sY',b.y); set('sW',b.width); set('sH',b.height); }
function onNumChange(){ const l=curLayer(); if(!l) return;
  const g=k=>Math.round(+((document.getElementById(k)||{}).value)||0);
  l.bbox.x=g('sX'); l.bbox.y=g('sY'); l.bbox.width=Math.max(1,g('sW')); l.bbox.height=Math.max(1,g('sH'));
  positionImg(l); drawSel(); recomputeSection(l); saveEdit(l.id,{bbox:l.bbox}); }
function saveEdit(id, patch){
  fetch("/edit",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({job_id:JOB, variant:curTab, patch:{[id]:patch}})}).catch(()=>{});
}
let _saveT=null, _savePend=null;
function saveEditDebounced(id, patch){ _savePend={id,patch}; clearTimeout(_saveT);
  _saveT=setTimeout(()=>{ if(_savePend) saveEdit(_savePend.id,_savePend.patch); }, 350); }
// click nen preview: chon layer roi press-drag di chuyen; click nen trong -> bo chon
document.getElementById('stage').addEventListener('pointerdown', function(e){
  if(groupMode) return;
  if(e.target.closest('.selov')) return;
  const img=e.target.closest('.lyr');
  if(!img){ deselect(); return; }
  const id=img.dataset.id;
  if(id!==sel) selectLayer(id, true);
  startDrag(e,'move');
});
// phim mui ten nhich 1px (Shift=10px), Esc bo chon
document.addEventListener('keydown', function(e){
  if(!sel || groupMode) return;
  if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName||'')) return;
  if(e.key==='Escape'){ deselect(); return; }
  const l=curLayer(); if(!l) return;
  const step=e.shiftKey?10:1; let m=true;
  if(e.key==='ArrowLeft') l.bbox.x-=step; else if(e.key==='ArrowRight') l.bbox.x+=step;
  else if(e.key==='ArrowUp') l.bbox.y-=step; else if(e.key==='ArrowDown') l.bbox.y+=step; else m=false;
  if(m){ e.preventDefault(); positionImg(l); drawSel(); syncNums(); recomputeSection(l); saveEditDebounced(l.id,{bbox:l.bbox}); }
});

// ---- GOP LAYER ----
document.getElementById("grpMode").onclick=()=>{
  groupMode=!groupMode;
  document.getElementById("grpMode").classList.toggle("active", groupMode);
  document.getElementById("edHint").textContent=groupMode
    ? "Chế độ GỘP: bấm vào các ảnh muốn gộp, rồi bấm 'Gộp thành 1 ảnh'. Bấm 'tách' để bỏ nhóm."
    : "Bấm vào ảnh để chọn → kéo để di chuyển, kéo góc để đổi kích thước, phím mũi tên để nhích. Bỏ tích = không xuất ảnh đó.";
  if(!groupMode) groupSel[curTab].clear();
  sel=null; render();
};
document.getElementById("grpClear").onclick=()=>{ groupSel[curTab].clear(); render(); };
document.getElementById("grpDo").onclick=()=>{
  const ids=[...groupSel[curTab]];
  const nm=document.getElementById("grpName").value.trim();
  doGroup(ids, nm);
};
async function doGroup(members, name){
  // BO layer da AN (tat mat) khoi phep gop -> khong dinh anh an vao ban ghep
  members=(members||[]).filter(id=>!disabled[curTab].has(id));
  if(members.length<2){ alert("Hãy chọn ít nhất 2 ảnh (đang hiện) để gộp."); return; }
  const btn=document.getElementById("grpDo"); if(btn) btn.disabled=true;
  try{
    const r=await fetch("/group",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({job_id:JOB, variant:curTab, members, name:name||"Group"})}).then(x=>x.json());
    if(r.error){ alert("Lỗi gộp: "+r.error); return; }
    MAN=r.manifest; groupSel[curTab].clear();
    document.getElementById("grpName").value="";
    render();
  }catch(e){ alert("Lỗi gộp: "+e); }
  finally{ if(btn) btn.disabled=false; }
}
async function doUngroup(gid){
  const r=await fetch("/ungroup",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({job_id:JOB, variant:curTab, group_id:gid})}).then(x=>x.json());
  if(r.error){ alert("Lỗi tách: "+r.error); return; }
  MAN=r.manifest; render();
}

document.getElementById("restart").onclick=()=>{
  editor.classList.remove("show"); exportPanel.classList.remove("show");
  document.getElementById("step1").style.display="block";
  sel=null; layerQuery=""; setStep(1);
};

// ---- Xem thu web (render slices theo lua chon hien tai) ----
const goReview=document.getElementById("goReview"), reviewBox=document.getElementById("reviewBox"),
      reviewStep=document.getElementById("reviewStep"), reviewBar=document.getElementById("reviewBar"),
      reviewFrame=document.getElementById("reviewFrame"), reviewErr=document.getElementById("reviewErr"),
      reviewOpen=document.getElementById("reviewOpen");
let reviewUrl=null;
goReview.onclick=async()=>{
  const body={ job_id:JOB, swiper:document.getElementById("swiper").checked,
    disabled_desktop:[...(disabled.desktop||[])], disabled_mobile:[...(disabled.mobile||[])] };
  goReview.disabled=true; reviewBox.style.display="block"; reviewErr.textContent="";
  reviewBar.style.display="block"; reviewFrame.style.display="none"; reviewOpen.style.display="none";
  reviewStep.textContent="Đang gửi yêu cầu…";
  reviewBox.scrollIntoView({behavior:"smooth",block:"start"});
  let r;
  try{ r=await (await fetch("/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})).json(); }
  catch(e){ reviewStep.textContent="Lỗi: "+e; goReview.disabled=false; return; }
  if(r.error){ reviewStep.textContent="Lỗi: "+r.error; goReview.disabled=false; return; }
  pollReview();
};
async function pollReview(){
  let s; try{ s=await (await fetch("/status/"+JOB)).json(); }
  catch(e){ setTimeout(pollReview,1200); return; }
  reviewStep.textContent=s.step||"Đang xử lý…";
  if(s.status==="done" && s.phase==="preview" && s.preview){
    reviewUrl=s.preview+"?t="+Date.now();
    reviewBar.style.display="none"; reviewFrame.style.display="block"; reviewFrame.src=reviewUrl;
    reviewStep.textContent="\\u2713 Bản xem thử (theo ảnh đang chọn)";
    reviewOpen.style.display="inline-block"; goReview.disabled=false; return; }
  if(s.status==="error" && s.phase==="preview"){ reviewBar.style.display="none";
    reviewErr.textContent=(s.error||"")+"\\n"+(s.trace||""); goReview.disabled=false; return; }
  setTimeout(pollReview,1200);
}
reviewOpen.onclick=()=>{ if(reviewUrl) window.open(reviewUrl,"_blank"); };

// ---- BUOC 3: export ----
goExport.onclick=async()=>{
  const fmt=document.querySelector('input[name=fmt]:checked').value;
  const lang=(document.querySelector('input[name=lang]:checked')||{}).value||'js';
  const body={ job_id:JOB, format:fmt, lang:lang,
    swiper:document.getElementById("swiper").checked,
    disabled_desktop:[...(disabled.desktop||[])], disabled_mobile:[...(disabled.mobile||[])],
    disabled_popup:disabledPopupMap() };
  ["swiper_lib","env_config","nav_menu","popups","ai_enhance","fluid","fx","fx_reveal"].forEach(k=>body[k]=document.getElementById(k).checked);
  goExport.disabled=true; exportPanel.classList.add("show");
  exProgress.style.display="block"; result.style.display="none"; exStep.textContent="Đang gửi yêu cầu…";
  exportPanel.scrollIntoView({behavior:"smooth",block:"start"});
  let r;
  try{
    const resp=await fetch("/export",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    r=await resp.json();
  }catch(e){ exStep.textContent="Lỗi: "+e; goExport.disabled=false; return; }
  if(r.error){ exStep.textContent="Lỗi: "+r.error; goExport.disabled=false; return; }
  pollExport();
};

async function pollExport(){
  let s; try{ s=await (await fetch("/status/"+JOB)).json(); }
  catch(e){ setTimeout(pollExport,1500); return; }
  exStep.textContent=s.step||"Đang xử lý…";
  if(s.status==="done" && s.phase==="export"){ showResult(s); goExport.disabled=false; return; }
  if(s.status==="error"){ exProgress.style.display="none"; result.style.display="block";
    result.innerHTML='<b style="color:#fca5a5">Lỗi khi xuất:</b><div class="err">'+(s.error||"")+'\\n'+(s.trace||"")+'</div>';
    goExport.disabled=false; return; }
  setTimeout(pollExport,1500);
}

function showResult(s){
  setStep(3);
  exProgress.style.display="none"; result.style.display="block";
  let html='<b style="color:#4ade80;font-size:16px">\\u2705 Xuất thành công!</b> ';
  if(s.download) html+='<a class="dl" href="'+s.download+'">\\u2B07 Tải ZIP kết quả</a>';
  if(s.preview){ html+='<iframe src="'+s.preview+'?t='+Date.now()+'"></iframe>'; }
  else if(s.files && s.files.length){
    const isProj=(s.format==="react"||s.format==="next");
    if(isProj){
      html+='<button id="goBuild" class="dl" style="border:0;cursor:pointer">\\uD83D\\uDD28 Build &amp; Xem trước (npm)</button>';
      html+='<div id="buildBox" style="display:none;margin-top:10px">'
          +'<div id="buildBar"><div style="color:var(--muted);font-size:13px" id="buildStep"></div><div class="bar"><i></i></div></div>'
          +'<iframe id="buildFrame" style="display:none"></iframe>'
          +'<a id="buildOpen" style="display:none" class="dl" target="_blank">\\u2197 Mở tab mới</a>'
          +'<pre id="buildLog" class="err" style="display:none;max-height:180px;overflow:auto"></pre>'
          +'</div>';
    }
    html+='<div class="files">'+s.files.join("<br>")+'</div>'
      +'<p style="color:#94a3b8;font-size:13px">Đã tạo project '+(s.format==="next"?"Next.js":"React")+'. '
      +(isProj?'Bấm <b>Build &amp; Xem trước</b> để chạy ngay, hoặc giải nén ZIP rồi ':'Giải nén ZIP rồi ')
      +'chạy: <code>npm install &amp;&amp; npm run dev</code></p>';
  }
  result.innerHTML=html;
  const gb=document.getElementById("goBuild");
  if(gb) gb.onclick=startBuild;
}

let buildUrl=null;
async function startBuild(){
  const gb=document.getElementById("goBuild");
  const box=document.getElementById("buildBox"), bar=document.getElementById("buildBar"),
        step=document.getElementById("buildStep"), frame=document.getElementById("buildFrame"),
        openBtn=document.getElementById("buildOpen"), log=document.getElementById("buildLog");
  gb.disabled=true; box.style.display="block"; bar.style.display="block";
  frame.style.display="none"; openBtn.style.display="none"; log.style.display="none";
  step.textContent="Đang gửi yêu cầu…";
  let r;
  try{ r=await (await fetch("/build_preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({job_id:JOB})})).json(); }
  catch(e){ step.textContent="Lỗi: "+e; gb.disabled=false; return; }
  if(r.error){ step.textContent="Lỗi: "+r.error; gb.disabled=false; return; }
  pollBuild();
}
async function pollBuild(){
  const gb=document.getElementById("goBuild");
  const bar=document.getElementById("buildBar"), step=document.getElementById("buildStep"),
        frame=document.getElementById("buildFrame"), openBtn=document.getElementById("buildOpen"),
        log=document.getElementById("buildLog");
  let s; try{ s=await (await fetch("/status/"+JOB)).json(); }
  catch(e){ setTimeout(pollBuild,1500); return; }
  const b=s.build||{};
  step.textContent=b.step||"Đang xử lý…";
  if(b.status==="done" && b.url){
    buildUrl=b.url; bar.style.display="none";
    frame.style.display="block"; frame.src=buildUrl;
    openBtn.style.display="inline-block"; openBtn.href=buildUrl;
    if(gb) gb.disabled=false; return;
  }
  if(b.status==="error"){ bar.style.display="none";
    if(b.log){ log.style.display="block"; log.textContent=(b.error||"")+"\\n\\n"+b.log; }
    else step.textContent="Lỗi: "+(b.error||"");
    if(gb) gb.disabled=false; return;
  }
  setTimeout(pollBuild,1500);
}
</script>
</body></html>"""


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
