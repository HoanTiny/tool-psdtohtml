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

def _variant_manifest(job_id, vdir, url_prefix):
    """
    Doc layout.json cua 1 bien the (desktop hoac mobile) -> manifest cho frontend:
    canvas, danh sach section, va tung ANH (layer co asset) kem section index.
    """
    layout = json.loads((Path(vdir) / "layout.json").read_text(encoding="utf-8"))
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

    items = []
    for l in layout["layers"]:
        if not l.get("asset"):   # bo group/layer khong co anh
            continue
        b = l["bbox"]
        items.append({
            "id": l["id"],
            "name": (l.get("name") or l["id"]),
            "kind": l.get("kind"),
            "bbox": b,
            "asset": base + l["asset"],
            "text": bool((l.get("text") or {}).get("content")),
            "section": _section_of(b["y"] + b["height"] / 2),
        })

    return {
        "canvas": canvas,
        "screenshot": base + layout.get("screenshot", "screenshot.png"),
        "sections": [{"name": s["name"], "y0": s["y0"], "y1": s["y1"]} for s in secs],
        "layers": items,
    }


def _build_manifest(job_id):
    out = JOBS_DIR / job_id / "out"
    man = {"desktop": _variant_manifest(job_id, out, ""), "mobile": None}
    if (out / "_mobile" / "layout.json").exists():
        man["mobile"] = _variant_manifest(job_id, out / "_mobile", "_mobile/")
    return man


def _run_parse(job_id, desktop_psds, mobile_psds, quality="balanced"):
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

def _apply_selection(vdir, disabled):
    """
    Loc layout.json: bo cac layer id nam trong `disabled`. Luon dung tu ban goc
    layout.orig.json de export lai nhieu lan deu chinh xac theo lua chon hien tai.
    """
    vdir = Path(vdir)
    orig = vdir / "layout.orig.json"
    cur = vdir / "layout.json"
    if not orig.exists():
        shutil.copyfile(cur, orig)
    layout = json.loads(orig.read_text(encoding="utf-8"))
    dis = set(disabled or [])
    if dis:
        layout["layers"] = [l for l in layout["layers"] if l.get("id") not in dis]
    cur.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_export(job_id, fmt, lang, swiper, feats, disabled_d, disabled_m):
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

        # Don ket qua render cu (tranh lan file section cu khi xuat lai)
        for stale in ("react-app", "next-app", "sections"):
            p = out / stale
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)

        job["step"] = "Sinh code..."
        if fmt == "slices":
            render_slices(str(out), swiper=swiper)
            job["preview"] = f"/result/{job_id}/index.html"
            job["files"] = []
            zip_src = out
            zip_include = ["index.html", "style.css", "assets", "sections"]
        else:
            proj = export_web(str(out), framework=fmt, lang=lang,
                              mobile_dir=str(mobile_dir) if has_mobile else None,
                              detect_repeats=feats.get("fluid", False),
                              swiper=swiper, feats=feats)
            job["preview"] = None
            zip_src = Path(proj)
            zip_include = None  # zip toan bo project
            job["files"] = sorted(p.name for p in Path(proj).glob("**/*")
                                  if p.is_file() and "node_modules" not in str(p))[:60]

        job["step"] = "Nen ZIP..."
        zip_path = JOBS_DIR / job_id / "result.zip"
        _make_zip(zip_src, zip_path, zip_include)
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


