# psd2html — Chuyển file PSD thành HTML/CSS (Python + AI)

Tool cắt giao diện từ file PSD ra HTML/CSS. Ý tưởng cốt lõi:

- **Python** lo phần "máy làm giỏi": đọc PSD chính xác — layer, toạ độ, text, màu, xuất assets.
- **AI (Claude)** lo phần "người làm giỏi": nhìn tổng thể, đặt semantic tag, viết CSS responsive.

## Pipeline

```
PSD ──► [Pha 1: parser.py] ──► layout.json + assets/*.png + screenshot.png
                                          │
                                          ▼
        [Pha 2: ai_convert.py] ──► index.html + style.css
```

## Cài đặt

```powershell
cd D:\Work\psd2html
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Giao diện web kéo-thả (không cần gõ lệnh)

```powershell
venv\Scripts\python.exe -m psd2html.webapp
```
Mở **http://localhost:5000** → kéo file PSD (desktop + tuỳ chọn mobile) → chọn định dạng (HTML / React / Next) → bấm **Chuyển đổi** → xem preview (HTML) và tải ZIP kết quả.

## Nhiều PSD — mỗi file 1 section (mới)

Nếu design gửi **mỗi section 1 file PSD riêng** (thay vì 1 file cả trang), truyền nhiều file cùng lúc — tool tự **ghép dọc theo thứ tự tên file**:

```powershell
venv\Scripts\python.exe -m psd2html.cli 01-hero.psd 02-features.psd 03-footer.psd -o output --react
```

Trên **web UI**: kéo/chọn nhiều file `.psd` vào ô Desktop (và Mobile nếu có) — danh sách hiện theo đúng thứ tự ghép.

- **Thứ tự = tên file.** Đặt tên có số đầu: `01-hero.psd`, `02-features.psd`... Phần tên sau số (`hero`, `features`) thành **tên component** luôn (`Hero.jsx`, `Features.jsx`).
- **Ranh giới section chính xác 100%** do người chia — không còn đoán gap như file gộp (xem `sectionize.py`).
- **Assets tách riêng** theo section (`s0_*`, `s1_*`...) nên không đè tên nhau.
- Section hẹp hơn được **căn giữa** trong canvas (rộng = section rộng nhất).
- Dùng được với mọi chế độ (`--slices`, `--react`, `--next`, AI). Truyền **1 file** → chạy y như cũ.
- `--mobile` cũng nhận nhiều file: `--mobile 01-hero-m.psd 02-features-m.psd`.

**Cắt layer theo khung (clip):** layer PSD hay vẽ lấn ra ngoài canvas (bleed). Parser tự **cắt asset + bbox về đúng khung** — nếu không, phần tràn của section trên sẽ đè xuống section dưới khi ghép (xem `parser.py`).

**Thanh cố định (fixed nav):** phần lặp ở mọi section (logo + menu dọc + icon chuột) được **tự phát hiện** (gom cụm theo vị trí tương đối + so ảnh aHash, đã loại nền) rồi **render 1 lần** dạng `position:fixed` thay vì lặp mỗi section — slices dùng overlay riêng, React/Next sinh component `FixedNav` (xem `fixed_overlay.py`).

**Tối ưu hiệu năng (tự động):**
- **WebP**: asset xuất dạng `.webp` (quality 85) thay vì PNG → nhẹ hơn ~90% (vd 42MB → ~4MB), tải + giải mã nhanh, đỡ giật. Đổi lại PNG: đặt `PSD2HTML_ASSET_FMT=png`; chỉnh chất lượng: `PSD2HTML_WEBP_QUALITY=90`.
- **Lazy-load**: ảnh ngoài màn hình chỉ tải khi cuộn tới (`loading=lazy` + `decoding=async`); section đầu tải ngay để không nháy. Áp cho cả slices lẫn React/Next.
- **content-visibility** (slices): mỗi section là 1 lớp riêng, trình duyệt bỏ qua render section ngoài màn hình → cuộn mượt hơn.

## 3 chế độ chuyển

| Chế độ | Lệnh | Khi nào dùng | AI? |
|--------|------|--------------|-----|
| **Cắt ảnh** | `--slices` | Landing nhiều đồ hoạ (game, sự kiện) — mọi thứ kể cả chữ cách điệu đều là ảnh. Pixel-perfect, tức thì | Không |
| **React** | `--react` | Xuất project React (Vite) + Tailwind | Không |
| **Next.js** | `--next` | Xuất project Next.js (app router) + Tailwind | Không |
| **Cắt section** | `--sections` (tự động khi trang cao) | Cần HTML semantic + đặt ảnh nền, foreground dựng lại | Có |
| **One-shot** | `--one-shot` | Trang ngắn, đơn giản | Có |

### Xuất React / Next

```powershell
venv\Scripts\python.exe -m psd2html.cli file.psd -o output --react            # JS (mac dinh)
venv\Scripts\python.exe -m psd2html.cli file.psd -o output --react --lang ts  # TypeScript
venv\Scripts\python.exe -m psd2html.cli file.psd -o output --next --lang ts   # Next + TS
```

Rồi: `cd output\react-app && npm install && npm run dev`.

**Chọn TypeScript hoặc JavaScript** qua `--lang ts|js` (hoặc bộ chọn trên web UI). TS kèm `types/landing.ts` + `tsconfig.json`.

**Chia nhỏ theo section — dễ maintain:** mỗi section là 1 component riêng trong `components/landing/` (vd `DiemDanh`, `NapDungGoi`, `TichLuyNap`...), cùng `Stage` (responsive), `Layer` (1 lớp ảnh), `Background` (nền), và mỗi cụm lặp 1 file. `Landing` ghép tất cả lại. Cấu trúc:
```
src/components/
  Stage.tsx
  landing/
    Landing.tsx        # ghép các section
    Background.tsx
    DiemDanh.tsx  NapDungGoi.tsx  ...   # mỗi section 1 file
    Group66.tsx  ...                     # mỗi cụm lặp 1 file
  landing-mobile/      # nếu có --mobile
