"""Regression test cho cac loi concurrency/job/auth cua webapp."""

import tempfile
import threading
import unittest
import os
import time
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from psd2html import ai_hybrid, ba_flow, export_web, parser, sectionize, webapp


class _FakeLayer:
    def __init__(self, name, visible=True, children=None):
        self.name = name
        self.visible = visible
        self._children = children
        self.bbox = (0, 0, 20, 10)
        self.opacity = 255
        self.kind = "group" if children is not None else "pixel"
        self.blend_mode = SimpleNamespace(name="NORMAL")
        self.force_calls = []

    def __iter__(self):
        return iter(self._children or [])

    def is_group(self):
        return self._children is not None

    def composite(self, force=False):
        self.force_calls.append(force)
        return Image.new("RGBA", (20, 10), (255, 0, 0, 255))


class HiddenLayerParserTests(unittest.TestCase):
    def test_hidden_group_and_children_are_exported_as_hidden(self):
        child = _FakeLayer("popup content", visible=True)
        group = _FakeLayer("popup", visible=False, children=[child])
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp)
            out = []
            parser._walk(
                [group], out, assets, [0], cw=100, ch=100,
                asset_cfg=parser._asset_cfg(asset_fmt="png"),
            )

            self.assertEqual(["popup", "popup content"], [item["name"] for item in out])
            self.assertFalse(out[0]["visible"])
            self.assertFalse(out[1]["visible"])
            self.assertEqual([True], child.force_calls)
            self.assertTrue((assets / "L2.png").exists())

    def test_identical_layers_share_one_asset_file(self):
        first = _FakeLayer("frame 1")
        second = _FakeLayer("frame 2")
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp)
            out = []
            parser._walk(
                [first, second], out, assets, [0], cw=100, ch=100,
                asset_cfg=parser._asset_cfg(asset_fmt="png"),
            )

            self.assertEqual(out[0]["asset"], out[1]["asset"])
            self.assertEqual(1, len(list(assets.glob("*.png"))))


class InlinePopupTests(unittest.TestCase):
    def _layout(self):
        box = {"x": 100, "y": 200, "width": 300, "height": 180}
        return {
            "canvas": {"width": 1000, "height": 1000},
            "layers": [
                {"id": "root", "name": "popup", "kind": "group",
                 "parent": None, "bbox": box},
                {"id": "rules", "name": "the le", "kind": "group",
                 "parent": "root", "bbox": box, "visible": False,
                 "visible_self": False},
                {"id": "body", "name": "noi dung", "kind": "pixel",
                 "parent": "rules", "bbox": box, "asset": "assets/body.png",
                 "opacity": 1, "visible": False, "visible_self": True},
            ],
        }

    def test_manifest_finds_group_under_popup_folder(self):
        choices = webapp._inline_popup_groups(self._layout(), "desktop")
        self.assertEqual("inline-desktop-rules", choices[0]["id"])
        self.assertEqual(1, choices[0]["count"])

    def test_export_rebases_hidden_popup_group_and_consumes_page_layer(self):
        popups, consumed = export_web._inline_popups(
            self._layout(), "assets", "desktop"
        )
        self.assertEqual({"body"}, consumed)
        self.assertEqual("inline-desktop-rules", popups[0]["id"])
        self.assertFalse(popups[0]["flat"][0]["hidden"])
        self.assertEqual((0, 0), (
            popups[0]["flat"][0]["x"], popups[0]["flat"][0]["y"]
        ))


