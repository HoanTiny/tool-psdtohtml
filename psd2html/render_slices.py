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

    # Phat hien thanh CO DINH (nav/logo lap o moi section) -> render 1 lan, bo ban trung.
    from .fixed_overlay import detect_fixed_overlay
    fixed_items, drop_ids = detect_fixed_overlay(out_dir, layout)

    layers = [l for l in layout["layers"] if l.get("asset") and l["id"] not in drop_ids]

    # Chieu cao thuc: cat theo ANH COMPOSITE that - chi bo cac dong TRONG (dong mau)
    # o day, giu lai moi dong con hinh (ke ca nen trang tri footer nhu seu/song vang).
    stage_h = _content_bottom_from_image(out_dir / layout.get("screenshot", "screenshot.png"), ch)

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
        # moi SECTION la 1 lop rieng: content-visibility bo qua render section ngoai
        # man hinh -> cuon muot hon, do hoa nang khong ve het cung luc.
        f".stage .sec {{ position: absolute; left: 0; width: {cw}px; content-visibility: auto; }}",
    ]

    def _item_html_css(l, top, lazy=True):
        """Tra ve (html, css_rule) cho 1 layer, top tinh theo container chua no."""
        b = l["bbox"]
        cls = l["id"]
        alt = l["text"]["content"] if (l.get("text") and l["text"].get("content")) else l.get("name", "")
        alt = html_mod.escape(_norm(alt), quote=True)
        rule = (f".stage .{cls}{{left:{b['x']}px;top:{top}px;"
                f"width:{b['width']}px;height:{b['height']}px;opacity:{l.get('opacity', 1)};")
        if l.get("blend"):
            rule += f"mix-blend-mode:{l['blend']};"
        rule += "}"
        # Section dau (above-the-fold) tai NGAY; section sau LAZY (chi tai khi cuon toi).
        load = ' loading="lazy"' if lazy else ""
        if _is_interactive(l):
            h = (f'<a class="node {cls}" href="#" title="{alt}">'
                 f'<img src="{l["asset"]}" alt="{alt}"{load} decoding="async"></a>')
        else:
            h = f'<img class="node {cls}" src="{l["asset"]}" alt="{alt}"{load} decoding="async">'
        return h, rule

    sections = layout.get("sections")
    if sections:
        # Gom layer theo section (moi layer nam gon trong 1 section sau khi clip).
        groups = {i: [] for i in range(len(sections))}
        for l in layers:
            cy = l["bbox"]["y"] + l["bbox"]["height"] / 2
            idx = next((i for i, s in enumerate(sections) if s["y0"] <= cy < s["y1"]), 0)
            groups[idx].append(l)
        blocks = []
        for i, s in enumerate(sections):
            y0, hb = s["y0"], s["y1"] - s["y0"]
            items_css.append(f".stage .sec{i}{{top:{y0}px;height:{hb}px;"
                             f"contain-intrinsic-size:{cw}px {hb}px;}}")
            inner = []
            for l in groups[i]:
                h, rule = _item_html_css(l, l["bbox"]["y"] - y0, lazy=(i > 0))  # section 0 tai ngay
                items_css.append(rule)
                inner.append(h)
            blocks.append(f'<div class="sec sec{i}">'
                          + "".join("\n      " + x for x in inner) + "\n    </div>")
        body = "".join("\n    " + b for b in blocks)
    else:
        html_list = []
        for l in layers:
            h, rule = _item_html_css(l, l["bbox"]["y"])  # top tuyet doi
            items_css.append(rule)
            html_list.append(h)
        body = "".join("\n    " + x for x in html_list)

    # ---- Thanh CO DINH (nav/logo): render 1 lan, position:fixed, scale cung he so ----
    fixed_html, fixed_block = "", ""
    if fixed_items:
        items_css.append(".fixed-wrap{position:fixed;top:0;left:0;width:100%;height:0;"
                         "z-index:1000;pointer-events:none;}")
        items_css.append(f".fixed-stage{{position:absolute;top:0;left:0;width:{cw}px;"
                         f"height:{stage_h}px;transform-origin:top left;}}")
        items_css.append(".fixed-stage .node{position:absolute;display:block;pointer-events:auto;}")
        items_css.append(".fixed-stage a.node{cursor:pointer;transition:filter .15s ease;}")
        items_css.append(".fixed-stage a.node:hover{filter:brightness(1.12);}")
        fx = []
        for it in fixed_items:
            cls = it["id"]
            alt = html_mod.escape(_norm(it.get("alt", "")), quote=True)
            rule = (f".fixed-stage .{cls}{{left:{it['x']}px;top:{it['y']}px;"
                    f"width:{it['w']}px;height:{it['h']}px;opacity:{it.get('o', 1)};")
            if it.get("blend"):
                rule += f"mix-blend-mode:{it['blend']};"
            rule += "}"
            items_css.append(rule)
            if it.get("href"):
                fx.append(f'<a class="node {cls}" href="{it["href"]}" title="{alt}">'
                          f'<img src="{it["asset"]}" alt="{alt}"></a>')
            else:
                fx.append(f'<img class="node {cls}" src="{it["asset"]}" alt="{alt}">')
        fixed_html = ('<div class="fixed-wrap"><div class="fixed-stage">'
                      + "".join("\n    " + x for x in fx) + "\n  </div></div>")
        fixed_block = ("\n  var fstage=document.querySelector('.fixed-stage');"
                       "\n    if(fstage) fstage.style.transform='scale('+s+')';")

    script = f"""
<script>
(function(){{
  var wrap=document.querySelector('.stage-wrap'),stage=document.querySelector('.stage');
  var W={cw},H={stage_h};
  function fit(){{
    var s=Math.min(1, wrap.clientWidth/W);
    stage.style.transform='scale('+s+')';
    wrap.style.height=(H*s)+'px';{fixed_block}
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
{fixed_html}
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
    if fixed_items:
        print(f"[slices] {len(fixed_items)} phan tu CO DINH (nav/logo) -> render 1 lan (fixed)")
    print(f"[slices] -> {out_dir/'index.html'} + style.css")
    return out_dir / "index.html"


if __name__ == "__main__":
    import sys
    render(sys.argv[1] if len(sys.argv) > 1 else "output")
