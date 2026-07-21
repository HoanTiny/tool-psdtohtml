"""
Ghep NHIEU file PSD (moi file = 1 SECTION) thanh MOT layout duy nhat.

Boi canh: truoc day design gui 1 file PSD chua ca trang; tool phai TU DOAN cho
cat section (xem sectionize.py) - hay sai. Nay design gui MOI SECTION 1 file PSD
rieng -> ta co ranh gioi do NGUOI chia san, khong can doan nua.

Cach lam:
  1. Parse tung PSD rieng vao out_dir/_sections/NN_ten/ (dung lai parse_psd co san).
  2. Xep chong theo chieu doc: section sau nam duoi section truoc (cong don chieu cao).
  3. Doi toa do moi layer: y += offset cua section; x can giua neu section hep hon.
  4. Tach assets theo section (tien to sNN_) de 2 section khong de file len nhau.
  5. Ghep cac screenshot thanh 1 anh cao = ca trang.
  6. Ghi layout.json GIONG HET dinh dang parse_psd, THEM field "sections" =
     [{name, y0, y1, source}] -> downstream (sectionize/export_web) dung DUNG
     ranh gioi nay thay vi doan.

Thu tu section = thu tu sau khi sort theo TEN FILE. Nen dat ten co so thu tu:
  01-hero.psd  02-features.psd  03-footer.psd
"""

import json
import re
import shutil
from pathlib import Path

from PIL import Image

from .parser import parse_psd


def _section_name(stem):
    """Tu ten file lay ten section sach: bo so thu tu dau ('01-hero' -> 'hero')."""
    name = re.sub(r"^[\s0-9_.\-]+", "", stem).strip()
    return name or stem


def _order_key(path):
    """Khoa sort: theo ten file (khong phan biet hoa thuong)."""
    return Path(path).name.lower()


def parse_and_merge(psd_paths, out_dir, gap=0, align="center",
                    asset_fmt=None, webp_quality=None, webp_lossless_max=None):
    """
    Parse nhieu PSD roi ghep doc thanh 1 layout.json trong out_dir.

    psd_paths : list duong dan .psd (moi file = 1 section). Se sort theo ten file.
    out_dir   : thu muc xuat (tao assets/, screenshot.png, layout.json, _sections/).
    gap       : khoang trong (px) chen giua cac section (mac dinh 0 - dinh sat nhau).
    align     : 'center' (mac dinh) can giua section hep hon; 'left' can trai.

    Tra ve: duong dan layout.json ghep.
    """
    psd_paths = sorted(psd_paths, key=_order_key)
    if not psd_paths:
        raise ValueError("Khong co file PSD nao de ghep.")

    out_dir = Path(out_dir)
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    sec_parse_dir = out_dir / "_sections"
    sec_parse_dir.mkdir(parents=True, exist_ok=True)

    # 1. Parse tung PSD rieng
    parsed = []  # list (index, stem, section_dir, layout_dict)
    for i, psd in enumerate(psd_paths):
        stem = Path(psd).stem
        sdir = sec_parse_dir / f"{i:02d}_{stem}"
        print(f"[merge] ({i + 1}/{len(psd_paths)}) parse section: {Path(psd).name}")
        parse_psd(str(psd), str(sdir), asset_fmt, webp_quality, webp_lossless_max)
        layout = json.loads((sdir / "layout.json").read_text(encoding="utf-8"))
        parsed.append((i, stem, sdir, layout))

    # 2. Kich thuoc canvas ghep: rong = max, cao = tong (+ gap giua cac section)
    canvas_w = max(p[3]["canvas"]["width"] for p in parsed)
    widths = {p[1]: p[3]["canvas"]["width"] for p in parsed}
    if len({p[3]["canvas"]["width"] for p in parsed}) > 1:
        print(f"[merge] CANH BAO: cac section rong khac nhau {widths} - se can theo '{align}'.")

    merged_layers = []
    sections_meta = []
    combined = None
    y_offset = 0

    for (i, stem, sdir, layout) in parsed:
        w_i = layout["canvas"]["width"]
        h_i = layout["canvas"]["height"]
        x_off = (canvas_w - w_i) // 2 if align == "center" else 0

        # 4. Copy assets cua section -> assets ghep, doi ten voi tien to sNN_
        for layer in layout["layers"]:
            nl = dict(layer)
            nb = dict(layer["bbox"])
            nb["x"] = nb["x"] + x_off
            nb["y"] = nb["y"] + y_offset
            nl["bbox"] = nb
            nl["id"] = f"s{i}_{layer['id']}"
            if layer.get("parent"):
                nl["parent"] = f"s{i}_{layer['parent']}"
            if layer.get("asset"):
                old = sdir / layer["asset"]
                new_name = f"s{i}_{Path(layer['asset']).name}"
                try:
                    shutil.copyfile(old, assets_dir / new_name)
                    nl["asset"] = f"assets/{new_name}"
                except Exception:
                    nl.pop("asset", None)
            merged_layers.append(nl)

        # 5. Ghep screenshot section vao anh tong
        try:
            shot = Image.open(sdir / layout.get("screenshot", "screenshot.png")).convert("RGB")
        except Exception:
            shot = Image.new("RGB", (w_i, h_i), (255, 255, 255))
        if combined is None:
            # tinh truoc tong chieu cao de tao canvas 1 lan
            total_h = sum(p[3]["canvas"]["height"] for p in parsed) + gap * (len(parsed) - 1)
            combined = Image.new("RGB", (canvas_w, total_h), (255, 255, 255))
        combined.paste(shot, (x_off, y_offset))

        # 6. Ghi ranh gioi section (theo goc trang ghep)
        sections_meta.append({
            "name": _section_name(stem),
            "y0": y_offset,
            "y1": y_offset + h_i,
            "source": Path(layout.get("source", stem)).name,
        })

        y_offset += h_i + gap

    total_h = y_offset - gap if parsed else 0  # bo gap thua o cuoi

    # Luu screenshot ghep
    screenshot_path = out_dir / "screenshot.png"
    if combined is not None:
        combined.crop((0, 0, canvas_w, total_h)).save(screenshot_path)

    layout_merged = {
        "source": "merged",
        "canvas": {"width": canvas_w, "height": total_h},
        "screenshot": "screenshot.png",
        "artboards": [],
        "sections": sections_meta,   # <-- ranh gioi NGUOI chia san
        "layers": merged_layers,
    }
    layout_path = out_dir / "layout.json"
    layout_path.write_text(json.dumps(layout_merged, ensure_ascii=False, indent=2), encoding="utf-8")

    names = ", ".join(s["name"] for s in sections_meta)
    print(f"[merge] Ghep {len(parsed)} section ({names}) -> {canvas_w}x{total_h}px -> {layout_path}")
    return layout_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Cach dung: python -m psd2html.merge <out_dir> <a.psd> <b.psd> ...")
        sys.exit(1)
    parse_and_merge(sys.argv[2:], sys.argv[1])