class BAFlowTests(unittest.TestCase):
    def test_extract_text_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ba.md"
            path.write_text("Bấm nút Tải game mở https://example.com", encoding="utf-8")
            self.assertIn("Tải game", ba_flow.extract_document(path))

    def test_build_flow_spec_maps_common_actions(self):
        manifest = {
            "desktop": {
                "layers": [
                    {"id": "login", "name": "Đăng Nhập"},
                    {"id": "download", "name": "Tải Game"},
                    {"id": "gift", "name": "Mốc Quà"},
                ],
                "sections": [{"name": "Hero"}, {"name": "Quà"}],
            },
            "popups": [{"id": "p0", "name": "Đăng nhập"}],
        }
        text = "\n".join([
            "Bấm nút Đăng Nhập để mở popup Đăng nhập.",
            "Nhấn Tải Game mở https://example.com/download.",
            "Click Mốc Quà để cuộn tới section Quà.",
        ])
        spec = ba_flow.build_flow_spec(text, manifest, "BA.md")
        by_action = {item["action"]: item for item in spec["items"]}

        self.assertEqual("login", by_action["popup"]["layer_id"])
        self.assertEqual("p0", by_action["popup"]["target"])
        self.assertEqual("download", by_action["url"]["layer_id"])
        self.assertEqual("https://example.com/download", by_action["url"]["target"])
        self.assertEqual("gift", by_action["scroll"]["layer_id"])
        self.assertEqual("1", by_action["scroll"]["target"])

    def test_build_flow_spec_understands_ft_usecase_table(self):
        manifest = {
            "desktop": {
                "layers": [
                    {"id": "login", "name": "Đăng Nhập"},
                    {"id": "rules", "name": "Thể Lệ"},
                ],
                "sections": [{"name": "Hero"}],
            },
            "popups": [{"id": "rules-popup", "name": "Thể lệ"}],
        }
        text = """
3.1 FT_001. Luồng Đăng nhập
Mã Use case | FT_001
Tên Use case | Đăng nhập
Tác nhân | Người dùng
Điểm kích hoạt | Người dùng ấn nút "Đăng nhập" trên landing
Luồng sự kiện chính | Hệ thống chuyển sang https://id.onlive.vn/
Luồng sự kiện ngoại lệ | Mất kết nối => hiển thị "Vui lòng thử lại"

3.2 FT_002. Luồng Xem thể lệ
Tên Use case | Xem thể lệ
Điểm kích hoạt | Người dùng nhấn nút "Thể lệ"
Luồng sự kiện chính | Truy cập https://landing.example/ rồi hệ thống mở popup thể lệ

3.3 FT_003. Luồng Nhận quà
Tên Use case | Nhận quà
Điểm kích hoạt | Người dùng nhấn nút "Nhận quà"
Luồng sự kiện chính | Người dùng nạp tại https://nap.example/; hệ thống kiểm tra điều kiện nghiệp vụ và trả quà
"""
        spec = ba_flow.build_flow_spec(text, manifest, "T027.docx")
        by_feature = {
            item["feature_code"]: item
            for item in spec["items"] if item.get("feature_code")
        }

        self.assertEqual(3, spec["summary"]["structured"])
        self.assertEqual(1, spec["summary"]["unsupported"])
        self.assertEqual("url", by_feature["FT_001"]["action"])
        self.assertEqual("https://id.onlive.vn/", by_feature["FT_001"]["target"])
        self.assertEqual("Người dùng", by_feature["FT_001"]["actor"])
        self.assertIn("Mất kết nối", by_feature["FT_001"]["exceptions"])
        self.assertEqual("popup", by_feature["FT_002"]["action"])
        self.assertEqual("rules-popup", by_feature["FT_002"]["target"])
        self.assertEqual("rules", by_feature["FT_002"]["layer_id"])
        self.assertEqual("unsupported", by_feature["FT_003"]["action"])
        self.assertFalse(by_feature["FT_003"]["enabled"])

    def test_upload_and_apply_flow_mapping(self):
        old_jobs_dir = webapp.JOBS_DIR
        old_jobs = webapp.jobs
        with tempfile.TemporaryDirectory() as tmp:
            try:
                webapp.JOBS_DIR = Path(tmp)
                webapp.jobs = {}
                out = Path(tmp) / "demo-job" / "out"
                out.mkdir(parents=True)
                layout = {
                    "canvas": {"width": 1200, "height": 800},
                    "sections": [{"name": "Hero", "y0": 0, "y1": 800}],
                    "layers": [{
                        "id": "download", "name": "Tải Game", "kind": "pixel",
                        "parent": None, "bbox": {
                            "x": 10, "y": 10, "width": 100, "height": 40,
                        },
                        "asset": "assets/download.webp",
                    }],
                    "screenshot": "screenshot.png",
                }
                (out / "layout.json").write_text(
                    json.dumps(layout, ensure_ascii=False), encoding="utf-8"
                )
                client = webapp.app.test_client()
                upload = client.post("/ba-flow/upload", data={
                    "job_id": "demo-job",
                    "document": (
                        io.BytesIO("Bấm Tải Game mở https://example.com".encode("utf-8")),
                        "flow.md",
                    ),
                }, content_type="multipart/form-data")
                self.assertEqual(200, upload.status_code)
                item = upload.get_json()["flow"]["items"][0]
                self.assertEqual("download", item["layer_id"])

                applied = client.post("/ba-flow/apply", json={
                    "job_id": "demo-job", "items": [item],
                })
                self.assertEqual(200, applied.status_code)
                edits = json.loads((out / "edits.json").read_text(encoding="utf-8"))
                self.assertEqual(
                    "https://example.com",
                    edits["download"]["link"]["url"],
                )
            finally:
                webapp.JOBS_DIR = old_jobs_dir
                webapp.jobs = old_jobs


