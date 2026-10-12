"""Connection form text and validation, without GTK."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import nas_form  # noqa: E402
from nas_core import FieldError  # noqa: E402


def values(**changes):
    base = {
        "label": "Shared documents",
        "server": "fileserver",
        "remote": "shared/documents",
        "local": "/mnt/nas-documents",
        "username": "<USERNAME>",
        "password": "<PASSWORD>",
        "domain": "",
    }
    return dict(base, **changes)


class FormCopyTests(unittest.TestCase):
    def test_each_mode_names_what_its_button_does(self):
        self.assertEqual(
            nas_form.form_copy(adding=True, login_only=False)["confirm"],
            "Save and mount",
        )
        edit = nas_form.form_copy(adding=False, login_only=False)
        self.assertEqual(edit["title"], "Edit connection")
        self.assertEqual(edit["confirm"], "Save changes")
        login = nas_form.form_copy(adding=False, login_only=True)
        self.assertEqual(login["title"], "Connect to NAS")
        self.assertEqual(login["confirm"], "Mount")

    def test_fields_are_grouped_into_sections(self):
        groups = {key: nas_form.field_group(key) for key, _ in nas_form.FIELDS}
        self.assertEqual(groups["server"], "Connection")
        self.assertEqual(groups["local"], "Local folder")
        self.assertEqual(groups["password"], "Login")
        self.assertEqual(set(nas_form.HINTS), {key for key, _ in nas_form.FIELDS})


class ParseFormTests(unittest.TestCase):
    def test_valid_values_become_a_profile_and_a_login(self):
        clean, entered = nas_form.parse_form(
            values(label="  Docs  "), "id-1", encrypt=False, allow_exec=True
        )
        self.assertEqual(clean["id"], "id-1")
        self.assertEqual(clean["label"], "Docs")
        self.assertEqual(clean["source"], "//fileserver/shared/documents")
        self.assertFalse(clean["encrypt"])
        self.assertTrue(clean["allow_exec"])
        self.assertEqual(set(entered), {"username", "password", "domain"})
        self.assertNotIn("password", clean)

    def test_each_invalid_value_points_at_its_field(self):
        for changes, field in (
            ({"label": "  "}, "label"),
            ({"server": "bad host!"}, "server"),
            ({"remote": "a,b"}, "remote"),
            ({"local": "/etc/x"}, "local"),
            ({"username": ""}, "username"),
        ):
            with (
                self.subTest(field=field),
                self.assertRaises(FieldError) as caught,
            ):
                nas_form.parse_form(values(**changes), "id-1", True, False)
            self.assertEqual(caught.exception.field, field)


if __name__ == "__main__":
    unittest.main()
