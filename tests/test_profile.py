import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from render import render, safe_projects, treemap, language_svg
from update_profile import eligible, extract_sources


class ProfileTests(unittest.TestCase):
    def test_private_metadata_never_published(self):
        secret = 'SECRET-REPO-NAME-123'
        repo = {'private': True, 'name': secret, 'description': secret, 'html_url': 'https://github.com/'+secret, 'pushed_at': '2026-10-25'}
        self.assertEqual(safe_projects([repo]), [{'private': True}])
        config = json.loads((Path(__file__).resolve().parents[1]/'profile.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            render(config, {'languages': {'Python': 10}, 'repositories': [repo], 'activity': [], 'coverage': 'Test', 'updated': 'Test'}, folder)
            for file in Path(folder).rglob('*'):
                if file.is_file():
                    self.assertNotIn(secret, file.read_text(encoding='utf-8'))

    def test_treemap_area_tracks_lines(self):
        tiles = treemap([('Python', 49), ('TS', 27), ('Java', 14), ('C++', 10)])
        total_area = 904 * (904/1.618)
        for (_, value), x, y, width, height in tiles:
            self.assertAlmostEqual(width*height/total_area, value/100)
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)

    def test_empty_single_and_many_languages_are_valid_svg(self):
        for values in [{}, {'C++': 1}, {f'Lang {i}': i+1 for i in range(100)}, {'<script>&': 20}]:
            ET.fromstring(language_svg(values))

    def test_recent_order_and_private_redaction(self):
        repos = [{'private': True, 'pushed_at': f'2026-10-{i:02}'} for i in range(1, 6)]
        self.assertEqual(len(safe_projects(repos)), 3)

    def test_traversal_rejected(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('repo/../../escape.py', 'x=1')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                extract_sources(raw.getvalue(), Path(folder), set())

    def test_dependencies_excluded(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('repo/node_modules/package/a.js', 'secret')
            archive.writestr('repo/main.py', 'x=1')
        with tempfile.TemporaryDirectory() as folder:
            extract_sources(raw.getvalue(), Path(folder), {'node_modules'})
            self.assertEqual([p.name for p in Path(folder).rglob('*')], ['main.py'])


if __name__ == '__main__':
    unittest.main()
