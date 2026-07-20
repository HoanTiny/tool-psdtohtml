"""
Giao dien WEB keo-tha cho psd2html (khong can go lenh).

Chay:
  venv\\Scripts\\python.exe -m psd2html.webapp
Roi mo http://localhost:5000

Luong: keo file PSD (desktop + tuy chon mobile) -> chon dinh dang -> bam Chuyen doi
-> xem preview (HTML) va tai ZIP ket qua.
"""

import shutil
import threading
import zipfile
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, send_file, abort
from werkzeug.utils import secure_filename

from .parser import parse_psd
from .render_slices import render as render_slices
from .export_web import export as export_web

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 800 * 1024 * 1024  # cho phep PSD nang toi 800MB

BASE = Path(__file__).resolve().parent.parent
JOBS_DIR = BASE / "output_web"
JOBS_DIR.mkdir(exist_ok=True)

jobs = {}          # job_id -> {status, step, error, format, preview, download, files}
_counter = [0]


def _new_job_id():
    _counter[0] += 1
    return f"job{_counter[0]}"


def _run(job_id, desktop_psd, mobile_psd, fmt):
    job = jobs[job_id]
    out = JOBS_DIR / job_id / "out"
    try:
        job["step"] = "Doc PSD desktop..."
        parse_psd(str(desktop_psd), str(out))

        mobile_dir = None
        if mobile_psd:
            job["step"] = "Doc PSD mobile..."
            mobile_dir = out / "_mobile"
            parse_psd(str(mobile_psd), str(mobile_dir))

        job["step"] = "Sinh code..."
        if fmt == "slices":
            render_slices(str(out))
            job["preview"] = f"/result/{job_id}/index.html"
            zip_src = out
            zip_include = ["index.html", "style.css", "assets", "sections"]
        else:
            proj = export_web(str(out), framework=fmt, mobile_dir=str(mobile_dir) if mobile_dir else None)
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