src/types/landing.ts   # (TS)
``` Tailwind cho class tiện ích, component `Stage` tự co giãn responsive. **Nhiều artboard** trong 1 PSD → mỗi artboard thành 1 component (React) / 1 route (Next).

**Componentize group lặp (API-ready) — tuỳ chọn `--repeats`:** MẶC ĐỊNH render **phẳng** (mỗi layer đặt tuyệt đối, khớp thiết kế 100% như slices) vì với landing dày đồ hoạ, các thẻ/vật phẩm khác nhau hay bị gom nhầm thành "cụm lặp" → méo/chồng lên nhau. Bật `--repeats` khi bạn muốn các cụm lặp (7 thẻ điểm danh, 3 gói nạp...) được tự phát hiện và sinh thành 1 component render bằng `.map()` qua mảng data:
- Mỗi phần tử: `{ id, x, y, sN (ảnh khác nhau như "Ngày 1"), claimed, items }` — thay bằng data từ BE.
- Nút "Nhận Quà" gọi `onClaim(id)` — cắm API claim vào đây.
- Ô vật phẩm: `item.items = [{src, x, y, w, h}]` do BE trả về.
- `item.claimed = true` → hiện lớp mờ đánh dấu đã nhận.
- Hook `useLandingData` (stub) để điền endpoint thật.

Layer không lặp vẫn render phẳng như `--slices`.

### Desktop + Mobile riêng

Nếu designer gửi cả PSD mobile, truyền thêm `--mobile`:

```powershell
python -m psd2html.cli landing-web.psd -o output --react --mobile landing-mobile.psd
```

- Desktop hiện từ breakpoint `md` (≥768px), mobile hiện dưới `md` — dùng đúng design mỗi bản.
- Component mobile có tiền tố `M`, ảnh mobile ở `public/assets-m`.
- Không truyền `--mobile` → chỉ bản desktop (tự co giãn responsive như cũ).

Chế độ `--slices`: mỗi layer (kể cả layer chữ) được xuất ra PNG và đặt đúng toạ độ bbox, xếp chồng đúng thứ tự → giống thiết kế 100%, không tốn API. Đây là cách dân cắt web hay dùng cho landing game. Tính năng:
- **Cắt đáy thừa**: tự bỏ phần nền kéo dài quá nội dung cuối.
- **Blend mode**: áp `mix-blend-mode` (screen/overlay/soft-light...) cho layer hiệu ứng.
- **Nút bấm**: layer CTA (Nhận Quà, Đăng Nhập, Nạp Thẻ, menu...) tự bọc `<a>` có hover. Sửa danh sách từ khoá tại `INTERACTIVE_KEYWORDS` trong `render_slices.py`, điền link thật vào `href`.
- **Responsive**: tự co giãn cả trang cho vừa màn hình (kể cả mobile).

> Cần `scipy` để render layer gradient (nhân vật, nhãn). Thiếu scipy → layer gradient mất ảnh.

## Dùng

Cắt ảnh trực tiếp (khuyên dùng cho landing game, KHÔNG cần API):

```powershell
venv\Scripts\python.exe -m psd2html.cli duong_dan.psd -o output --slices
```

Chạy 2 pha AI (cần API key):

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
venv\Scripts\python.exe -m psd2html.cli duong_dan.psd -o output
```

