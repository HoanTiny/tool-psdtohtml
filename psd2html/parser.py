"""
Pha 1 - Parser PSD (Python thuan, KHONG can API).

Nhiem vu:
  1. Doc file PSD -> lay cay layer (ten, loai, toa do, opacity...).
  2. Voi layer chu (text): lay noi dung + font + mau + co chu.
  3. Voi layer anh/icon: xuat ra PNG trong thu muc assets/.
  4. Render toan bo PSD thanh 1 anh screenshot lam tham chieu cho AI.
  5. Xuat tat ca thanh 1 file JSON mo ta layout.

Dau ra JSON co dang:
{
  "canvas": {"width": 1440, "height": 900},
  "screenshot": "screenshot.png",
  "layers": [ {layer}, {layer}, ... ]   # da lam phang, theo thu tu ve
}

Moi {layer}:
{
  "id": "L3",
  "name": "Button Dang nhap",
  "kind": "type" | "pixel" | "shape" | "group" | "smartobject",
  "bbox": {"x": 120, "y": 340, "width": 200, "height": 48},
  "opacity": 1.0,
  "text": {"content": "...", "font": "...", "size": 16, "color": "#ffffff"},  # chi voi layer chu
  "asset": "assets/L3.png"   # chi voi layer anh
}
"""

import json
import os
from pathlib import Path

from PIL import Image
from psd_tools import PSDImage
from psd_tools.api.layers import Artboard

from .sectionize import is_background

# Cau hinh xuat asset (co the doi qua tham so parse_psd HOAC bien moi truong .env).
# fmt: 'webp' (nhe, mac dinh) hoac 'png' (goc, net nhat, nang).
# webp_quality: chat luong lossy cho anh lon (nen/nhan vat).
# webp_lossless_max: anh nho hon dien tich nay -> WEBP LOSSLESS (chu/icon/logo cang sac).
_ASSET_CFG = {"fmt": "webp", "quality": 92, "lossless_max": 300000}


def _apply_asset_cfg(asset_fmt=None, webp_quality=None, webp_lossless_max=None):
    """Cap nhat cau hinh asset: uu tien tham so truyen -> .env -> mac dinh."""
    fmt = (asset_fmt or os.environ.get("PSD2HTML_ASSET_FMT", "webp")).lower()
    q = int(webp_quality if webp_quality is not None else os.environ.get("PSD2HTML_WEBP_QUALITY", "92"))
    lm = int(webp_lossless_max if webp_lossless_max is not None
             else os.environ.get("PSD2HTML_WEBP_LOSSLESS_MAX", "300000"))
    _ASSET_CFG.update(fmt="png" if fmt == "png" else "webp", quality=q, lossless_max=lm)


def _save_asset(img, assets_dir, lid):
    """Luu asset theo cau hinh _ASSET_CFG. Tra ve ten file (vd L3.webp)."""
    if _ASSET_CFG["fmt"] == "png":
        name = f"{lid}.png"
        img.save(assets_dir / name)
    else:
        name = f"{lid}.webp"
        w, h = img.size
        if _ASSET_CFG["lossless_max"] and w * h <= _ASSET_CFG["lossless_max"]:
            img.save(assets_dir / name, "WEBP", lossless=True, method=6)   # chu/icon/logo: sac net
        else:
            img.save(assets_dir / name, "WEBP", quality=_ASSET_CFG["quality"], method=4)  # nen/nhan vat: nhe
    return name


def _load_env():
    """Nap .env o goc du an vao os.environ (de PSD2HTML_* trong .env co tac dung luc parse)."""
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent):
        env = base / ".env"
        if not env.exists():
            continue
        try:
            for line in env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and v and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass


def _overlay_ids(psd):
    """
    Tim cac layer thuoc MENU OVERLAY (group ten co 'menu' va cao > 40% trang).
    Tra ve set id() cua chung. Dung de LOAI khoi composite nguon-mau, tranh
    'bong ma' menu bi bake vao layer phia duoi (khi PSD thiet ke menu dang mo).
    """
    ids = set()

    def collect_all(layer):
        for s in layer:
            ids.add(id(s))
            if s.is_group():
                collect_all(s)

    def walk(layer):
        for s in layer:
            if s.is_group():
                l, t, r, b = s.bbox
                if "menu" in (s.name or "").lower() and (b - t) > 0.4 * psd.height:
                    collect_all(s)
                else:
                    walk(s)

    walk(psd)
    return ids


