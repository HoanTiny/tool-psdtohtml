"""
Pha 2 - AI converter (can ANTHROPIC_API_KEY).

Nhiem vu:
  - Doc layout.json + screenshot.png tu Pha 1.
  - Gui cho Claude: anh screenshot (de AI 'nhin' tong the) + JSON layout
    (de AI biet chinh xac text, toa do, mau, ten file asset).
  - Nhan ve HTML + CSS semantic, responsive.
  - Ghi ra index.html va style.css trong cung thu muc output.

Y tuong: Python lo phan 'may lam gioi' (doc PSD chinh xac),
AI lo phan 'nguoi lam gioi' (nhin bo cuc, dat semantic tag, viet CSS responsive).
"""

import base64
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from PIL import Image

from .sectionize import split_sections, is_background

# Model mac dinh: sonnet-5 (nhanh, re, du tot cho sinh code + doc anh).
# Muon chat luong cao nhat co the doi sang "claude-opus-4-8".
DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """\
Ban la chuyen gia frontend chuyen chuyen thiet ke sang HTML/CSS sach.
Ban nhan mot anh chup thiet ke (tu file PSD) va mot mo ta JSON cac layer
(kem toa do pixel, noi dung chu, mau sac, va ten file asset da xuat san).

Nhiem vu: tao ra HTML + CSS tai hien trung thanh thiet ke, nhung PHAI:
- Dung the semantic (header, nav, main, section, button, h1..h3, p...) thay vi div vo nghia.
- Bo cuc bang Flexbox/Grid, KHONG dung position:absolute tran lan.
- Responsive co ban (dung max-width, %, rem; co 1 media query cho mobile neu hop ly).
- Voi layer chu: viet thang text vao HTML, style bang CSS (font-size, color lay tu JSON).
- Voi layer anh/icon: dung <img src="assets/Lx.png"> dung theo truong 'asset' trong JSON.
- Mau nen, khoang cach uoc luong tu toa do trong JSON va anh.
- CSS gon gang, dat trong file rieng, dung bien CSS cho mau chinh.

Tra ve DUNG dinh dang sau, khong giai thich them:
```html
<!-- toan bo noi dung file index.html, co <link rel="stylesheet" href="style.css"> -->
```
```css
/* toan bo noi dung file style.css */
```
"""


SECTION_SYSTEM_PROMPT = """\
Ban la chuyen gia frontend. Ban dang chuyen MOT SECTION (mot khoi ngang) cua
mot trang landing tu thiet ke PSD sang HTML/CSS.

Ban nhan:
- Anh 1: 'reference' - anh chup section (ca nen lan noi dung) de ban nhin bo cuc.
- Mo ta JSON cac layer trong section (toa do da tinh theo goc TRAI-TREN cua section,
  don vi px; kem noi dung chu, font, mau, va ten file asset da xuat).
- Kich thuoc section: rong x cao (px).

Yeu cau:
- Tra ve MOT the <section class="s{idx}-root"> ... </section> (fragment, khong <html>/<body>).
- Day la trang promo game KHO CO DINH rong DUNG {width}px. Section root phai
  width:{width}px; height:{height}px; position:relative; margin:0 auto;
  va nen `background:url('sections/bg{idx}.png') center top/cover no-repeat`.
- QUAN TRONG NHAT - DAT DUNG VI TRI: moi phan tu foreground dung position:absolute
  voi left/top/width/height LAY CHINH XAC tu bbox trong JSON (don vi px). KHONG
  dung flow/margin lam le vi tri. Muc tieu la trong khop thiet ke tung pixel.
- Van dung the semantic (h2, p, button, ul/li, img) cho dung ngu nghia, nhung
  moi cai deu position:absolute theo toa do JSON.
- Layer anh nhan vat/icon: <img src="assets/Lx.png"> theo truong 'asset', dat dung bbox.
- Voi nhom item lap lai (vd 7 o diem danh) van position:absolute tung cai theo JSON.
- Tien to MOI class bang 's{idx}-'. Text lay dung noi dung tieng Viet co dau tu JSON.

Tra ve DUNG dinh dang, khong giai thich:
```html
<section class="s{idx}-root"> ... </section>
```
```css
/* CSS cho section {idx}, moi class deu bat dau bang s{idx}- */
```
"""


def _img_b64(path):
    return base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")


def _pil_b64(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _extract_blocks(text):
    """Tach 2 khoi ```html``` va ```css``` tu cau tra loi cua AI."""
    html_m = re.search(r"```html\s*(.*?)```", text, re.S)
    css_m = re.search(r"```css\s*(.*?)```", text, re.S)
    html = html_m.group(1).strip() if html_m else ""
    css = css_m.group(1).strip() if css_m else ""
    return html, css


def convert(out_dir, model=DEFAULT_MODEL, api_key=None):
    """
    Doc output/layout.json + output/screenshot.png, goi Claude, ghi index.html + style.css.
    """
    out_dir = Path(out_dir)
    layout = json.loads((out_dir / "layout.json").read_text(encoding="utf-8"))
    screenshot = out_dir / layout.get("screenshot", "screenshot.png")

    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    print(f"[AI] Gui thiet ke cho {model} ...")
    message = client.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _img_b64(screenshot),
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Day la thiet ke can chuyen. Kich thuoc canvas: "
                            f"{layout['canvas']['width']}x{layout['canvas']['height']}px.\n\n"
                            "Mo ta cac layer (JSON):\n"
                            f"{json.dumps(layout['layers'], ensure_ascii=False, indent=2)}"
                        ),
                    },
                ],
            }
        ],
    )

    reply = "".join(b.text for b in message.content if b.type == "text")
    html, css = _extract_blocks(reply)
    if not html:
        # Neu khong parse duoc, luu nguyen cau tra loi de debug
        (out_dir / "ai_raw_reply.txt").write_text(reply, encoding="utf-8")
        raise RuntimeError("Khong tach duoc HTML tu cau tra loi. Xem output/ai_raw_reply.txt")

    (out_dir / "index.html").write_text(html, encoding="utf-8")
    if css:
        (out_dir / "style.css").write_text(css, encoding="utf-8")

    usage = message.usage
    print(f"[AI] Xong. Token: in={usage.input_tokens}, out={usage.output_tokens}")
    print(f"[AI] Ghi: {out_dir/'index.html'}" + (f" + {out_dir/'style.css'}" if css else ""))
    return out_dir / "index.html"