Chỉ Pha 1 (parse PSD, KHÔNG cần API — tốt để học/kiểm tra):

```powershell
venv\Scripts\python.exe -m psd2html.cli duong_dan.psd --parse-only
```

Đổi model chất lượng cao nhất:

```powershell
venv\Scripts\python.exe -m psd2html.cli duong_dan.psd --model claude-opus-4-8
```

## Cấu trúc code

| File | Vai trò |
|------|---------|
| `psd2html/parser.py` | Pha 1 — đọc PSD, xuất JSON + assets + screenshot |
| `psd2html/merge.py` | Ghép nhiều PSD (mỗi file 1 section) thành 1 layout |
| `psd2html/fixed_overlay.py` | Phát hiện phần lặp giữa các section (nav/logo) → render 1 lần dạng fixed |
| `psd2html/sectionize.py` | Cắt trang cao thành section + phân loại layer nền (ưu tiên ranh giới có sẵn) |
| `psd2html/ai_convert.py` | Pha 2 — gửi Claude, nhận HTML/CSS (one-shot & theo section) |
| `psd2html/cli.py` | Nối 2 pha, chạy từ dòng lệnh |
| `make_sample_psd.py` | Sinh PSD mẫu để test (cần `pytoshop`) |

## Cách xử lý trang dài (landing page)

Trang cao > 2500px tự động **cắt theo section**:
1. `sectionize` chia trang theo chiều dọc, nắn đường cắt về chỗ ít nội dung nhất.
2. Mỗi section: ghép ảnh nền trang trí (`sections/bgX.png`) từ các layer nền.
3. AI dựng lại foreground (chữ, nút, item) đè lên nền, chạy **song song** nhiều section.
4. Ghép tất cả thành `index.html` + `style.css`.

Ép chế độ: `--sections` (luôn cắt) hoặc `--one-shot` (cả trang 1 lần).

## Hạn chế / hướng nâng cấp

- Trích font/màu chữ phụ thuộc dữ liệu engine của PSD — layer chữ phức tạp có thể thiếu.
- Chưa xử lý blend mode, layer effect nâng cao, smart object lồng nhau.
- Có thể thêm: gom layer theo hàng/cột trước khi đưa AI, tách nhiều artboard, xuất React/Tailwind.
