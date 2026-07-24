"""
CLI - chay ca pipeline: PSD -> (Pha 1) layout+assets -> (Pha 2) HTML/CSS.

Vi du:
  python -m psd2html.cli sample.psd                # chay ca 2 pha
  python -m psd2html.cli sample.psd -o out --parse-only   # chi Pha 1 (khong can API)
  python -m psd2html.cli sample.psd --model claude-opus-4-8
"""

import argparse
import sys
from pathlib import Path

from .parser import parse_psd
from .merge import parse_and_merge
from .ai_convert import convert, convert_sectioned, DEFAULT_MODEL

# Trang cao hon nguong nay -> tu dong cat theo section
TALL_THRESHOLD = 2500


_QUALITY = {"balanced": ("webp", 92, 300000), "high": ("webp", 97, 800000), "png": ("png", None, None)}


def _parse_input(psd_list, out_dir, label="desktop", quality="balanced"):
    """1 file -> parse thuong; nhieu file -> moi file 1 section, ghep doc (merge)."""
    fmt, q, lm = _QUALITY.get(quality, _QUALITY["balanced"])
    if len(psd_list) == 1:
        return parse_psd(psd_list[0], out_dir, fmt, q, lm)
    print(f"[{label}] {len(psd_list)} file PSD -> moi file 1 section, ghep doc theo ten file")
    return parse_and_merge(psd_list, out_dir, asset_fmt=fmt, webp_quality=q, webp_lossless_max=lm)


def main():
    ap = argparse.ArgumentParser(description="Chuyen file PSD thanh HTML/CSS.")
    ap.add_argument("psd", nargs="+",
                    help="File .psd. Nhieu file = moi file 1 SECTION, ghep doc theo ten file "
                         "(vd: 01-hero.psd 02-features.psd 03-footer.psd)")
    ap.add_argument("-o", "--out", default="output", help="Thu muc xuat (mac dinh: output)")
    ap.add_argument("--quality", choices=["balanced", "high", "png"], default="balanced",
                    help="Chat luong anh: balanced (WebP q92, mac dinh), high (WebP q97), png (anh goc, nang).")
    ap.add_argument("--parse-only", action="store_true",
                    help="Chi chay Pha 1 (parse PSD), khong goi AI")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Model Claude (mac dinh: {DEFAULT_MODEL})")
    ap.add_argument("--mobile", default=None, nargs="*", metavar="PSD",
                    help="File PSD ban mobile (chi dung voi --react/--next); nhieu file = ghep section")
    ap.add_argument("--lang", choices=["js", "ts"], default="js",
                    help="Ngon ngu khi xuat React/Next: js (mac dinh) hoac ts (TypeScript)")
    ap.add_argument("--repeats", action="store_true",
                    help="React/Next: gom 'cum lap' thanh component .map() (API-ready). "
                         "Mac dinh TAT (render phang, khop thiet ke hon cho landing do hoa).")
    ap.add_argument("--swiper", action="store_true",
                    help="Che do full-page: lan/vuot snap tung section (nhu swiper), "
                         "thay vi cuon xuong lien tuc. Dung cho slices/react/next.")
    ap.add_argument("--swiper-lib", action="store_true",
                    help="React/Next: dung thu vien Swiper.js that (effect fade nhu prod) thay fade tu viet.")
    ap.add_argument("--popups", action="store_true",
                    help="React/Next: sinh he popup (login/the le/lich su/nap dau) - dang stub.")
    ap.add_argument("--env-config", action="store_true",
                    help="React/Next: link/API dat trong .env (VITE_APP_*) + constant, thay object LINKS.")
    ap.add_argument("--nav-menu", action="store_true",
                    help="React/Next: nav dang menu chu config duoc (ten muc, muc->section/popup).")
    ap.add_argument("--fluid", action="store_true",
                    help="React/Next: mobile CO GIAN THAT (section xep doc flow, cum luoi reflow "
                         "4->2->1 cot theo viewport). Chi ap khi KHONG dung --mobile. Desktop giu nguyen.")
    ap.add_argument("--ai-enhance", action="store_true",
                    help="React/Next: nho AI 'prod-hoa' tung section (chu thuong->text that, CTA->button hover). Can ANTHROPIC_API_KEY (.env).")
    ap.add_argument("--smart-hybrid", action="store_true",
                    help="React/Next: composite tinh + AI tach so lieu/trang thai/nut thanh overlay noi API.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--slices", action="store_true",
                      help="Cat anh truc tiep (pixel-perfect, KHONG dung AI) - hop landing nhieu do hoa")
    mode.add_argument("--react", action="store_true",
                      help="Xuat du an React (Vite) + Tailwind (KHONG dung AI)")
    mode.add_argument("--next", dest="nextjs", action="store_true",
                      help="Xuat du an Next.js (app router) + Tailwind (KHONG dung AI)")
    mode.add_argument("--sections", action="store_true", help="AI cat theo section")
    mode.add_argument("--one-shot", action="store_true", help="AI chuyen ca trang 1 lan")
    args = ap.parse_args()

    print("=== Pha 1: Parse PSD ===")
    layout_path = _parse_input(args.psd, args.out, quality=args.quality)

    if args.parse_only:
        print("\nDa xong Pha 1. Bo qua AI (--parse-only).")
        return

    # Che do cat anh truc tiep: khong can AI
    if args.slices:
        print("\n=== Cat anh truc tiep (khong dung AI) ===")
        from .render_slices import render
        html_path = render(args.out, swiper=args.swiper)
        print(f"\nHOAN TAT -> mo file: {html_path}")
        return

    # Xuat React / Next: khong can AI
    if args.react or args.nextjs:
        fw = "next" if args.nextjs else "react"
        mobile_dir = None
        if args.mobile:
            print(f"\n=== Parse PSD mobile ({len(args.mobile)} file) ===")
            mobile_dir = str(Path(args.out) / "_mobile")
            _parse_input(args.mobile, mobile_dir, label="mobile", quality=args.quality)
        print(f"\n=== Xuat du an {fw.upper()}/{args.lang} (khong dung AI) ===")
        from .export_web import export
        feats = {"swiper_lib": args.swiper_lib, "popups": args.popups,
                 "env_config": args.env_config, "nav_menu": args.nav_menu,
                 "ai_enhance": args.ai_enhance, "fluid": args.fluid,
                 "smart_hybrid": args.smart_hybrid}
        proj = export(args.out, framework=fw, lang=args.lang, mobile_dir=mobile_dir,
                      detect_repeats=args.repeats, swiper=args.swiper, feats=feats)
        print(f"\nHOAN TAT -> {proj}")
        return

    # Quyet dinh che do
    import json
    canvas_h = json.loads(layout_path.read_text(encoding="utf-8"))["canvas"]["height"]
    use_sections = args.sections or (canvas_h > TALL_THRESHOLD and not args.one_shot)

    print(f"\n=== Pha 2: AI -> HTML/CSS ({'cat section' if use_sections else 'one-shot'}) ===")
    try:
        if use_sections:
            html_path = convert_sectioned(args.out, model=args.model)
        else:
            html_path = convert(args.out, model=args.model)
    except Exception as e:
        print(f"\n[LOI] Pha 2 that bai: {e}", file=sys.stderr)
        print("Meo: dat bien moi truong ANTHROPIC_API_KEY, hoac chay lai voi --parse-only.",
              file=sys.stderr)
        sys.exit(1)

    print(f"\nHOAN TAT -> mo file: {html_path}")


if __name__ == "__main__":
    main()