@app.route("/convert", methods=["POST"])
def convert():
    desktop = request.files.get("desktop")
    if not desktop or not desktop.filename:
        return jsonify({"error": "Chua chon file PSD desktop"}), 400
    fmt = request.form.get("format", "slices")
    if fmt not in ("slices", "react", "next"):
        fmt = "slices"

    job_id = _new_job_id()
    jdir = JOBS_DIR / job_id
    jdir.mkdir(parents=True, exist_ok=True)

    d_path = jdir / secure_filename(desktop.filename)
    desktop.save(d_path)

    m_path = None
    mobile = request.files.get("mobile")
    if mobile and mobile.filename:
        m_path = jdir / secure_filename(mobile.filename)
        mobile.save(m_path)

    jobs[job_id] = {"status": "running", "step": "Bat dau...", "format": fmt,
                    "error": None, "preview": None, "download": None, "files": []}
    threading.Thread(target=_run, args=(job_id, d_path, m_path, fmt), daemon=True).start()
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
    return send_file(z, as_attachment=True, download_name=f"psd2html-{jobs.get(job_id,{}).get('format','out')}.zip")


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
  .wrap{max-width:1000px;margin:0 auto;padding:24px}
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
  .panel{margin-top:20px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;display:none}
  .panel.show{display:block}
  .bar{height:8px;background:#334155;border-radius:6px;overflow:hidden;margin:10px 0}
  .bar>i{display:block;height:100%;background:var(--brand);width:30%;animation:pulse 1.2s infinite}
  @keyframes pulse{0%{opacity:.5}50%{opacity:1}100%{opacity:.5}}
  iframe{width:100%;height:560px;border:1px solid var(--line);border-radius:8px;background:#fff;margin-top:12px}
  a.dl{display:inline-block;background:#16a34a;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;margin-top:12px;font-weight:600}
  .err{color:#fca5a5;white-space:pre-wrap;font-family:monospace;font-size:12px}
  .files{color:var(--muted);font-size:12px;font-family:monospace;max-height:160px;overflow:auto;margin-top:10px}
</style></head><body>
<div class="wrap">
  <h1>🎨 psd2html</h1>
  <p class="sub">Keo file PSD vao, chon dinh dang, bam Chuyen doi. Khong can go lenh.</p>

  <div class="grid">
    <div class="drop" id="dropD">
      <div class="big">📄 Keo tha PSD <b>Desktop</b></div>
      <small>hoac bam de chon file (.psd)</small>
      <div class="fname" id="nameD"></div>
      <input type="file" id="fileD" accept=".psd" hidden>
    </div>
    <div class="drop" id="dropM">
      <div class="big">📱 Keo tha PSD <b>Mobile</b></div>
      <small>tuy chon - de trong neu khong co</small>
      <div class="fname" id="nameM"></div>
      <input type="file" id="fileM" accept=".psd" hidden>
    </div>
  </div>

  <div class="row">
    <div class="fmt">
      <label><input type="radio" name="fmt" value="slices" checked><span>HTML (xem ngay)</span></label>
      <label><input type="radio" name="fmt" value="react"><span>React + Tailwind</span></label>
      <label><input type="radio" name="fmt" value="next"><span>Next.js</span></label>
    </div>
    <button id="go">Chuyen doi</button>
  </div>

  <div class="panel" id="panel">
    <div id="progress">
      <b id="step">Dang xu ly...</b>
      <div class="bar"><i></i></div>
      <small style="color:var(--muted)">PSD lon co the mat 1-3 phut de doc.</small>
    </div>
    <div id="result" style="display:none"></div>
  </div>
</div>
<script>
let fileD=null, fileM=null;
function setupDrop(dropId, inputId, nameId, set){
  const drop=document.getElementById(dropId), input=document.getElementById(inputId), name=document.getElementById(nameId);
  drop.onclick=()=>input.click();
  input.onchange=()=>{ if(input.files[0]){ set(input.files[0]); name.textContent="✓ "+input.files[0].name; } };
  ["dragover","dragenter"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("over")}));
  ["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("over")}));
  drop.addEventListener("drop",ev=>{ const f=ev.dataTransfer.files[0]; if(f){ set(f); name.textContent="✓ "+f.name; }});
}
setupDrop("dropD","fileD","nameD",f=>fileD=f);
setupDrop("dropM","fileM","nameM",f=>fileM=f);

const panel=document.getElementById("panel"), stepEl=document.getElementById("step"),
      progress=document.getElementById("progress"), result=document.getElementById("result"), go=document.getElementById("go");

go.onclick=async()=>{
  if(!fileD){ alert("Hay chon file PSD desktop truoc"); return; }
  const fmt=document.querySelector('input[name=fmt]:checked').value;
  const fd=new FormData(); fd.append("desktop",fileD); if(fileM) fd.append("mobile",fileM); fd.append("format",fmt);
  go.disabled=true; panel.classList.add("show"); progress.style.display="block"; result.style.display="none"; stepEl.textContent="Tai file len...";
  let r;
  try{ r=await (await fetch("/convert",{method:"POST",body:fd})).json(); }
  catch(e){ stepEl.textContent="Loi tai len: "+e; go.disabled=false; return; }
  if(r.error){ stepEl.textContent="Loi: "+r.error; go.disabled=false; return; }
  poll(r.job_id);
};

async function poll(id){
  let s;
  try{ s=await (await fetch("/status/"+id)).json(); }
  catch(e){ setTimeout(()=>poll(id),1500); return; }
  stepEl.textContent=s.step||"Dang xu ly...";
  if(s.status==="done"){ showResult(s); go.disabled=false; return; }
  if(s.status==="error"){ progress.style.display="none"; result.style.display="block";
    result.innerHTML='<b style="color:#fca5a5">Loi khi chuyen doi:</b><div class="err">'+(s.error||"")+'\\n'+(s.trace||"")+'</div>'; go.disabled=false; return; }
  setTimeout(()=>poll(id),1500);
}

function showResult(s){
  progress.style.display="none"; result.style.display="block";
  let html='<b style="color:#4ade80">✓ Xong!</b> ';
  if(s.download) html+='<a class="dl" href="'+s.download+'">⬇ Tai ZIP ket qua</a>';
  if(s.preview){ html+='<iframe src="'+s.preview+'"></iframe>'; }
  else if(s.files && s.files.length){ html+='<div class="files">'+s.files.join("<br>")+'</div>'
    +'<p style="color:#94a3b8;font-size:13px">Project React/Next da tao. Giai nen ZIP roi chay: <code>npm install && npm run dev</code></p>'; }
  result.innerHTML=html;
}
</script>
</body></html>"""


def main():
    print("psd2html web UI: mo http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    main()
