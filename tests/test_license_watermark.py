# -*- coding: utf-8 -*-
"""商用授权客户水印与审计字段测试。"""
import unittest
from pathlib import Path

from _common import APP  # noqa: F401

import license_guard

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"


class LicenseWatermarkTests(unittest.TestCase):
    def test_page_has_customer_watermark(self):
        page = (APP_DIR / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        self.assertIn('id="licenseMark"', page)
        self.assertIn('id="licenseCustomer"', page)
        self.assertIn('fetch("/api/license"', page)
        self.assertIn('name.textContent = customer.length > 48', page)

    def test_star_map_has_customer_watermark(self):
        page = (APP_DIR / "宇宙接口图.html").read_text(encoding="utf-8")
        self.assertIn('id="licenseMark"', page)
        self.assertIn('id="licenseCustomer"', page)
        self.assertIn("fetch('/api/license'", page)

    def test_i18n_has_customer_label(self):
        text = (APP_DIR / "i18n.js").read_text(encoding="utf-8")
        self.assertIn("'客户': 'Customer'", text)

    def test_audit_fields_include_customer_and_fingerprint(self):
        import app_core
        old = license_guard.status
        try:
            license_guard.status = lambda force=False: {
                "commercial": True,
                "customer": "测试客户",
                "machine_code": "ABCD-EF01-2345-6789-ABCD-EF01",
            }
            fields = app_core.license_audit_fields()
            self.assertEqual(fields["license_customer"], "测试客户")
            self.assertRegex(fields["license_fp"], r"^[0-9a-f]{12}$")

            license_guard.status = lambda force=False: {"commercial": False}
            self.assertEqual(app_core.license_audit_fields(), {})
        finally:
            license_guard.status = old


if __name__ == "__main__":
    unittest.main()
