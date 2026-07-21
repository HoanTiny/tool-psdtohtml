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
    "nhận quà", "đăng nhập", "đăng ký", "nạp thẻ", "nạp ngay", "nạp đầu",
    "cập nhật", "tải file", "tải ngay", "tải game", "app store", "google play", "apk",
    "thể lệ", "thông tin đăng", "lịch sử", "điều khoản", "facebook", "kiểm tra",
    "button", "btn", "menu ngang",
]

# Phan loai nut theo tu khoa -> "action" (key trong config LINKS de cam URL that).
# Thu tu quan trong: cum cu the hon dat truoc.
ACTION_KEYWORDS = [
    ("download", ["tải game", "tải ngay", "tải file", "app store", "google play", "apk"]),
    ("login", ["đăng nhập"]),
    ("register", ["đăng ký"]),
    ("topup", ["nạp thẻ", "nạp ngay", "nạp đầu"]),
    ("gift", ["nhận quà"]),
    ("check", ["kiểm tra"]),
    ("rules", ["thể lệ", "điều khoản"]),
    ("history", ["lịch sử"]),
    ("update", ["cập nhật"]),
    ("info", ["thông tin đăng"]),
    ("social", ["facebook"]),
]


def _action_of(layer):
    """Doan 'action' cua 1 nut (download/login/topup/gift...) tu ten/chu de gan URL."""
    hay = _norm(layer.get("name"))
    txt = _norm(layer.get("text", {}).get("content") if layer.get("text") else "")
    for action, kws in ACTION_KEYWORDS:
        for kw in kws:
            if kw in hay or kw in txt:
                return action
    return "other"


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