def _build_bg_plate(out_dir, layout):
    """Ghep cac layer nen toan trang thanh 1 anh nen full trang (khong co foreground)."""
    out_dir = Path(out_dir)
    canvas = layout["canvas"]
    plate = Image.new("RGBA", (canvas["width"], canvas["height"]), (255, 255, 255, 255))
    for l in layout["layers"]:
        if l.get("kind") == "group":
            continue
        if not is_background(l, canvas["width"], canvas["height"]):
            continue  # chi lay layer nen (cung tieu chi voi sectionize)
        asset = l.get("asset")
        if not asset:
            continue
        try:
            img = Image.open(out_dir / asset).convert("RGBA")
            plate.paste(img, (l["bbox"]["x"], l["bbox"]["y"]), img)
        except Exception:
            pass
    return plate


def _fallback_section(sec):
    """Neu AI that bai: dung tam 1 section chi hien anh nen (khong de trang trong)."""
    i, h = sec["index"], sec["height"]
    html = f'<section class="s{i}-root"></section>'
    css = (f'.s{i}-root{{position:relative;width:100%;height:{h}px;'
           f"background:url('sections/bg{i}.png') center top/cover no-repeat;}}")
    return html, css


def _convert_one_section(client, model, sec, ref_crop, max_tokens=16000, retries=1):
    """Goi AI cho 1 section, tra ve (index, html, css, usage). Retry neu parse loi."""
    system = SECTION_SYSTEM_PROMPT.format(idx=sec["index"], height=sec["height"], width=ref_crop.width)
    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _pil_b64(ref_crop)}},
        {"type": "text", "text": (
            f"Section #{sec['index']}. Kich thuoc: {ref_crop.width}x{sec['height']}px.\n\n"
            "Layer trong section (JSON):\n"
            f"{json.dumps(sec['layers'], ensure_ascii=False, indent=2)}"
        )},
    ]
    last_usage = None
    for attempt in range(retries + 1):
        message = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        last_usage = message.usage
        reply = "".join(b.text for b in message.content if b.type == "text")
        html, css = _extract_blocks(reply)
        if html:
            return sec["index"], html, css, last_usage
        # het token -> giam bot yeu cau o lan sau (van giu 1 lan retry)
    # That bai sau khi retry -> dung fallback nen
    html, css = _fallback_section(sec)
    return sec["index"], html, css, last_usage


def convert_sectioned(out_dir, model=DEFAULT_MODEL, api_key=None, target_h=1300, max_workers=4):
    """
    Chuyen 1 trang PSD dai: cat thanh section, chuyen tung section song song, roi ghep.
    Ghi ra index.html + style.css + thu muc sections/ (nen tung section).
    """
    out_dir = Path(out_dir)
    layout = json.loads((out_dir / "layout.json").read_text(encoding="utf-8"))
    full = Image.open(out_dir / layout.get("screenshot", "screenshot.png")).convert("RGB")

    sections = split_sections(layout, target_h=target_h)
    print(f"[AI] Cat thanh {len(sections)} section, chuyen song song ({max_workers} luong)...")

    # Xuat anh nen tung section
    sec_dir = out_dir / "sections"
    sec_dir.mkdir(exist_ok=True)
    plate = _build_bg_plate(out_dir, layout)
    ref_crops = {}
    for sec in sections:
        i, y0, y1 = sec["index"], sec["y0"], sec["y1"]
        plate.crop((0, y0, layout["canvas"]["width"], y1)).convert("RGB").save(sec_dir / f"bg{i}.png")
        ref_crops[i] = full.crop((0, y0, layout["canvas"]["width"], y1))

    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    results = {}
    total_in = total_out = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_convert_one_section, client, model, sec, ref_crops[sec["index"]])
                for sec in sections]
        for f in futs:
            idx, html, css, usage = f.result()
            results[idx] = (html, css)
            total_in += usage.input_tokens
            total_out += usage.output_tokens
            print(f"      section #{idx} xong ({len(html)} ky tu HTML)")

    # Ghep lai theo thu tu
    body = "\n".join(results[i][0] for i in sorted(results) if results[i][0])
    css_all = "\n".join(results[i][1] for i in sorted(results) if results[i][1])

    html_doc = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{layout.get('source', 'Landing')}</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
{body}
</body>
</html>
"""
    css_doc = "* { margin: 0; padding: 0; box-sizing: border-box; }\nbody { font-family: Arial, sans-serif; }\n\n" + css_all

    (out_dir / "index.html").write_text(html_doc, encoding="utf-8")
    (out_dir / "style.css").write_text(css_doc, encoding="utf-8")
    print(f"[AI] Xong. Token: in={total_in}, out={total_out}")
    print(f"[AI] Ghi: {out_dir/'index.html'} + {out_dir/'style.css'}")
    return out_dir / "index.html"


if __name__ == "__main__":
    import sys

    d = sys.argv[1] if len(sys.argv) > 1 else "output"
    convert_sectioned(d)
