"""Run the client-state regression checks without browser or network access."""
import os
import shutil
import subprocess
import unittest


class MobilityFormJavascriptTest(unittest.TestCase):
    def test_form_privacy_and_draft_preservation(self):
        node = '/opt/homebrew/opt/node@24/bin/node'
        if not os.path.exists(node):
            node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is not installed')
        result = subprocess.run(
            [node, '--test', 'tests/mobility_form.test.cjs'],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