def _collect_artboards(psd):
    """
    Tim tat ca artboard trong PSD (neu co). Tra ve list {name, bbox}.
    PSD khong dung artboard -> tra ve [] (se coi ca canvas la 1 'artboard').
    """
    boards = []

    def walk(layer):
        for sub in layer:
            if isinstance(sub, Artboard):
                left, top, right, bottom = sub.bbox
                boards.append({
                    "name": (sub.name or "Artboard").replace("\x00", "").strip(),
                    "bbox": {"x": int(left), "y": int(top),
                             "width": int(right - left), "height": int(bottom - top)},
                })
            if sub.is_group():
                walk(sub)

    walk(psd)
    return boards


# Anh xa blend mode cua PSD -> gia tri CSS mix-blend-mode
_BLEND_MAP = {
    "MULTIPLY": "multiply", "SCREEN": "screen", "OVERLAY": "overlay",
    "DARKEN": "darken", "LIGHTEN": "lighten",
    "COLOR_DODGE": "color-dodge", "COLOR_BURN": "color-burn",
    "HARD_LIGHT": "hard-light", "SOFT_LIGHT": "soft-light",
    "DIFFERENCE": "difference", "EXCLUSION": "exclusion",
    "HUE": "hue", "SATURATION": "saturation", "COLOR": "color",
    "LUMINOSITY": "luminosity",
    "LINEAR_DODGE": "plus-lighter",  # xap xi
}


def _blend_css(layer):
    """Tra ve gia tri CSS mix-blend-mode, hoac None neu la normal/khong ho tro."""
    try:
        name = layer.blend_mode.name  # vd 'NORMAL', 'MULTIPLY'
        return _BLEND_MAP.get(name)
    except Exception:
        return None


def _bbox_to_dict(layer):
    """Chuyen bbox (left, top, right, bottom) cua psd-tools thanh x/y/width/height."""
    left, top, right, bottom = layer.bbox
    return {
        "x": int(left),
        "y": int(top),
        "width": int(right - left),
        "height": int(bottom - top),
    }


def _extract_text_style(layer):
    """
    Rut trich style co ban cua 1 layer chu: font, co chu, mau.
    Phan nay hoi 'mong manh' vi du lieu font nam sau trong engine_dict cua PSD,
    nen boc trong try/except - loi thi tra ve gia tri mac dinh.
    """
    style = {
        "content": layer.text or "",
        "font": None,
        "size": None,
        "color": None,
    }
    try:
        engine = layer.engine_dict
        # Lay style run dau tien (style cua ky tu dau tien cua doan van)
        style_run = engine["StyleRun"]["RunArray"][0]["StyleSheet"]["StyleSheetData"]

        # Co chu
        if "FontSize" in style_run:
            style["size"] = round(float(style_run["FontSize"]))

        # Mau chu: FillColor.Values = [alpha, R, G, B] trong khoang 0..1
        if "FillColor" in style_run:
            vals = style_run["FillColor"]["Values"]
            r, g, b = (int(round(c * 255)) for c in vals[1:4])
            style["color"] = f"#{r:02x}{g:02x}{b:02x}"

        # Ten font: tra cuu qua FontSet bang chi so Font
        font_index = style_run.get("Font", 0)
        font_set = layer.resource_dict["FontSet"]
        style["font"] = str(font_set[font_index]["Name"])
    except Exception:
        pass
    return style


def _is_blank(img):
    """Kiem tra anh co bi den/rong hoan toan khong (dung de phat hien composite loi)."""
    try:
        extrema = img.convert("RGB").getextrema()  # ((rmin,rmax),(gmin,gmax),(bmin,bmax))
        return all(lo == hi for lo, hi in extrema)
    except Exception:
        return True


def _mostly_white(img, thr=0.9):
    """
    Vung crop tu composite co gan nhu TOAN pixel trang khong (>thr).
    Dung phat hien vung bi loi blend cua psd-tools (NaN -> trang) de fallback.
    """
    try:
        import numpy as np
        a = np.asarray(img.convert("RGB"))
        near_white = (a.min(axis=2) > 248)
        return near_white.mean() >= thr
    except Exception:
        return False


