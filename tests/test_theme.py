"""Synthetic palette tests; do not change the desktop's theme."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("nas_theme"), "Omarchy palette integration missing"
        )
        import nas_theme

        self.theme = nas_theme
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.override = self.folder / "user-shell.toml"

    def write_theme(self):
        (self.folder / "colors.toml").write_text(
            'background = "#102030"\nforeground = "#ddeeff"\naccent = "#506070"\ngreen = "#809090"\nred = "#aa1020"\nyellow = "#bbcc00"\n'
        )

    def test_palette_uses_the_omarchy_colors(self):
        self.write_theme()
        palette = self.theme.read_palette(self.folder, self.override)
        self.assertEqual(palette["background"], "#102030")
        self.assertEqual(palette["foreground"], "#ddeeff")
        self.assertEqual(palette["accent"], "#506070")

    def test_user_popup_colors_override_the_theme(self):
        self.write_theme()
        (self.folder / "shell.toml").write_text(
            '[popups]\nbackground = "#223344"\ntext = "foreground"\n'
        )
        self.override.write_text('[popups]\nbackground = "#556677"\ntext = "#abcdef"\n')
        palette = self.theme.read_palette(self.folder, self.override)
        self.assertEqual(palette["background"], "#556677")
        self.assertEqual(palette["foreground"], "#abcdef")

    def test_css_injection_is_rejected(self):
        self.write_theme()
        self.override.write_text(
            '[popups]\nbackground = "#ff0000; } button { color: red"\n'
        )
        self.assertEqual(
            self.theme.read_palette(self.folder, self.override)["background"], "#102030"
        )

    def test_missing_theme_keeps_gtk_fallback(self):
        self.assertEqual(self.theme.read_palette(self.folder, self.override), {})

    def test_new_theme_is_picked_up_without_restarting(self):
        self.write_theme()
        first = self.theme.read_palette(self.folder, self.override)
        (self.folder / "colors.toml").write_text(
            'background = "#001122"\nforeground = "#ffffff"\naccent = "#112233"\n'
        )
        second = self.theme.read_palette(self.folder, self.override)
        self.assertNotEqual(first, second)
        self.assertEqual(second["background"], "#001122")

    def test_fonts_default_to_the_omarchy_type_scale(self):
        fonts = self.theme.read_fonts(self.folder, self.override)
        self.assertEqual(
            fonts,
            {
                "caption": 10,
                "body-small": 11,
                "body": 12,
                "subtitle": 13,
                "title": 14,
                "heading": 16,
            },
        )

    def test_fonts_follow_base_size_and_user_overrides(self):
        (self.folder / "shell.toml").write_text("[font]\nbase-size = 15\n")
        self.override.write_text("[font]\nbase-size = 18\ntitle = 30\n")
        fonts = self.theme.read_fonts(self.folder, self.override)
        self.assertEqual(fonts["body"], 18)
        self.assertEqual(fonts["caption"], 15)
        self.assertEqual(fonts["heading"], 24)
        self.assertEqual(fonts["title"], 30)

    def test_invalid_font_values_keep_defaults(self):
        self.override.write_text(
            '[font]\nbase-size = "12px; } * { color: red"\nbody = -4\ntitle = true\n'
        )
        fonts = self.theme.read_fonts(self.folder, self.override)
        self.assertEqual(fonts["body"], 12)
        self.assertEqual(fonts["title"], 14)

    def test_font_css_maps_tokens_to_classes(self):
        css = self.theme.font_css(self.theme.read_fonts(self.folder, self.override))
        self.assertIn(b".nas-title { font-size: 12px; }", css)
        self.assertIn(b".nas-status { font-size: 10px; }", css)
        self.assertIn(b".nas-badge { font-size: 10px; }", css)
        self.assertIn(b".nas-manager, .nas-editor { font-size: 11px; }", css)
        # Section labels match Omarchy's PanelSectionHeader (caption size).
        self.assertIn(b".nas-section { font-size: 10px; }", css)


class PaletteCssTests(unittest.TestCase):
    def test_only_known_roles_with_hex_colors_reach_css(self):
        import nas_theme

        css = nas_theme.palette_css(
            {
                "background": "#060B1E",
                "accent": "#7d82d9",
                "red": "red; } * { color: #fff",
                "unknown": "#123456",
            }
        ).decode()
        self.assertIn("@define-color nas_bg #060B1E;", css)
        self.assertIn("@define-color nas_accent #7d82d9;", css)
        self.assertNotIn("nas_error", css)
        self.assertNotIn("#123456", css)


if __name__ == "__main__":
    unittest.main()
