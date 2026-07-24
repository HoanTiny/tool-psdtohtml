# Tien trinh nang cap giao dien psd2html

Cap nhat lan cuoi: 2026-07-23

## Muc tieu

Chuyen giao dien webapp tu form dai thanh workspace chinh sua toan man hinh,
giu nguyen API Flask va toan bo luong parse/edit/group/export/build hien tai.

## Tien trinh

- [x] Khao sat UI hien tai va xac dinh kien truc app shell.
- [x] Tach HTML, CSS va JavaScript khoi `psd2html/webapp.py`.
- [x] Dung top bar, document tabs va status bar.
- [x] Dung workspace ba vung: Layers, Canvas, Inspector.
- [x] Chuyen tuy chon export/build sang panel rieng.
- [x] Bo sung responsive co ban cho workspace.
- [x] Bo sung pan/zoom va Fit Canvas.
- [x] Bo sung collapse/resize panel, luu preference va shortcut F/G/L/I.
- [x] Smoke test Python, JavaScript, Flask, static asset va phuc hoi job.
- [ ] QA truc quan va chay lai full flow parse/edit/preview/export tren trinh duyet.

## Nhat ky

### 2026-07-23

- Da hoan tat khao sat giao dien cu.
- Chon huong giu Flask + JavaScript hien tai de giam rui ro thay doi backend.
- Da tach UI thanh `templates/index.html`, `static/css/app.css` va
  `static/js/app.js`; `webapp.py` chi con backend va route render template.
- Da tao app shell toan man hinh voi top bar, Layers, Canvas, Inspector va
  status bar; cac ID/API cu duoc giu nguyen.
- Da them `editor-shell.css` va `editor-shell.js` cho responsive, Fit Canvas,
  Ctrl+wheel zoom va Space+drag pan.
- Da kiem tra Python, JavaScript, Flask route va static asset: dat.
- Da them nut an/hien Layers va Inspector, luu bo cuc vao localStorage.
- Da them shortcut F (fit), G (group), L (Layers), I (Inspector).
- Da them keo resize Layers/Inspector va ghi nho kich thuoc panel.
- Da them status bar cho canvas va trang thai autosave.
- Smoke test dat: trang chinh 200, static 200, job1 status 200 JSON; Python/JS hop le.
- Da sua template bi sot JavaScript inline sau buoc tach file.
- Da doi CSS/JS sang duong dan `../static/...` de giao dien co style khi mo
  truc tiep bang `file://`; cac chuc nang API van chay qua Flask.
- Da them nut Dong cho ban xem thu, ho tro Esc va dung iframe khi dong.
- Da them nut Dong cho panel ket qua export/build va ho tro Esc.
- Da bat auto-reload template va tat cache static; localhost da tra ca hai nut Dong.
- Da thiet ke lai panel export: card nen tang, segmented language, switch production va mo ta ro rang.
- Da thiet ke lai Inspector: layer header, transform grid, interaction/SEO, asset va effect theo section.
- Da them Undo/Redo 80 buoc cho drag, resize, transform input va phim mui ten (Ctrl+Z/Ctrl+Shift+Z/Ctrl+Y).

### 2026-07-24

- Da chan path traversal cho route result/download va popup variant.
- Da sua debounce autosave theo tung layer/tab de Ctrl+Z khong bi save cu ghi de.
- Da them option VPlay/OIDC login, mac dinh tat, cho output React/Vite va Next.
- Flow OIDC moi dung Web Crypto, URLSearchParams, luu/kiem tra state va khong can `md5`.
- Da sinh `.env` rieng cho Vite (`VITE_APP_*`) va Next (`NEXT_PUBLIC_APP_*`).
- Da doc horizontal/vertical guide tu Photoshop vao `layout.json`.
- PSD dai trong mot file nay duoc chia section theo horizontal guide cua designer;
  editor va export dung chung dung moc y nen khong bi lech section.
- Da them che do preview `PSD chuan` dung composite tong de khop Photoshop,
  trong khi cac hitbox layer van cho phep chon layer tren canvas.
- Editor tu chuyen sang `Tung layer` khi nguoi dung keo, resize, an/hien hoac
  thay doi thuoc tinh hinh anh de phan chinh sua duoc cap nhat truc tiep.
- Da them option `Composite + hotspot` cho React/Vite va Next, mac dinh tat.
- Khi bat, moi section dung WebP lossless cat tu composite PSD; cac nut/link duoc
  phu anchor trong suot, giu action popup, scroll, link va VPlay/OIDC.
- Hotspot tu nhan dien qua lon bi loc de tranh tieu de che click; cac manh text/icon
  sat nhau cua cung mot nut duoc gop thanh mot hitbox.
- UI tu khoa `Fluid mobile`, `AI productionize` va hieu ung layer khi dung composite.
- Da xac minh tren PSD 1920x5807: 6 composite section, React/Vite va Next production
  build thanh cong, TypeScript typecheck thanh cong.
- Regression suite hien co 32 test.

## Luu y

- `layout.json` co them field `guides` (additive, khong pha vo consumer cu).
- Khong thay doi contract cua cac endpoint hien co.
- Giu nguyen cac thay doi dang co trong `export_web.py` va `webapp.py`.