def _make_zip(src, zip_path, include=None):
    src = Path(src)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if include is None:
            for p in src.rglob("*"):
                if p.is_file() and "node_modules" not in str(p):
                    zf.write(p, p.relative_to(src))
        else:
            for name in include:
                item = src / name
                if item.is_file():
                    zf.write(item, name)
                elif item.is_dir():
                    for p in item.rglob("*"):
                        if p.is_file():
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

    jobs[job_id] = {"phase": "parse", "status": "running", "step": "Bat dau...",
                    "sections": len(d_paths), "error": None, "manifest": None,
                    "preview": None, "download": None, "files": []}
    threading.Thread(target=_run_parse, args=(job_id, d_paths, m_paths, quality),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/export", methods=["POST"])
def export():
    """Buoc 3: nhan lua chon (format/option + danh sach anh bo) -> render + ZIP."""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    job = jobs.get(job_id)
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
             "ai_enhance": _flag(data.get("ai_enhance")), "fluid": _flag(data.get("fluid"))}
    disabled_d = data.get("disabled_desktop") or []
    disabled_m = data.get("disabled_mobile") or []

    job.update(phase="export", status="running", format=fmt, lang=lang,
               step="Bat dau xuat...", error=None, trace=None,
               preview=None, download=None, files=[])
    threading.Thread(target=_run_export,
                     args=(job_id, fmt, lang, swiper, feats, disabled_d, disabled_m),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/preview", methods=["POST"])
def preview():
    """Xem thu: render slices theo lua chon anh hien tai (khong ZIP)."""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    job = jobs.get(job_id)
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
    job = jobs.get(job_id)
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
<title>psd2html - Chuyen PSD sang code</title>
<style>
  :root{--brand:#2563eb;--bg:#0f172a;--card:#1e293b;--line:#334155;--txt:#e2e8f0;--muted:#94a3b8}
  *{box-sizing:border-box}
  body{margin:0;font-family:system-ui,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--txt)}
  .wrap{max-width:1180px;margin:0 auto;padding:24px}
  h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px;font-size:14px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  @media(max-width:700px){.grid{grid-template-columns:1fr}}
  .drop{border:2px dashed var(--line);border-radius:12px;padding:26px;text-align:center;cursor:pointer;background:var(--card);transition:.15s}
  .drop:hover,.drop.over{border-color:var(--brand);background:#243149}
  .drop .big{font-size:15px}.drop .fname{color:#4ade80;margin-top:8px;font-size:13px;word-break:break-all}
  .drop small{color:var(--muted)}
  .row{display:flex;gap:16px;align-items:center;margin:18px 0;flex-wrap:wrap}
  .fmt{display:flex;gap:10px;flex-wrap:wrap}
  .fmt label{border:1px solid var(--line);border-radius:8px;padding:8px 14px;cursor:pointer;background:var(--card);font-size:14px}
  .fmt input{margin-right:6px}
  .fmt input:checked+span{color:#93c5fd;font-weight:600}
  button{background:var(--brand);color:#fff;border:0;border-radius:8px;padding:12px 26px;font-size:15px;font-weight:600;cursor:pointer}
  button:disabled{opacity:.5;cursor:default}
  button.ghost{background:#334155}
  .panel{margin-top:20px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;display:none}
  .panel.show{display:block}
  .bar{height:8px;background:#334155;border-radius:6px;overflow:hidden;margin:10px 0}
  .bar>i{display:block;height:100%;background:var(--brand);width:30%;animation:pulse 1.2s infinite}
  @keyframes pulse{0%{opacity:.5}50%{opacity:1}100%{opacity:.5}}
  iframe{width:100%;height:560px;border:1px solid var(--line);border-radius:8px;background:#fff;margin-top:12px}
  a.dl{display:inline-block;background:#16a34a;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:12px;font-weight:600}
  .err{color:#fca5a5;white-space:pre-wrap;font-family:monospace;font-size:12px}
  .files{color:var(--muted);font-size:12px;font-family:monospace;max-height:160px;overflow:auto;margin-top:10px}
  /* editor */
  .ed{display:grid;grid-template-columns:minmax(280px,420px) 1fr;gap:18px}
  @media(max-width:820px){.ed{grid-template-columns:1fr}}
  .prevBox{position:sticky;top:16px;align-self:start;background:#0b1220;border:1px solid var(--line);border-radius:10px;padding:10px;max-height:88vh;overflow:auto}
  .stage{position:relative;margin:0 auto;background:#fff;background-image:linear-gradient(45deg,#e2e8f0 25%,transparent 25%,transparent 75%,#e2e8f0 75%),linear-gradient(45deg,#e2e8f0 25%,#fff 25%,#fff 75%,#e2e8f0 75%);background-size:20px 20px;background-position:0 0,10px 10px}
  .stage img{position:absolute;display:block}
  .stage img.off{display:none}
  .secmark{position:absolute;left:0;right:0;border-top:2px dashed rgba(37,99,235,.5);pointer-events:none}
  .secmark span{position:absolute;top:2px;left:4px;font-size:10px;background:rgba(37,99,235,.85);color:#fff;padding:1px 6px;border-radius:0 0 6px 0}
  .tabs{display:flex;gap:8px;margin-bottom:10px}
  .tabs button{padding:6px 14px;font-size:13px;background:#334155}
  .tabs button.active{background:var(--brand)}
  .sec{border:1px solid var(--line);border-radius:10px;margin-bottom:10px;overflow:hidden}
  .sec>h4{margin:0;padding:10px 12px;background:#111a2e;font-size:14px;display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none}
  .sec>h4 .cnt{color:var(--muted);font-weight:400;font-size:12px}
  .sec>h4 .toggle{margin-left:auto;font-size:12px;color:#93c5fd;background:#1e293b;border:1px solid var(--line);padding:3px 8px;border-radius:6px}
  .layers{padding:6px;display:grid;grid-template-columns:1fr 1fr;gap:6px}
  @media(max-width:520px){.layers{grid-template-columns:1fr}}
  .item{display:flex;align-items:center;gap:8px;padding:5px;border:1px solid var(--line);border-radius:8px;background:#0f172a;cursor:pointer}
  .item.off{opacity:.4}
  .item .th{width:44px;height:44px;object-fit:contain;background:#1e293b;border-radius:5px;flex:0 0 44px}
  .item .nm{font-size:12px;line-height:1.25;word-break:break-word;flex:1;min-width:0}
  .item .badge{font-size:9px;padding:1px 5px;border-radius:4px;background:#334155;color:#cbd5e1;margin-left:4px}
  .item input{flex:0 0 auto}
  .hint{color:var(--muted);font-size:13px;margin:0 0 12px}
</style></head><body>
<div class="wrap">
  <h1>&#127912; psd2html</h1>
  <p class="sub">Keo file PSD vao &rarr; <b>Phan tich</b> &rarr; <b>chon anh giu/bo</b> &rarr; <b>Xuat web</b>.<br>
    <b style="color:#93c5fd">Nhieu file = moi file 1 section</b>, ghep doc theo <b>thu tu ten file</b>
    (vd: 01-hero.psd, 02-features.psd, 03-footer.psd).</p>

  <!-- BUOC 1: upload -->
  <div id="step1">
    <div class="grid">
      <div class="drop" id="dropD">
        <div class="big">&#128196; Keo tha PSD <b>Desktop</b></div>
        <small>1 file, hoac nhieu file (moi file 1 section)</small>
        <div class="fname" id="nameD"></div>
        <input type="file" id="fileD" accept=".psd" multiple hidden>
      </div>
      <div class="drop" id="dropM">
        <div class="big">&#128241; Keo tha PSD <b>Mobile</b></div>
        <small>tuy chon - 1 hoac nhieu file</small>
        <div class="fname" id="nameM"></div>
        <input type="file" id="fileM" accept=".psd" multiple hidden>
      </div>
    </div>
    <div class="row">
      <span style="color:var(--muted);font-size:14px">Chat luong anh:</span>
      <div class="fmt">
        <label><input type="radio" name="quality" value="balanced" checked><span>Can bang (WebP)</span></label>
        <label><input type="radio" name="quality" value="high"><span>Net cao (WebP)</span></label>
        <label><input type="radio" name="quality" value="png"><span>Anh goc (PNG, nang)</span></label>
      </div>
    </div>
    <div class="row">
      <button id="goParse">&#128269; Phan tich PSD</button>
      <small style="color:var(--muted)">PSD lon co the mat 1-3 phut de doc.</small>
    </div>
  </div>

  <!-- panel tien trinh parse -->
  <div class="panel" id="parsePanel">
    <b id="parseStep">Dang xu ly...</b>
    <div class="bar"><i></i></div>
    <div id="parseErr" class="err"></div>
  </div>

  <!-- BUOC 2: EDITOR -->
  <div class="panel" id="editor">
    <div class="row" style="margin-top:0">
      <b style="font-size:16px">&#9986;&#65039; Chon anh dua vao web</b>
      <span class="tabs" id="tabs"></span>
      <span style="margin-left:auto;color:var(--muted);font-size:13px" id="selInfo"></span>
    </div>
    <p class="hint">Bo tich = khong xuat anh do. Bam tieu de section de bat/tat ca section.
      Preview ben trai an/hien ngay theo lua chon.</p>
    <div class="ed">
      <div class="prevBox"><div class="stage" id="stage"></div></div>
      <div id="secList"></div>
    </div>

    <hr style="border-color:var(--line);margin:18px 0">
    <!-- BUOC 3: format + option -->
    <div class="row" style="margin-top:0">
      <div class="fmt">
        <label><input type="radio" name="fmt" value="slices" checked><span>HTML (xem ngay)</span></label>
        <label><input type="radio" name="fmt" value="react"><span>React + Tailwind</span></label>
        <label><input type="radio" name="fmt" value="next"><span>Next.js</span></label>
      </div>
    </div>
    <div class="row" id="langRow" style="display:none">
      <span style="color:var(--muted);font-size:14px">Ngon ngu:</span>
      <div class="fmt">
        <label><input type="radio" name="lang" value="js" checked><span>JavaScript</span></label>
        <label><input type="radio" name="lang" value="ts"><span>TypeScript</span></label>
      </div>
    </div>
    <div class="row">
      <label class="fmt" style="cursor:pointer"><input type="checkbox" id="swiper" style="margin-right:6px">
        <span>Full-page (swiper): lan/vuot snap tung section</span></label>
    </div>
    <div id="reactOpts" style="display:none;margin:6px 0 4px">
      <div style="color:var(--muted);font-size:13px;margin-bottom:6px">Tuy chon React/Next (bam prod):</div>
      <div class="fmt" style="flex-direction:column;gap:8px;align-items:flex-start">
        <label style="cursor:pointer"><input type="checkbox" id="swiper_lib" style="margin-right:6px"><span>Dung Swiper.js that (effect fade nhu prod)</span></label>
        <label style="cursor:pointer"><input type="checkbox" id="env_config" style="margin-right:6px"><span>Config link/API bang .env (VITE_APP_*)</span></label>
        <label style="cursor:pointer"><input type="checkbox" id="nav_menu" style="margin-right:6px"><span>Nav chu + slideTo (config duoc)</span></label>
        <label style="cursor:pointer"><input type="checkbox" id="popups" style="margin-right:6px"><span>Popup stubs (login/the le/lich su/nap dau)</span></label>
        <label style="cursor:pointer"><input type="checkbox" id="fluid" style="margin-right:6px"><span>&#128241; Mobile co gian that (section xep doc, luoi reflow 4&rarr;2&rarr;1 cot) - khong dung khi da co PSD mobile</span></label>
        <label style="cursor:pointer"><input type="checkbox" id="ai_enhance" style="margin-right:6px"><span>&#10024; AI prod-hoa (chu that + hover) - can API key trong .env</span></label>
      </div>
    </div>
    <div class="row">
      <button id="goExport">&#128190; Xuat web</button>
      <button class="ghost" id="goReview">&#128065; Xem thu web</button>
      <button class="ghost" id="restart">&#8617; Phan tich file khac</button>
    </div>
    <div id="reviewBox" style="display:none;margin-top:6px">
      <div class="row" style="margin:0 0 6px">
        <b id="reviewStep" style="font-size:14px">Dang dung ban xem thu...</b>
        <span style="color:var(--muted);font-size:12px">Ban HTML thuc te theo anh dang chon (chua tinh responsive React/Next).</span>
        <button class="ghost" id="reviewOpen" style="margin-left:auto;padding:6px 12px;font-size:13px;display:none">&#8599; Mo tab moi</button>
      </div>
      <div class="bar" id="reviewBar"><i></i></div>
      <iframe id="reviewFrame" style="display:none;height:640px"></iframe>
      <div id="reviewErr" class="err"></div>
    </div>
  </div>

  <!-- panel export + ket qua -->
  <div class="panel" id="exportPanel">
    <div id="exProgress">
      <b id="exStep">Dang xuat...</b>
      <div class="bar"><i></i></div>
    </div>
    <div id="result" style="display:none"></div>
  </div>
</div>
<script>
let filesD=[], filesM=[];
let JOB=null, MAN=null, curTab='desktop';
const disabled={desktop:new Set(), mobile:new Set()};

function showList(nameEl, arr){
  if(!arr.length){ nameEl.innerHTML=""; return; }
  const sorted=[...arr].sort((a,b)=>a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
  if(sorted.length===1){ nameEl.textContent="\\u2713 "+sorted[0].name; return; }
  nameEl.innerHTML="\\u2713 "+sorted.length+" section:<br>"
    + sorted.map((f,i)=>(i+1)+". "+f.name).join("<br>");
}
function setupDrop(dropId, inputId, nameId, get, set){
  const drop=document.getElementById(dropId), input=document.getElementById(inputId), name=document.getElementById(nameId);
  drop.onclick=()=>input.click();
  input.onchange=()=>{ if(input.files.length){ set([...input.files]); showList(name,get()); } };
  ["dragover","dragenter"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("over")}));
  ["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("over")}));
  drop.addEventListener("drop",ev=>{ const fs=[...ev.dataTransfer.files].filter(f=>/\\.psd$/i.test(f.name));
    if(fs.length){ set(fs); showList(name,get()); }});
}
setupDrop("dropD","fileD","nameD",()=>filesD,a=>filesD=a);
setupDrop("dropM","fileM","nameM",()=>filesM,a=>filesM=a);

document.querySelectorAll('input[name=fmt]').forEach(r=>r.addEventListener('change',()=>{
  const f=document.querySelector('input[name=fmt]:checked').value;
  const isRN=(f==='react'||f==='next');
  document.getElementById('langRow').style.display=isRN?'flex':'none';
  document.getElementById('reactOpts').style.display=isRN?'block':'none';
}));

const parsePanel=document.getElementById("parsePanel"), parseStep=document.getElementById("parseStep"),
      parseErr=document.getElementById("parseErr"), editor=document.getElementById("editor"),
      exportPanel=document.getElementById("exportPanel"), exProgress=document.getElementById("exProgress"),
      exStep=document.getElementById("exStep"), result=document.getElementById("result"),
      goParse=document.getElementById("goParse"), goExport=document.getElementById("goExport");

// ---- BUOC 1: parse ----
goParse.onclick=async()=>{
  if(!filesD.length){ alert("Hay chon file PSD desktop truoc"); return; }
  const fd=new FormData();
  filesD.forEach(f=>fd.append("desktop",f));
  filesM.forEach(f=>fd.append("mobile",f));
  fd.append("quality",(document.querySelector('input[name=quality]:checked')||{}).value||'balanced');
  goParse.disabled=true; parsePanel.classList.add("show"); parseErr.textContent="";
  editor.classList.remove("show"); parseStep.textContent="Tai file len...";
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
  parseStep.textContent=s.step||"Dang xu ly...";
  if(s.status==="done" && s.manifest){ MAN=s.manifest; goParse.disabled=false;
    parsePanel.classList.remove("show"); openEditor(); return; }
  if(s.status==="error"){ parseErr.textContent=(s.error||"")+"\\n"+(s.trace||""); goParse.disabled=false; return; }
  setTimeout(pollParse,1500);
}

// ---- BUOC 2: editor ----
function openEditor(){
  document.getElementById("step1").style.display="none";
  disabled.desktop.clear(); disabled.mobile.clear();
  curTab='desktop';
  const tabs=document.getElementById("tabs");
  tabs.innerHTML="";
  if(MAN.mobile){
    ["desktop","mobile"].forEach(t=>{ const b=document.createElement("button");
      b.textContent=t==='desktop'?'\\u{1F4BB} Desktop':'\\u{1F4F1} Mobile';
      b.className=t===curTab?'active':''; b.onclick=()=>{curTab=t; render();}; tabs.appendChild(b); });
  }
  editor.classList.add("show"); render();
}

function variant(){ return MAN[curTab]; }

function render(){
  document.querySelectorAll('#tabs button').forEach((b,i)=>b.className=(['desktop','mobile'][i]===curTab)?'active':'');
  const v=variant(), dis=disabled[curTab];
  // preview stage
  const stage=document.getElementById("stage");
  const maxW=380, scale=Math.min(1, maxW/v.canvas.width);
  stage.style.width=(v.canvas.width*scale)+"px";
  stage.style.height=(v.canvas.height*scale)+"px";
  let html="";
  v.layers.forEach(l=>{ const b=l.bbox, off=dis.has(l.id)?" off":"";
    html+='<img class="lyr'+off+'" data-id="'+l.id+'" src="'+l.asset+'" loading="lazy" style="left:'+(b.x*scale)+'px;top:'+(b.y*scale)+'px;width:'+(b.width*scale)+'px;height:'+(b.height*scale)+'px">';
  });
  v.sections.forEach((s,i)=>{ if(i===0)return;
    html+='<div class="secmark" style="top:'+(s.y0*scale)+'px"><span>'+esc(s.name)+'</span></div>'; });
  stage.innerHTML=html;

  // list nhom theo section
  const list=document.getElementById("secList"); list.innerHTML="";
  v.sections.forEach((s,si)=>{
    const layers=v.layers.filter(l=>l.section===si);
    if(!layers.length) return;
    const sec=document.createElement("div"); sec.className="sec";
    const kept=layers.filter(l=>!dis.has(l.id)).length;
    const h=document.createElement("h4");
    h.innerHTML='<span>'+esc(s.name)+'</span><span class="cnt">'+kept+'/'+layers.length+' anh</span>'
      +'<span class="toggle">bat/tat het</span>';
    h.querySelector('.toggle').onclick=(e)=>{ e.stopPropagation();
      const allOn=layers.every(l=>!dis.has(l.id));
      layers.forEach(l=>{ if(allOn) dis.add(l.id); else dis.delete(l.id); });
      render(); };
    sec.appendChild(h);
    const box=document.createElement("div"); box.className="layers";
    layers.forEach(l=>{
      const on=!dis.has(l.id);
      const it=document.createElement("label"); it.className="item"+(on?"":" off");
      it.innerHTML='<input type="checkbox" '+(on?"checked":"")+'>'
        +'<img class="th" src="'+l.asset+'" loading="lazy">'
        +'<span class="nm">'+esc(l.name)+(l.text?'<span class="badge">T</span>':'')+'</span>';
      it.querySelector('input').onchange=(e)=>{ if(e.target.checked) dis.delete(l.id); else dis.add(l.id);
        // cap nhat nhanh khong render lai toan bo
        it.classList.toggle("off",!e.target.checked);
        const im=stage.querySelector('img[data-id="'+cssq(l.id)+'"]'); if(im) im.classList.toggle("off",!e.target.checked);
        updInfo(); h.querySelector('.cnt').textContent=layers.filter(x=>!dis.has(x.id)).length+'/'+layers.length+' anh'; };
      box.appendChild(it);
    });
    sec.appendChild(box); list.appendChild(sec);
  });
  updInfo();
}
function updInfo(){
  const v=variant(), dis=disabled[curTab], tot=v.layers.length, kept=tot-[...dis].filter(id=>v.layers.some(l=>l.id===id)).length;
  document.getElementById("selInfo").textContent="Giu "+kept+"/"+tot+" anh";
}
function esc(s){ return (s||"").replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function cssq(s){ return (s||"").replace(/"/g,'\\\\"'); }

document.getElementById("restart").onclick=()=>{
  editor.classList.remove("show"); exportPanel.classList.remove("show");
  document.getElementById("step1").style.display="block";
};

// ---- Xem thu web (render slices theo lua chon hien tai) ----
const goReview=document.getElementById("goReview"), reviewBox=document.getElementById("reviewBox"),
      reviewStep=document.getElementById("reviewStep"), reviewBar=document.getElementById("reviewBar"),
      reviewFrame=document.getElementById("reviewFrame"), reviewErr=document.getElementById("reviewErr"),
      reviewOpen=document.getElementById("reviewOpen");
let reviewUrl=null;
goReview.onclick=async()=>{
  const body={ job_id:JOB, swiper:document.getElementById("swiper").checked,
    disabled_desktop:[...disabled.desktop], disabled_mobile:[...disabled.mobile] };
  goReview.disabled=true; reviewBox.style.display="block"; reviewErr.textContent="";
  reviewBar.style.display="block"; reviewFrame.style.display="none"; reviewOpen.style.display="none";
  reviewStep.textContent="Gui yeu cau...";
  reviewBox.scrollIntoView({behavior:"smooth",block:"start"});
  let r;
  try{ r=await (await fetch("/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})).json(); }
  catch(e){ reviewStep.textContent="Loi: "+e; goReview.disabled=false; return; }
  if(r.error){ reviewStep.textContent="Loi: "+r.error; goReview.disabled=false; return; }
  pollReview();
};
async function pollReview(){
  let s; try{ s=await (await fetch("/status/"+JOB)).json(); }
  catch(e){ setTimeout(pollReview,1200); return; }
  reviewStep.textContent=s.step||"Dang xu ly...";
  if(s.status==="done" && s.phase==="preview" && s.preview){
    reviewUrl=s.preview+"?t="+Date.now();
    reviewBar.style.display="none"; reviewFrame.style.display="block"; reviewFrame.src=reviewUrl;
    reviewStep.textContent="\\u2713 Ban xem thu (theo anh dang chon)";
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
    disabled_desktop:[...disabled.desktop], disabled_mobile:[...disabled.mobile] };
  ["swiper_lib","env_config","nav_menu","popups","ai_enhance","fluid"].forEach(k=>body[k]=document.getElementById(k).checked);
  goExport.disabled=true; exportPanel.classList.add("show");
  exProgress.style.display="block"; result.style.display="none"; exStep.textContent="Gui yeu cau...";
  let r;
  try{
    const resp=await fetch("/export",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    r=await resp.json();
  }catch(e){ exStep.textContent="Loi: "+e; goExport.disabled=false; return; }
  if(r.error){ exStep.textContent="Loi: "+r.error; goExport.disabled=false; return; }
  pollExport();
};

async function pollExport(){
  let s; try{ s=await (await fetch("/status/"+JOB)).json(); }
  catch(e){ setTimeout(pollExport,1500); return; }
  exStep.textContent=s.step||"Dang xu ly...";
  if(s.status==="done" && s.phase==="export"){ showResult(s); goExport.disabled=false; return; }
  if(s.status==="error"){ exProgress.style.display="none"; result.style.display="block";
    result.innerHTML='<b style="color:#fca5a5">Loi khi xuat:</b><div class="err">'+(s.error||"")+'\\n'+(s.trace||"")+'</div>';
    goExport.disabled=false; return; }
  setTimeout(pollExport,1500);
}

function showResult(s){
  exProgress.style.display="none"; result.style.display="block";
  let html='<b style="color:#4ade80">\\u2713 Xong!</b> ';
  if(s.download) html+='<a class="dl" href="'+s.download+'">\\u2B07 Tai ZIP ket qua</a>';
  if(s.preview){ html+='<iframe src="'+s.preview+'?t='+Date.now()+'"></iframe>'; }
  else if(s.files && s.files.length){ html+='<div class="files">'+s.files.join("<br>")+'</div>'
    +'<p style="color:#94a3b8;font-size:13px">Project React/Next da tao. Giai nen ZIP roi chay: <code>npm install &amp;&amp; npm run dev</code></p>'; }
  result.innerHTML=html;
}
</script>
</body></html>"""


def main():
    print("psd2html web UI: mo http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    main()
