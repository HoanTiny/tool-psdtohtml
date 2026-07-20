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
from .ai_convert import convert, convert_sectioned, DEFAULT_MODEL

# Trang cao hon nguong nay -> tu dong cat theo section
TALL_THRESHOLD = 2500


def main():
    ap = argparse.ArgumentParser(description="Chuyen file PSD thanh HTML/CSS.")
    ap.add_argument("psd", help="Duong dan file .psd")
    ap.add_argument("-o", "--out", default="output", help="Thu muc xuat (mac dinh: output)")
    ap.add_argument("--parse-only", action="store_true",
                    help="Chi chay Pha 1 (parse PSD), khong goi AI")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Model Claude (mac dinh: {DEFAULT_MODEL})")
    ap.add_argument("--mobile", default=None, metavar="PSD",
                    help="File PSD ban mobile (chi dung voi --react/--next): sinh ban mobile rieng")
    ap.add_argument("--lang", choices=["js", "ts"], default="js",
                    help="Ngon ngu khi xuat React/Next: js (mac dinh) hoac ts (TypeScript)")
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
    layout_path = parse_psd(args.psd, args.out)

    if args.parse_only:
        print("\nDa xong Pha 1. Bo qua AI (--parse-only).")
        return

    # Che do cat anh truc tiep: khong can AI
    if args.slices:
        print("\n=== Cat anh truc tiep (khong dung AI) ===")
        from .render_slices import render
        html_path = render(args.out)
        print(f"\nHOAN TAT -> mo file: {html_path}")
        return

    # Xuat React / Next: khong can AI
    if args.react or args.nextjs:
        fw = "next" if args.nextjs else "react"
        mobile_dir = None
        if args.mobile:
            print(f"\n=== Parse PSD mobile: {args.mobile} ===")
            mobile_dir = str(Path(args.out) / "_mobile")
            parse_psd(args.mobile, mobile_dir)
        print(f"\n=== Xuat du an {fw.upper()}/{args.lang} (khong dung AI) ===")
        from .export_web import export
        proj = export(args.out, framework=fw, lang=args.lang, mobile_dir=mobile_dir)
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