def render(out_dir, swiper=False):
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
        # moi SECTION la 1 lop rieng (position:absolute). KHONG dung content-visibility
        # vi ket hop voi .stage transform:scale() -> trinh duyet tinh nham section
        # 'ngoai man hinh' -> khong paint -> section bi DEN. Lazy-load anh la du de muot.
        f".stage .sec {{ position: absolute; left: 0; width: {cw}px; }}",
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
            act = _action_of(l)
            h = (f'<a class="node hot {cls}" href="#" data-action="{act}" title="{alt}">'
                 f'<img src="{l["asset"]}" alt="{alt}"{load} decoding="async"></a>')
        else:
            h = f'<img class="node {cls}" src="{l["asset"]}" alt="{alt}"{load} decoding="async">'
        return h, rule

    sections = layout.get("sections")
    swiper = swiper and bool(sections)  # swiper chi co nghia khi co nhieu section
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
            items_css.append(f".stage .sec{i}{{top:{y0}px;height:{hb}px;}}")
            inner = []
            for l in groups[i]:
                h, rule = _item_html_css(l, l["bbox"]["y"] - y0, lazy=(i > 0))  # section 0 tai ngay
                items_css.append(rule)
                inner.append(h)
            rev = "" if (i == 0 or swiper) else " reveal"  # swiper dung fade rieng, khong reveal
            blocks.append(f'<section id="sec{i}" class="sec sec{i}{rev}" data-sec="{i}">'
                          + "".join("\n      " + x for x in inner) + "\n    </section>")
        body = "".join("\n    " + b for b in blocks)
    else:
        html_list = []
        for l in layers:
            h, rule = _item_html_css(l, l["bbox"]["y"])  # top tuyet doi
            items_css.append(rule)
            html_list.append(h)
        body = "".join("\n    " + x for x in html_list)

    # ---- CSS tuong tac: hover nut, nav active, modal (+ swiper hoac reveal) ----
    items_css += [
        # Nut/lien ket bam: hover phong nhe + sang + glow (chi khi co JS de tranh nhay).
        ".stage .hot{cursor:pointer;transition:transform .18s ease,filter .18s ease;transform-origin:center;}",
        ".stage .hot:hover{transform:scale(1.06);filter:brightness(1.15) "
        "drop-shadow(0 0 14px rgba(255,214,120,.55));z-index:60;}",
        ".stage .hot:active{transform:scale(.98);}",
        # Modal popup
        ".modal-bg{position:fixed;inset:0;background:rgba(4,8,20,.72);display:none;"
        "align-items:center;justify-content:center;z-index:3000;opacity:0;transition:opacity .25s ease;}",
        ".modal-bg.show{display:flex;opacity:1;}",
        ".modal{position:relative;background:#111a2e;border:1px solid #33507e;border-radius:16px;"
        "padding:30px 34px;max-width:420px;width:90%;color:#e8eeff;text-align:center;"
        "transform:scale(.9);transition:transform .25s ease;box-shadow:0 20px 60px rgba(0,0,0,.5);}",
        ".modal-bg.show .modal{transform:scale(1);}",
        ".modal h3{margin:0 0 10px;font-size:20px;}",
        ".modal p{margin:0 0 20px;color:#9db0d6;font-size:14px;line-height:1.5;}",
        ".modal .mbtn{background:linear-gradient(90deg,#2563eb,#3b82f6);color:#fff;border:0;"
        "border-radius:9px;padding:11px 26px;font-weight:700;cursor:pointer;font-size:15px;}",
        ".modal .mx{position:absolute;top:8px;right:14px;background:none;border:0;color:#7d90b5;"
        "font-size:24px;cursor:pointer;line-height:1;}",
    ]
    if swiper:
        # Che do SWIPER full-page kieu FADE (giong swiper effect:'fade'): cac section
        # chong len nhau, crossfade opacity khi chuyen -> muot, khong giat kieu truot.
        max_sec_h = max(s["y1"] - s["y0"] for s in sections)
        items_css += [
            "html,body{height:100%;overflow:hidden;}",
            ".deck{position:fixed;inset:0;overflow:hidden;background:#000;"
            "display:flex;align-items:center;justify-content:center;}",
            # flex:none + width co dinh: khong cho flex co stage tu 1920 -> viewport
            # (neu co, se bi co 2 lan: 1 lan flex + 1 lan transform scale -> o nho ti hon giua).
            f".deck .stage{{margin:0;flex:none;width:{cw}px;transform-origin:center center;height:{max_sec_h}px;}}",
            ".deck .stage section.sec{top:0 !important;opacity:0;transition:opacity .5s ease;"
            "pointer-events:none;}",
            ".deck .stage section.sec.on{opacity:1;pointer-events:auto;z-index:2;}",
        ]
    else:
        items_css += [
            # Che do CUON: section (tru dau) fade-up khi vao man hinh.
            "body.js .stage section.sec.reveal{opacity:0;transform:translateY(28px);"
            "transition:opacity .6s ease,transform .6s ease;}",
            "body.js .stage section.sec.reveal.in{opacity:1;transform:none;}",
        ]

    # ---- Thanh CO DINH (nav/logo): render 1 lan, position:fixed, scale cung he so ----
    fixed_html, fixed_block, nav_count = "", "", 0
    if fixed_items:
        items_css.append(".fixed-wrap{position:fixed;top:0;left:0;width:100%;height:0;"
                         "z-index:1000;pointer-events:none;}")
        items_css.append(f".fixed-stage{{position:absolute;top:0;left:0;width:{cw}px;"
                         f"height:{stage_h}px;transform-origin:top left;}}")
        items_css.append(".fixed-stage .node{position:absolute;display:block;pointer-events:auto;}")
        items_css.append(".fixed-stage .navitem{cursor:pointer;transition:transform .18s ease,"
                         "filter .2s ease;transform-origin:center;}")
        items_css.append(".fixed-stage .navitem:hover{transform:scale(1.1);filter:brightness(1.25);}")
        items_css.append(".fixed-stage .navitem.active{filter:brightness(1.4) "
                         "drop-shadow(0 0 10px rgba(255,214,120,.85));}")
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
            # muc menu bam duoc: chu ngan (loai logo to, icon chuot cao, duong ke mong)
            is_nav = bool(it.get("alt")) and 15 <= it["w"] <= 220 and 15 <= it["h"] <= 60
            if is_nav:
                fx.append(f'<a class="node navitem {cls}" href="#" data-nav="{nav_count}" title="{alt}">'
                          f'<img src="{it["asset"]}" alt="{alt}" decoding="async"></a>')
                nav_count += 1
            else:
                fx.append(f'<img class="node {cls}" src="{it["asset"]}" alt="{alt}" decoding="async">')
        fixed_html = ('<div class="fixed-wrap"><div class="fixed-stage">'
                      + "".join("\n    " + x for x in fx) + "\n  </div></div>")
        fixed_block = ("\n    var fstage=document.querySelector('.fixed-stage');"
                       "\n    if(fstage) fstage.style.transform='scale('+s+')';")

    modal_html = ('<div class="modal-bg" id="modal">'
                  '<div class="modal"><button class="mx" data-close>&times;</button>'
                  '<h3 id="m-title">Thông báo</h3><p id="m-desc"></p>'
                  '<button class="mbtn" data-close>Đóng</button></div></div>')

    # JS chung: cau hinh link, modal, nut bam (dung .replace de tranh escape f-string)
    common_ui = r'''
  var LINKS = { download:"", login:"", register:"", topup:"", gift:"", rules:"", history:"", social:"", check:"" };
  var LABELS = { download:"Tải game", login:"Đăng nhập", register:"Đăng ký", topup:"Nạp", gift:"Nhận quà", rules:"Thể lệ", history:"Lịch sử", social:"Facebook", check:"Kiểm tra" };
  var modal=document.getElementById('modal'), mTitle=document.getElementById('m-title'), mDesc=document.getElementById('m-desc');
  function openModal(t,d){ mTitle.textContent=t; mDesc.textContent=d; modal.classList.add('show'); }
  function closeModal(){ modal.classList.remove('show'); }
  modal.addEventListener('click',function(e){ if(e.target===modal||e.target.hasAttribute('data-close')) closeModal(); });
  document.addEventListener('keydown',function(e){ if(e.key==='Escape') closeModal(); });
  document.querySelectorAll('.hot').forEach(function(a){ a.addEventListener('click',function(e){ e.preventDefault();
    var act=a.getAttribute('data-action')||'other', url=LINKS[act];
    if(url){ window.open(url,'_blank'); return; }
    openModal(LABELS[act]||'Thông báo','Chức năng "'+(LABELS[act]||act)+'": điền URL vào LINKS.'+act+' hoặc gọi API tại đây.'); }); });
'''
    fixed_scale = ("var fstage=document.querySelector('.fixed-stage'); "
                   "if(fstage) fstage.style.transform='scale('+s+')';")

    if swiper:
        body_wrap = f'<div class="deck">\n  <div class="stage">{body}\n  </div>\n</div>'
        js = (r'''
<script>
(function(){
  document.body.classList.add('js','swiper');
  var deck=document.querySelector('.deck'), stage=document.querySelector('.stage');
  var W=__CW__;
  var secs=[].slice.call(document.querySelectorAll('.stage section.sec'));
  var navs=[].slice.call(document.querySelectorAll('.fixed-stage .navitem'));
  var s=1, idx=0, lock=false, N=secs.length;
  function go(i){
    idx = Math.max(0, Math.min(N-1, i));
    // crossfade: chi section idx sang (opacity 1), con lai mo di
    secs.forEach(function(sc,k){ sc.classList.toggle('on', k===idx); });
    navs.forEach(function(n,k){ n.classList.toggle('active', k===Math.min(idx, navs.length-1)); });
  }
  function fit(){ s = Math.min(1, deck.clientWidth/W); stage.style.transform='scale('+s+')'; __FIXEDSCALE__ }
  // Ep repaint: dat transform 'none' roi reflow roi scale lai -> tranh loi layer
  // scale khong duoc ve (section bi DEN cho toi khi resize), nhat la che do swiper.
  function kick(){ stage.style.transform='none'; void stage.offsetHeight; fit(); }
  window.addEventListener('resize', fit); fit(); go(0);
  window.addEventListener('load', kick); requestAnimationFrame(kick); setTimeout(kick, 300);
  function step(d){ if(lock) return; lock=true; setTimeout(function(){lock=false;}, 650); go(idx+d); }
  deck.addEventListener('wheel', function(e){ e.preventDefault(); if(Math.abs(e.deltaY)<8) return; step(e.deltaY>0?1:-1); }, {passive:false});
  window.addEventListener('keydown', function(e){
    if(e.key==='ArrowDown'||e.key==='PageDown'){ e.preventDefault(); step(1); }
    else if(e.key==='ArrowUp'||e.key==='PageUp'){ e.preventDefault(); step(-1); } });
  var ty=null;
  deck.addEventListener('touchstart', function(e){ ty=e.touches[0].clientY; }, {passive:true});
  deck.addEventListener('touchend', function(e){ if(ty==null) return;
    var dy=ty-e.changedTouches[0].clientY; if(Math.abs(dy)>40) step(dy>0?1:-1); ty=null; });
  navs.forEach(function(n,i){ n.addEventListener('click', function(e){ e.preventDefault(); go(Math.min(i, N-1)); }); });
__COMMON__
})();
</script>'''
              .replace("__CW__", str(cw))
              .replace("__FIXEDSCALE__", fixed_scale)
              .replace("__COMMON__", common_ui))
    else:
        body_wrap = f'<div class="stage-wrap">\n  <div class="stage">{body}\n  </div>\n</div>'
        js = (r'''
<script>
(function(){
  document.body.classList.add('js');
  var wrap=document.querySelector('.stage-wrap'), stage=document.querySelector('.stage');
  var W=__CW__, H=__H__;
  function fit(){ var s=Math.min(1, wrap.clientWidth/W); stage.style.transform='scale('+s+')'; wrap.style.height=(H*s)+'px'; __FIXEDSCALE__ }
  // Ep repaint sau khi tai xong -> tranh loi layer scale khong duoc ve (bi DEN).
  function kick(){ stage.style.transform='none'; void stage.offsetHeight; fit(); }
  window.addEventListener('resize', fit); fit();
  window.addEventListener('load', kick); requestAnimationFrame(kick); setTimeout(kick, 300);
  var secs=[].slice.call(document.querySelectorAll('.stage section.sec'));
  var navs=[].slice.call(document.querySelectorAll('.fixed-stage .navitem'));
  var N=secs.length;
  function topOf(el){ return el.getBoundingClientRect().top + window.scrollY; }
  navs.forEach(function(n,i){ n.addEventListener('click', function(e){ e.preventDefault();
    var t=secs[Math.min(i,N-1)]; if(t) window.scrollTo({top:Math.max(0,topOf(t)-4), behavior:'smooth'}); }); });
  function onScroll(){ var mid=window.scrollY+window.innerHeight*0.4, revealLine=window.scrollY+window.innerHeight*0.88, cur=0;
    secs.forEach(function(s,i){ var top=topOf(s); if(top<=mid) cur=i; if(top<revealLine) s.classList.add('in'); });
    navs.forEach(function(n,i){ n.classList.toggle('active', i===cur); }); }
  window.addEventListener('scroll', onScroll, {passive:true}); window.addEventListener('resize', onScroll); onScroll();
  setTimeout(function(){ secs.forEach(function(s){ s.classList.add('in'); }); }, 2500);
__COMMON__
})();
</script>'''
              .replace("__CW__", str(cw))
              .replace("__H__", str(stage_h))
              .replace("__FIXEDSCALE__", fixed_scale)
              .replace("__COMMON__", common_ui))

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
{body_wrap}
{modal_html}{js}
</body>
</html>
"""
    (out_dir / "index.html").write_text(html_doc, encoding="utf-8")
    (out_dir / "style.css").write_text("\n".join(items_css) + "\n", encoding="utf-8")
    n_hot = sum(1 for l in layers if _is_interactive(l))
    mode = "swiper" if swiper else "cuon"
    print(f"[slices/{mode}] {len(layers)} anh | {n_hot} nut bam | cao {stage_h}px (cat bo {ch-stage_h}px thua)")
    if fixed_items:
        print(f"[slices] {len(fixed_items)} phan tu CO DINH (nav/logo) -> render 1 lan (fixed)")
    print(f"[slices] -> {out_dir/'index.html'} + style.css")
    return out_dir / "index.html"


if __name__ == "__main__":
    import sys
    render(sys.argv[1] if len(sys.argv) > 1 else "output")