def _mostly_dark(img, thr=0.92):
    """
    Vung crop co gan nhu TOAN pixel den (trong so cac pixel DAC) khong (>thr).
    Dung phat hien layer nen 'suy bien' (composite rieng ra den do la lop dieu
    chinh/fill da bake vao composite tong) -> fallback lay mau tu composite tong.
    """
    try:
        import numpy as np
        a = np.asarray(img.convert("RGBA"))
        alpha = a[..., 3]
        opaque = alpha > 8
        if opaque.mean() < 0.5:      # phan lon trong suot -> khong coi la nen den
            return False
        near_black = (a[..., :3].max(axis=2) < 16) & opaque
        return near_black.sum() / max(1, opaque.sum()) >= thr
    except Exception:
        return False


def _walk(layer, out, assets_dir, counter, canvas=None, real_comp=None, cw=0, ch=0, parent_id=None, overlay=None):
    """
    Duyet de quy cay layer, lam phang thanh danh sach `out`.
    - Group thi ghi lai roi duyet vao con.
    - Layer chu thi lay text style.
    - Layer anh/shape thi xuat PNG.
    - Moi node co `parent` = id group cha (de dung lai cay group ben codegen).
    Layer khong hien (visible=False) hoac rong thi bo qua.
    """
    for sub in layer:
        if not sub.visible:
            continue
        if sub.bbox == (0, 0, 0, 0):  # layer rong
            continue

        counter[0] += 1
        lid = f"L{counter[0]}"
        node = {
            "id": lid,
            "name": (sub.name or "").replace("\x00", "").strip(),
            "kind": sub.kind,
            "bbox": _bbox_to_dict(sub),
            "opacity": round(sub.opacity / 255, 2),
            "parent": parent_id,
        }
        blend = _blend_css(sub)
        if blend:
            node["blend"] = blend

        if sub.is_group():
            out.append(node)
            _walk(sub, out, assets_dir, counter, canvas, real_comp, cw, ch, parent_id=lid, overlay=overlay)
            continue

        # Composite rieng layer nay 1 lan (dung lay ALPHA/hinh dang + du phong)
        img = None
        try:
            img = sub.composite()
            if img is not None:
                img = img.convert("RGBA")
        except Exception:
            img = None

        # Layer chu: van luu noi dung text (de lam alt / tra cuu),
        # nhung VAN xuat ra PNG - vi chu cach dieu trong landing thuong la anh.
        if sub.kind == "type":
            node["text"] = _extract_text_style(sub)

        # Anh de xuat: mac dinh la composite rieng cua layer.
        export_img = img

        # Voi layer FOREGROUND: lay MAU tu composite tong (dung layer style:
        # gradient overlay, vien, glow...) + ALPHA tu layer -> chu/anh dung mau.
        # (Layer nen giu composite rieng vi crop tu tong se dinh ca foreground.)
        # Layer thuoc menu overlay: dung composite RIENG (real_comp da loai chung ra).
        b = node["bbox"]
        is_overlay = overlay is not None and id(sub) in overlay
        if (real_comp is not None and img is not None
                and not is_background(node, cw, ch) and not is_overlay):
            try:
                crop = real_comp.crop((b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]))
                crop = crop.convert("RGBA")
                # Neu vung composite nay bi TRANG/RONG (loi blend cua psd-tools) ->
                # dung composite RIENG cua layer (tranh nhan vat thanh bong trang).
                if _is_blank(crop) or _mostly_white(crop):
                    export_img = img
                else:
                    crop.putalpha(img.getchannel("A"))
                    export_img = crop
            except Exception:
                export_img = img
        # Layer NEN: mac dinh giu composite rieng. Nhung neu composite rieng SUY BIEN
        # (den/trang/rong) -> day thuc chat la lop dieu chinh/fill da bake vao composite
        # tong; neu de opaque no se CHE ca trang (bug hero den). Thay bang crop tu
        # composite tong (mau that), bo blend/opacity vi da la anh da render.
        elif (real_comp is not None and img is not None
              and is_background(node, cw, ch) and not is_overlay
              and (_is_blank(img) or _mostly_white(img) or _mostly_dark(img))):
            try:
                crop = real_comp.crop((b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"])).convert("RGBA")
                if not (_is_blank(crop) or _mostly_white(crop)):
                    export_img = crop
                    node["opacity"] = 1.0
                    node.pop("blend", None)
            except Exception:
                pass

        # CLIP layer ve trong khung canvas. Layer PSD thuong VE LAN ra ngoai
        # canvas (bleed) - composite/screenshot da tu cat, nhung asset PNG xuat
        # rieng thi giu nguyen kich thuoc day du + bbox tran. Neu khong cat, khi
        # dat lai theo bbox, layer se tran sang vung khac (nghiem trong khi GHEP
        # NHIEU section: layer section tren de len section duoi). Ta cat ca asset
        # lan bbox ve phan giao voi canvas cho khop voi screenshot.
        orig_b = dict(node["bbox"])
        if export_img is not None and cw and ch:
            bx, by, bw, bh = orig_b["x"], orig_b["y"], orig_b["width"], orig_b["height"]
            ix0, iy0 = max(0, bx), max(0, by)
            ix1, iy1 = min(cw, bx + bw), min(ch, by + bh)
            if ix1 <= ix0 or iy1 <= iy0:
                export_img = None  # layer nam hoan toan ngoai canvas -> bo
            elif (ix0, iy0, ix1, iy1) != (bx, by, bx + bw, by + bh):
                try:
                    export_img = export_img.crop((ix0 - bx, iy0 - by, ix1 - bx, iy1 - by))
                    node["bbox"] = {"x": ix0, "y": iy0, "width": ix1 - ix0, "height": iy1 - iy0}
                except Exception:
                    pass

        # Xuat asset cho MOI layer ve duoc (ke ca layer chu) - mac dinh WebP.
        if export_img is not None:
            try:
                name = _save_asset(export_img, assets_dir, lid)
                node["asset"] = f"assets/{name}"
            except Exception:
                pass

        # Ghep vao canvas du phong (dung toa do GOC; PIL tu cat o canh canvas)
        if canvas is not None and img is not None:
            try:
                canvas.paste(img.convert("RGBA"), (orig_b["x"], orig_b["y"]), img.convert("RGBA"))
            except Exception:
                pass

        out.append(node)


def parse_psd(psd_path, out_dir, asset_fmt=None, webp_quality=None, webp_lossless_max=None):
    """
    Ham chinh cua Pha 1.
    psd_path: duong dan file .psd
    out_dir : thu muc xuat ket qua (se tao assets/, screenshot.png, layout.json)
    asset_fmt/webp_quality/webp_lossless_max: chat luong anh (uu tien hon .env).
    Tra ve: duong dan file layout.json
    """
    _load_env()
    _apply_asset_cfg(asset_fmt, webp_quality, webp_lossless_max)
    psd_path = Path(psd_path)
    out_dir = Path(out_dir)
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Mo file PSD: {psd_path.name}")
    psd = PSDImage.open(psd_path)

    print("[2/4] Render composite tong (co layer style)...")
    # Composite tong render DUNG layer style (gradient/vien/glow) - dung lam
    # nguon MAU cho tung layer foreground de chu/anh khong bi mat hieu ung.
    # LOAI menu overlay ra khoi composite de layer duoi khong bi bake 'bong ma' menu.
    overlay = _overlay_ids(psd)
    try:
        if overlay:
            real_comp = psd.composite(layer_filter=lambda l: id(l) not in overlay and l.visible)
        else:
            real_comp = psd.composite()
        if real_comp is not None:
            real_comp = real_comp.convert("RGBA")
        if real_comp is not None and _is_blank(real_comp):
            real_comp = None
    except Exception:
        real_comp = None

    print("[3/4] Duyet cay layer + xuat assets...")
    fallback = Image.new("RGBA", (psd.width, psd.height), (255, 255, 255, 255))
    layers = []
    counter = [0]
    _walk(psd, layers, assets_dir, counter, canvas=fallback,
          real_comp=real_comp, cw=psd.width, ch=psd.height, overlay=overlay)

    # Screenshot tong: uu tien composite that; neu rong thi dung ban tu ghep
    screenshot_path = out_dir / "screenshot.png"
    composite = real_comp if real_comp is not None else fallback
    composite.convert("RGB").save(screenshot_path)

    artboards = _collect_artboards(psd)
    if artboards:
        print(f"      Tim thay {len(artboards)} artboard")

    layout = {
        "source": psd_path.name,
        "canvas": {"width": psd.width, "height": psd.height},
        "screenshot": "screenshot.png",
        "artboards": artboards,
        "layers": layers,
    }

    layout_path = out_dir / "layout.json"
    with open(layout_path, "w", encoding="utf-8") as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)

    print(f"[4/4] Xong Pha 1: {len(layers)} layer -> {layout_path}")
    return layout_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Cach dung: python -m psd2html.parser <file.psd> [thu_muc_out]")
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "output"
    parse_psd(src, dst)
