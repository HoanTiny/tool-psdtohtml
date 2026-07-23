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

## Luu y

- Khong thay doi schema `layout.json`.
- Khong thay doi contract cua cac endpoint hien co.
- Giu nguyen cac thay doi dang co trong `export_web.py` va `webapp.py`.
