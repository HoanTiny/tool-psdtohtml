"""
AI "prod-hoa" tung SECTION (can ANTHROPIC_API_KEY).

Y tuong: giu do CHINH XAC cua bBan absolute-image, nhung nho AI nang cap:
 - Layer CHU THUONG (menu, so, mo ta) -> render THANH TEXT THAT (h2/p/span) de
   net (retina) + tot SEO; layer chu CACH DIEU (logo, tieu de co hieu ung) giu <img>.
 - Nut CTA (nap/dang nhap/nhan qua...) -> boc <button> co hover.
 - Moi phan tu van position:absolute dung bbox -> khop thiet ke.

Chi lam FOREGROUND (nen van do Background/bg pipeline san lo) -> ghep sach vao
luong export hien co. Moi section 1 lan goi AI, chay song song.
"""

import base64
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from .ai_convert import _load_env, DEFAULT_MODEL

_SYS = """Ban la chuyen gia React frontend. Ban nhan 1 anh chup MOT SECTION landing game va JSON cac layer FOREGROUND (toa do px theo goc trai-tren section).

Tao 1 React component (JSX thuan, khong TypeScript) ten __COMP__ tai hien cac layer FOREGROUND nay PIXEL-PERFECT bang position:absolute theo dung bbox. QUY TAC:
- Layer co 'text' la CHU THUONG de doc (menu, so lieu, mo ta ngan): render THANH TEXT THAT bang the semantic (h2/h3/p/span) voi style {position:'absolute',left,top,fontSize:size,color} lay tu JSON. KHONG dung <img>. Neu text nhieu dong dung whiteSpace:'pre-line'.
- Layer chu CACH DIEU/NGHE THUAT (logo, tieu de lon co gradient/vien/glow) hoac layer khong co 'text': GIU <img src={asset}> dat dung bbox.
- Layer la NUT CTA (alt/text chua: nap, dang nhap, dang ky, nhan qua, kiem tra, tai game, the le, lich su): boc trong <button> voi className "transition hover:brightness-110 hover:scale-105 cursor-pointer" va style position:absolute dung bbox; ben trong dat <img> hoac text.
- KHONG ve nen toan man (background da co san o noi khac) - chi ve cac layer trong JSON.
- Root: <div className="absolute inset-0"> ... </div> (KHONG dat width/height co dinh).
- Chi dung asset qua thuoc tinh 'asset' trong JSON. Giu nguyen mau/opacity/blend neu co.

Chi tra ve DUNG 1 khoi:
```jsx
export default function __COMP__(props) { ... }
```
Khong giai thich gi them."""


def _pil_b64(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _extract_jsx(text):
    m = re.search(r"```(?:jsx|tsx|js)?\s*(.*?)```", text, re.S)
    return (m.group(1).strip() if m else text.strip())


def _enhance_one(client, model, comp, shot_crop, layers, w, h):
    sys = _SYS.replace("__COMP__", comp)
    msg = client.messages.create(
        model=model, max_tokens=8000, system=sys,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": _pil_b64(shot_crop)}},
            {"type": "text", "text": f"Section {w}x{h}px. Component ten: {comp}.\n"
                                     f"Layers FOREGROUND (JSON):\n{json.dumps(layers, ensure_ascii=False)}"}]}],
    )
    reply = "".join(b.text for b in msg.content if b.type == "text")
    jsx = _extract_jsx(reply)
    return comp, jsx, msg.usage


def enhance_board(vdir, board, lang="js", model=DEFAULT_MODEL, api_key=None, max_workers=4):
    """
    Goi AI nang cap tung section trong board -> luu JSX vao sec['ai_jsx'].
    Chi xu ly foreground (sec['flat']); nen giu nguyen pipeline. Loi 1 section
    khong lam hong ca board (giu section do render kieu thuong).
    """
    import anthropic
    _load_env()
    vdir = Path(vdir)
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    layout = json.loads((vdir / "layout.json").read_text(encoding="utf-8"))
    style_by_id = {l["id"]: (l.get("text") or {}) for l in layout["layers"]}
    W = board["W"]
    try:
        shot = Image.open(vdir / layout.get("screenshot", "screenshot.png")).convert("RGB")
    except Exception:
        shot = None

    jobs = []
    for sec in board["sections"]:
        y0 = sec.get("y0", 0)
        # band cao = max day cua item trong section (foreground); an toan lay tu bbox
        items = sec.get("flat", [])
        if not items:
            continue
        band_h = max((it["y"] - y0) + it["h"] for it in items) if items else board["H"]
        band_h = min(board["H"] - y0, max(band_h, 1))
        crop = shot.crop((0, y0, W, y0 + band_h)) if shot else Image.new("RGB", (W, band_h))
        # layer foreground: doi toa do ve goc section + kem font/size/color
        lys = []
        for it in items:
            st = style_by_id.get(it["id"], {})
            lys.append({"id": it["id"], "asset": it["src"], "x": it["x"], "y": it["y"] - y0,
                        "w": it["w"], "h": it["h"], "o": it.get("o", 1), "blend": it.get("blend"),
                        "alt": it.get("alt"), "text": (st.get("content") or (it.get("alt") if it.get("t") else None)),
                        "font": st.get("font"), "size": st.get("size"), "color": st.get("color")})
        jobs.append((sec, crop, lys, band_h))

    total_in = total_out = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_enhance_one, client, model, sec["comp"], crop, lys, W, bh): sec
                for (sec, crop, lys, bh) in jobs}
        for f in futs:
            sec = futs[f]
            try:
                comp, jsx, usage = f.result()
                if jsx and "export default" in jsx:
                    sec["ai_jsx"] = jsx
                    total_in += usage.input_tokens
                    total_out += usage.output_tokens
                    print(f"      [AI] section {comp} xong ({len(jsx)} ky tu)")
                else:
                    print(f"      [AI] section {sec['comp']} loi parse -> giu ban thuong")
            except Exception as e:
                print(f"      [AI] section {sec['comp']} loi: {e} -> giu ban thuong")
    print(f"[AI] Enhance xong. Token in={total_in} out={total_out}")
    return board
