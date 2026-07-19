"""
Che do CAT ANH TRUC TIEP (deterministic, KHONG dung AI).

Danh cho landing nhieu do hoa (game, su kien): moi layer -> 1 anh dat dung bbox.

Tinh nang:
  - Cat bo phan thua o day (nen keo dai hon noi dung).
  - Ap blend mode (multiply/screen...) qua CSS mix-blend-mode cho khop thiet ke.
  - Bien cac layer CTA (Nhan Qua, Dang Nhap, Nap The, menu...) thanh <a> bam duoc.
  - Responsive: tu co gian ca trang cho vua man hinh nho.

Ket qua: index.html + style.css trong out_dir.
"""

import html as html_mod
import json
from pathlib import Path

from .sectionize import is_background

# Layer co ten/chu chua 1 trong cac cum nay -> coi la nut/lien ket bam duoc.
# (Dung cum cu the de tranh nham voi tieu de vd 'Nap Dung Goi'.)
INTERACTIVE_KEYWORDS = [
    "nhận quà", "đăng nhập", "đăng ký", "nạp thẻ", "cập nhật",
    "tải file", "tải ngay", "app store", "google play", "apk",
    "thể lệ", "thông tin đăng", "lịch sử", "điều khoản", "facebook",
    "button", "btn", "menu ngang",
]


def _content_bottom_from_image(path, canvas_h, thr=6.0, pad=8):
    """
    Tim day thuc su cua thiet ke tu anh composite: quet tu duoi len, dong nao
    con 'bien thien mau' (std > thr) la con hinh. Chi cat phan trong o tan cung.
    Nho vay giu duoc nen trang tri footer (seu, song...) ma van bo phan rong thua.
    """
    try:
        import numpy as np
        im = Image.open(path).convert("RGB")
        a = np.asarray(im)
        h = a.shape[0]
        rowstd = a.reshape(h, -1).std(axis=1)
        nz = np.where(rowstd > thr)[0]
        if len(nz) == 0:
            return canvas_h
        last = int(nz[-1]) + pad
        last = min(canvas_h, last)
        # An toan: neu tinh ra qua ngan (<50% trang) thi giu nguyen canvas
        return last if last >= canvas_h * 0.5 else canvas_h
    except Exception:
        return canvas_h


def _norm(s):
    return (s or "").replace("\r", " ").replace("\n", " ").strip().lower()


def _is_interactive(layer):
    hay = _norm(layer.get("name"))
    txt = _norm(layer.get("text", {}).get("content") if layer.get("text") else "")
    for kw in INTERACTIVE_KEYWORDS:
        if kw in hay or kw in txt:
            return True
    return False


def render(out_dir):
    out_dir = Path(out_dir)
    layout = json.loads((out_dir / "layout.json").read_text(encoding="utf-8"))
    canvas = layout["canvas"]
    cw, ch = canvas["width"], canvas["height"]

    layers = [l for l in layout["layers"] if l.get("asset")]

    # Chieu cao thuc: cat theo ANH COMPOSITE that - chi bo cac dong TRONG (dong mau)
    # o day, giu lai moi dong con hinh (ke ca nen trang tri footer nhu seu/song vang).
    stage_h = _content_bottom_from_image(out_dir / layout.get("screenshot", "screenshot.png"), ch)

    items_html = []
    items_css = [
        "* { margin: 0; padding: 0; box-sizing: border-box; }",
        "body { background: #000; }",
        ".stage-wrap { width: 100%; overflow: hidden; }",
        f".stage {{ position: relative; width: {cw}px; height: {stage_h}px;"
        f" margin: 0 auto; transform-origin: top left; overflow: hidden; }}",
        ".stage .node { position: absolute; display: block; }",
        ".stage a.node > img { width: 100%; height: 100%; display: block; }",
        # nut bam: con tro + hieu ung hover nhe
        ".stage a.node { cursor: pointer; transition: filter .15s ease, transform .15s ease; }",
        ".stage a.node:hover { filter: brightness(1.08); }",
    ]

    for l in layers:
        b = l["bbox"]
        cls = l["id"]
        alt = ""
        if l.get("text") and l["text"].get("content"):
            alt = l["text"]["content"]
        else:
            alt = l.get("name", "")
        alt = html_mod.escape(_norm(alt), quote=True)

        # CSS vi tri cho layer nay
        rule = (f".stage .{cls}{{left:{b['x']}px;top:{b['y']}px;"
                f"width:{b['width']}px;height:{b['height']}px;"
                f"opacity:{l.get('opacity', 1)};")
        if l.get("blend"):
            rule += f"mix-blend-mode:{l['blend']};"
        rule += "}"
        items_css.append(rule)

        # HTML: nut bam thi boc trong <a>, con lai la <img>
        if _is_interactive(l):
            items_html.append(
                f'<a class="node {cls}" href="#" title="{alt}">'
                f'<img src="{l["asset"]}" alt="{alt}"></a>'
            )
        else:
            items_html.append(f'<img class="node {cls}" src="{l["asset"]}" alt="{alt}">')

    body = "".join("\n    " + x for x in items_html)
    script = f"""
<script>
(function(){{
  var wrap=document.querySelector('.stage-wrap'),stage=document.querySelector('.stage');
  var W={cw},H={stage_h};
  function fit(){{
    var s=Math.min(1, wrap.clientWidth/W);
    stage.style.transform='scale('+s+')';
    wrap.style.height=(H*s)+'px';
  }}
  window.addEventListener('resize',fit); fit();
}})();
</script>"""

    html_doc = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_mod.escape(layout.get('source', 'Landing'))}</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="stage-wrap">
  <div class="stage">{body}
  </div>
</div>{script}
</body>
</html>
"""
    (out_dir / "index.html").write_text(html_doc, encoding="utf-8")
    (out_dir / "style.css").write_text("\n".join(items_css) + "\n", encoding="utf-8")
    n_hot = sum(1 for l in layers if _is_interactive(l))
    print(f"[slices] {len(layers)} anh | {n_hot} nut bam | cao {stage_h}px (cat bo {ch-stage_h}px thua)")
    print(f"[slices] -> {out_dir/'index.html'} + style.css")
    return out_dir / "index.html"


if __name__ == "__main__":
    import sys
    render(sys.argv[1] if len(sys.argv) > 1 else "output")
