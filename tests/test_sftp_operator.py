#!/usr/bin/env python3
from __future__ import annotations

import os
import unittest

from backend import sftp_operator as sftp


def _config() -> dict[str, object]:
    return {
        "schema": sftp.SCHEMA,
        "host": "ssh.one.com",
        "user": "goldgoblins",
        "port": 22,
        "remote_root": "/customers/0/example/httpd.www",
        "identity_file": "",
    }


class SftpOperatorTests(unittest.TestCase):
    def test_password_field_rejected(self) -> None:
        bad = dict(_config())
        bad["password"] = "no"
        with self.assertRaises(sftp.SftpOperatorError) as exc:
            sftp.validate_config(bad)
        self.assertIn("CREDENTIAL_FIELD_FORBIDDEN", str(exc.exception))

    def test_put_get_allowlist_and_batchmode(self) -> None:
        cfg = sftp.validate_config(_config())
        self.assertEqual(cfg["general_action_authority"], "NONE")
        self.assertNotIn("password", cfg)
        get_plan = sftp.plan("GET", "robots.txt", _config())
        self.assertIn("BatchMode=yes", get_plan["argv"])
        self.assertIn("AddressFamily=inet", get_plan["argv"])
        self.assertIn("IdentitiesOnly=yes", get_plan["argv"])
        self.assertIn("get robots.txt", get_plan["batch"])
        self.assertEqual(get_plan["risk_class"], "RED")
        put_plan = sftp.plan(
            "PUT",
            "wp-content/mu-plugins/gg-site-completion.php",
            _config(),
        )
        self.assertIn("put wp-content/mu-plugins/gg-site-completion.php", put_plan["batch"])
        theme_plan = sftp.plan(
            "PUT",
            "wp-content/themes/blankslate/header.php",
            _config(),
        )
        self.assertIn("put wp-content/themes/blankslate/header.php", theme_plan["batch"])
        with self.assertRaises(sftp.SftpOperatorError):
            sftp.plan("PUT", "wp-config.php", _config())
        with self.assertRaises(sftp.SftpOperatorError):
            sftp.plan("GET", "../secret", _config())

    def test_run_requires_agent_and_never_takes_password(self) -> None:
        self.assertTrue(callable(sftp.run))
        saved = os.environ.pop("SSH_AUTH_SOCK", None)
        try:
            with self.assertRaises(sftp.SftpOperatorError) as exc:
                sftp.run("GET", "robots.txt", _config())
            self.assertIn("SSH_AGENT", str(exc.exception))
        finally:
            if saved is not None:
                os.environ["SSH_AUTH_SOCK"] = saved


if __name__ == "__main__":
    unittest.main()