class CompositeHotspotTests(unittest.TestCase):
    def test_composite_filters_large_auto_hitbox_and_merges_button_fragments(self):
        board = {
            "W": 1000,
            "H": 1600,
            "sections": [
                {
                    "comp": "Hero",
                    "y0": 0,
                    "repeats": [],
                    "flat": [
                        {
                            "id": "title", "x": 20, "y": 100,
                            "w": 850, "h": 120, "href": "#",
                            "act": "history", "alt": "Lich su game",
                            "hotspot_explicit": False,
                        },
                        {
                            "id": "login-a", "x": 700, "y": 40,
                            "w": 100, "h": 35, "href": "#",
                            "act": "login", "alt": "Dang nhap",
                            "hotspot_explicit": False,
                        },
                        {
                            "id": "login-b", "x": 795, "y": 42,
                            "w": 30, "h": 30, "href": "#",
                            "act": "login", "alt": "icon login",
                            "hotspot_explicit": False,
                        },
                    ],
                },
                {"comp": "Gift", "y0": 800, "repeats": [], "flat": []},
            ],
            "backgrounds": [], "fixed": [], "repeats": [],
        }

        export_web._prepare_composite_board(board, "desktop")

        hotspots = board["sections"][0]["composite"]["hotspots"]
        self.assertEqual(1, len(hotspots))
        self.assertEqual("login", hotspots[0]["act"])
        self.assertEqual((700, 40, 125, 35), tuple(
            hotspots[0][key] for key in ("x", "y", "w", "h")
        ))
        self.assertEqual([], board["sections"][0]["flat"])
        self.assertEqual([], board["backgrounds"])
        self.assertTrue(board["composite_hotspots"])

    def test_composite_assets_are_cropped_losslessly_by_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = Image.new("RGB", (20, 30), (10, 20, 30))
            image.save(root / "screenshot.png")
            board = {
                "sections": [
                    {"composite": {
                        "filename": "desktop-section-1.webp",
                        "y0": 0, "y1": 12, "w": 20,
                    }},
                    {"composite": {
                        "filename": "desktop-section-2.webp",
                        "y0": 12, "y1": 30, "w": 20,
                    }},
                ]
            }

            export_web._write_composite_assets(
                root, {"screenshot": "screenshot.png"}, board,
                root / "public" / "composite",
            )

            with Image.open(root / "public/composite/desktop-section-1.webp") as first:
                self.assertEqual((20, 12), first.size)
                self.assertEqual((10, 20, 30), first.getpixel((0, 0)))
            with Image.open(root / "public/composite/desktop-section-2.webp") as second:
                self.assertEqual((20, 18), second.size)

    def test_composite_option_is_off_by_default_and_sent_to_backend(self):
        old_token = webapp._ACCESS_TOKEN
        webapp._ACCESS_TOKEN = ""
        try:
            html = webapp.app.test_client().get("/").get_data(as_text=True)
        finally:
            webapp._ACCESS_TOKEN = old_token
        js = (webapp.BASE / "psd2html/static/js/app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="composite_hotspots"', html)
        self.assertNotIn('id="composite_hotspots" checked', html)
        self.assertIn('"composite_hotspots"', js)
        self.assertIn("syncCompositeOptions", js)

class SmartHybridTests(unittest.TestCase):
    def test_fallback_detects_dynamic_game_ui_conservatively(self):
        def layer(layer_id, text, y, parent="group"):
            return {
                "id": layer_id, "kind": "type", "name": text,
                "visible": True, "parent": parent,
                "bbox": {"x": 10, "y": y, "width": 100, "height": 24},
                "text": {"content": text, "font": "GameFont", "size": 30,
                         "color": "#ffffff"},
            }
        layout = {"layers": [
            layer("label", "Tổng lượt vung", 10),
            layer("total", "10.000.000", 40),
            layer("remain", "Số lượt vung còn lại: 0", 80, "spin"),
            layer("spin", "Vung rìu x1", 120, "spin"),
            layer("claim", "Nhận lượt", 160, "task"),
            layer("claimed", "Đã nhận", 160, "task"),
            layer("date", "2025-01-08 11:55:42", 220, "history"),
            layer("title", "Vùng rìu thập bang", 260, "hero"),
        ]}

        roles = ai_hybrid.fallback_classification(layout)

        self.assertEqual("total_spins", roles["total"]["binding"])
        self.assertEqual("remaining_spins", roles["remain"]["binding"])
        self.assertEqual("button", roles["spin"]["role"])
        self.assertEqual("status", roles["claimed"]["role"])
        self.assertNotIn("date", roles)
        self.assertNotIn("title", roles)

    def test_composite_board_keeps_hybrid_overlay_and_uses_button_art_hitbox(self):
        board = {
            "W": 1000, "H": 500, "backgrounds": [], "fixed": [], "repeats": [],
            "_hybrid_roles": {"text": {
                "role": "button", "binding": "spin_once", "action": "spin_1",
                "text": "Vung riu x1", "font": "GameFont", "size": 30,
                "color": "#fff",
            }},
            "sections": [{"comp": "Spin", "y0": 0, "repeats": [], "flat": [
                {"id": "art", "x": 100, "y": 200, "w": 300, "h": 90,
                 "t": False, "src": "/assets/art.webp"},
                {"id": "text", "x": 180, "y": 230, "w": 130, "h": 28,
                 "t": True, "src": "/assets/text.webp", "alt": "Vung riu x1"},
            ]}],
        }

        export_web._prepare_composite_board(board, "desktop")
        overlay = board["sections"][0]["composite"]["hybrid"][0]

        self.assertEqual("spin_once", overlay["binding"])
        self.assertEqual((100, 200, 300, 90), tuple(
            overlay[key] for key in ("hx", "hy", "hw", "hh")
        ))
        source = export_web._gen_composite_section(board["sections"][0], "ts", False)
        self.assertIn("hybridData", source)
        self.assertIn("data-binding", source)
        self.assertIn("spin_once", source)

    def test_smart_hybrid_option_is_disabled_until_composite_is_enabled(self):
        old_token = webapp._ACCESS_TOKEN
        webapp._ACCESS_TOKEN = ""
        try:
            html = webapp.app.test_client().get("/").get_data(as_text=True)
        finally:
            webapp._ACCESS_TOKEN = old_token
        js = (webapp.BASE / "psd2html/static/js/app.js").read_text(encoding="utf-8")

        self.assertIn('id="smart_hybrid" disabled', html)
        self.assertIn('"smart_hybrid"', js)
        self.assertIn("hybrid.disabled = !composite.checked", js)

class OIDCLoginTests(unittest.TestCase):
    def test_vite_helper_uses_expected_env_and_safe_query_builder(self):
        source = export_web._gen_oidc_auth("ts", client=False)

        self.assertIn("VITE_APP_CLIENT_ID", source)
        self.assertIn("VITE_APP_LOGIN_DOMAIN", source)
        self.assertIn("new URLSearchParams", source)
        self.assertIn('sessionStorage.setItem("oidc_state", state)', source)
        self.assertNotIn("md5", source)
        self.assertIn("verifyOidcState", source)
        self.assertNotIn("&&protocol", source)

    def test_next_helper_uses_public_env(self):
        source = export_web._gen_oidc_auth("js", client=True)

        self.assertTrue(source.startswith('"use client";'))
        self.assertIn("NEXT_PUBLIC_APP_CLIENT_ID", source)
        self.assertIn("NEXT_PUBLIC_APP_REDIRECT_URL", source)

    def test_login_action_is_overridden_only_when_option_is_enabled(self):
        effect = 'if (href && href !== "#") return; const url = LINKS[act];'

        self.assertEqual(effect, export_web._with_oidc_login(effect, False))
        self.assertIn(
            'act === "login" ? "" : LINKS[act]',
            export_web._with_oidc_login(effect, True),
        )
        self.assertIn(
            'data-action") !== "login"', export_web._with_oidc_login(effect, True)
        )

    def test_option_is_visible_and_off_by_default(self):
        old_token = webapp._ACCESS_TOKEN
        webapp._ACCESS_TOKEN = ""
        try:
            html = webapp.app.test_client().get("/").get_data(as_text=True)
        finally:
            webapp._ACCESS_TOKEN = old_token
        self.assertIn('id="oidc_login"', html)
        self.assertNotIn('id="oidc_login" checked', html)

    def test_landing_imports_login_helper_only_when_enabled(self):
        board = {
            "landing_name": "Landing", "W": 100, "H": 100,
            "sections": [], "fixed": [], "backgrounds": [],
        }
        plain = export_web._gen_landing(board, "js", False, feats={})
        enabled = export_web._gen_landing(
            board, "js", False, feats={"oidc_login": True}
        )

        self.assertNotIn("handleLogin", plain)
        self.assertIn('import { handleLogin } from "../utils/auth";', enabled)
        self.assertIn('if (act === "login") { handleLogin(); return; }', enabled)


class EditorReferencePreviewTests(unittest.TestCase):
    def test_editor_defaults_to_exact_psd_composite_preview(self):
        old_token = webapp._ACCESS_TOKEN
        webapp._ACCESS_TOKEN = ""
        try:
            html = webapp.app.test_client().get("/").get_data(as_text=True)
        finally:
            webapp._ACCESS_TOKEN = old_token
        js = (webapp.BASE / "psd2html/static/js/app.js").read_text(
            encoding="utf-8"
        )
        css = (webapp.BASE / "psd2html/static/css/editor-shell.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="previewModeBtn"', html)
        self.assertIn('let previewMode = "reference"', js)
        self.assertIn('class="stageReference"', js)
        self.assertIn("function ensureLayerPreview()", js)
        self.assertIn(".stage.referenceMode .lyr", css)

class ParserConfigTests(unittest.TestCase):
    def test_photoshop_guides_are_converted_from_1_over_32_pixel(self):
        info = SimpleNamespace(data=[
            (30432, 1), (30720, 0), (57632, 1), (30432, 1),
            (0, 1), (999999, 0),
        ])
        psd = SimpleNamespace(
            width=1920,
            height=5807,
            image_resources=SimpleNamespace(get_data=lambda _resource: info),
        )

        guides = parser._collect_guides(psd)

        self.assertEqual([951, 1801], guides["horizontal"])
        self.assertEqual([960], guides["vertical"])

    def test_horizontal_guides_define_sections_for_single_tall_psd(self):
        layout = {
            "canvas": {"width": 1920, "height": 5807},
            "guides": {
                "horizontal": [951, 1801, 2651, 3501, 4351],
                "vertical": [240, 638, 960, 1277, 1680],
            },
            "layers": [
                {
                    "id": f"L{i}", "kind": "pixel",
                    "bbox": {
                        "x": 500, "y": y, "width": 300, "height": 100,
                    },
                }
                for i, y in enumerate([400, 1200, 2050, 2900, 3750, 5000], 1)
            ],
        }

        sections = sectionize.split_sections(layout)

        self.assertEqual(
            [(0, 951), (951, 1801), (1801, 2651), (2651, 3501),
             (3501, 4351), (4351, 5807)],
            [(s["y0"], s["y1"]) for s in sections],
        )
        self.assertEqual(
            ["Section 1", "Section 2", "Section 3", "Section 4",
             "Section 5", "Section 6"],
            [s["name"] for s in sections],
        )

    def test_editor_manifest_uses_detected_guide_sections(self):
        layout = {
            "canvas": {"width": 1000, "height": 2400},
            "guides": {"horizontal": [800, 1600], "vertical": []},
            "screenshot": "screenshot.png",
            "layers": [
                {
                    "id": "L1", "name": "Hero", "kind": "pixel",
                    "parent": None, "bbox": {
                        "x": 100, "y": 100, "width": 200, "height": 100,
                    },
                    "asset": "assets/L1.webp",
                },
                {
                    "id": "L2", "name": "Gift", "kind": "pixel",
                    "parent": None, "bbox": {
                        "x": 100, "y": 1700, "width": 200, "height": 100,
                    },
                    "asset": "assets/L2.webp",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "layout.json").write_text(
                json.dumps(layout), encoding="utf-8"
            )

            manifest = webapp._variant_manifest("demo", out, "")

        self.assertEqual(
            [(0, 800), (800, 1600), (1600, 2400)],
            [(s["y0"], s["y1"]) for s in manifest["sections"]],
        )
        self.assertEqual([0, 2], [item["section"] for item in manifest["layers"]])
    def test_asset_config_is_per_parse(self):
        png = parser._asset_cfg("png", None, None)
        webp = parser._asset_cfg("webp", 77, 123)

        self.assertEqual("png", png["fmt"])
        self.assertEqual("webp", webp["fmt"])
        self.assertEqual(77, webp["quality"])
        self.assertEqual(123, webp["lossless_max"])

        png["fmt"] = "changed"
        self.assertEqual("webp", webp["fmt"])

    def test_save_asset_uses_passed_config(self):
        image = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            png = parser._asset_cfg("png", None, None)
            webp = parser._asset_cfg("webp", 90, 100)

            self.assertEqual("L1.png", parser._save_asset(image, out, "L1", png))
            self.assertEqual("L2.webp", parser._save_asset(image, out, "L2", webp))
            self.assertTrue((out / "L1.png").is_file())
            self.assertTrue((out / "L2.webp").is_file())


class JobSafetyTests(unittest.TestCase):
    def test_result_and_download_reject_parent_job_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "jobs"
            root.mkdir()
            escaped_out = root.parent / "out"
            escaped_out.mkdir()
            (escaped_out / "proof.txt").write_text("secret", encoding="utf-8")
            (root.parent / "result.zip").write_bytes(b"not-a-job")

            old_token = webapp._ACCESS_TOKEN
            webapp._ACCESS_TOKEN = ""
            try:
                with patch.object(webapp, "JOBS_DIR", root):
                    client = webapp.app.test_client()
                    self.assertEqual(
                        404, client.get("/result/../proof.txt").status_code
                    )
                    self.assertEqual(404, client.get("/download/..").status_code)
            finally:
                webapp._ACCESS_TOKEN = old_token

    def test_popup_variant_cannot_escape_to_another_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "job-a" / "out" / "_popups").mkdir(parents=True)
            target = root / "job-b" / "out"
            target.mkdir(parents=True)
            (target / "layout.json").write_text("{}", encoding="utf-8")

            with patch.object(webapp, "JOBS_DIR", root):
                self.assertIsNone(
                    webapp._variant_dir(
                        "job-a", "popup:../../../job-b/out"
                    )
                )

    def test_new_job_id_skips_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "old").mkdir()
            ids = [SimpleNamespace(hex="old"), SimpleNamespace(hex="new")]
            with patch.object(webapp, "JOBS_DIR", root), \
                    patch.object(webapp.uuid, "uuid4", side_effect=ids):
                self.assertEqual("new", webapp._new_job_id())

    def test_only_one_background_task_per_job(self):
        job_id = "lock-test"
        started = threading.Event()
        finish = threading.Event()

        def slow():
            started.set()
            finish.wait(2)

        self.assertTrue(webapp._start_job_task(job_id, slow))
        self.assertTrue(started.wait(1))
        self.assertFalse(webapp._start_job_task(job_id, lambda: None))
        finish.set()

        lock = webapp._job_lock(job_id)
        for _ in range(100):
            if not lock.locked():
                break
            threading.Event().wait(0.01)
        self.assertFalse(lock.locked())
        self.assertTrue(webapp._start_job_task(job_id, lambda: None))

    def test_write_route_returns_conflict_while_job_is_busy(self):
        job_id = "route-lock-test"
        lock = webapp._job_lock(job_id)
        self.assertTrue(lock.acquire(blocking=False))
        old_token = webapp._ACCESS_TOKEN
        webapp._ACCESS_TOKEN = ""
        try:
            response = webapp.app.test_client().post(
                "/edit", json={"job_id": job_id, "patch": {}})
            self.assertEqual(409, response.status_code)
        finally:
            webapp._ACCESS_TOKEN = old_token
            lock.release()

    def test_job_list_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jdir = root / "recent-job"
            (jdir / "d").mkdir(parents=True)
            (jdir / "out").mkdir()
            (jdir / "d" / "01-hero.psd").write_bytes(b"psd")
            (jdir / "out" / "layout.json").write_text("{}", encoding="utf-8")
            old_token = webapp._ACCESS_TOKEN
            webapp._ACCESS_TOKEN = ""
            try:
                with patch.object(webapp, "JOBS_DIR", root):
                    client = webapp.app.test_client()
                    listing = client.get("/jobs")
                    self.assertEqual(200, listing.status_code)
                    item = listing.get_json()["jobs"][0]
                    self.assertEqual("recent-job", item["id"])
                    self.assertTrue(item["ready"])
                    self.assertGreater(item["size"], 0)

                    deleted = client.delete("/jobs/recent-job")
                    self.assertEqual(200, deleted.status_code)
                    self.assertFalse(jdir.exists())
            finally:
                webapp._ACCESS_TOKEN = old_token

    def test_cleanup_removes_only_expired_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "old-job"
            fresh = root / "fresh-job"
            old.mkdir()
            fresh.mkdir()
            (old / "file.bin").write_bytes(b"old")
            (fresh / "file.bin").write_bytes(b"fresh")
            old_time = time.time() - 10 * 86400
            os.utime(old / "file.bin", (old_time, old_time))
            os.utime(old, (old_time, old_time))

            with patch.object(webapp, "JOBS_DIR", root):
                removed = webapp._cleanup_old_jobs(7)

            self.assertEqual(["old-job"], removed)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())


class LanAuthTests(unittest.TestCase):
    def setUp(self):
        self.old_token = webapp._ACCESS_TOKEN
        webapp._ACCESS_TOKEN = "demo-secret"
        self.client = webapp.app.test_client()

    def tearDown(self):
        webapp._ACCESS_TOKEN = self.old_token

    def test_token_link_sets_cookie(self):
        self.assertEqual(401, self.client.get("/").status_code)

        login = self.client.get("/?token=demo-secret")
        self.assertEqual(302, login.status_code)
        self.assertIn("HttpOnly", login.headers.get("Set-Cookie", ""))

        self.assertEqual(200, self.client.get("/").status_code)

    def test_wrong_token_is_rejected(self):
        self.assertEqual(401, self.client.get("/?token=wrong").status_code)

    def test_preview_uses_configured_lan_host(self):
        env = {
            "PSD2HTML_HOST": "0.0.0.0",
            "PSD2HTML_PUBLIC_HOST": "192.168.1.20",
        }
        with patch.dict(webapp._os.environ, env, clear=False):
            self.assertTrue(webapp._is_lan_host())
            self.assertEqual("192.168.1.20", webapp._preview_public_host())


if __name__ == "__main__":
    unittest.main()
