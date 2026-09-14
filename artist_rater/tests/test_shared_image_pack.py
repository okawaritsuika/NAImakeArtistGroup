import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin

import arca_image_archive as archive_module
from arca_style_collector import init_arca_style_tables, get_collection_job, import_arca_style_seed, get_arca_style_statistics, get_arca_tag_statistics
from build_shared_image_archive import build_archive


class SharedImagePackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.seed, self.local = self.root / 'seed.sqlite', self.root / 'local.sqlite'
        self.source_images = self.root / 'originals'
        self.source_images.mkdir()
        self.images = self.root / 'installed'
        self.url = 'https://ac.namu.la/one.png?expires=1&key=old'
        for path, item_id, image_id, image_url in [
            (self.seed, 1, 1, self.url),
            (self.local, 20, 30, 'https://ac.arca.live/one.png?expires=99&key=new'),
        ]:
            init_arca_style_tables(path)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("INSERT INTO arca_style_items(id,source_url,representative_image_url,collected_at,updated_at) VALUES(?, 'https://arca.live/b/aiart/1',?,'now','now')", (item_id, image_url))
                db.execute("INSERT INTO arca_style_images(id,item_id,image_url,image_path,metadata_status,created_at) VALUES(?,?,?,'original.png','ok','now')",(image_id,item_id,image_url))
        info = PngImagePlugin.PngInfo()
        info.add_text('Comment', json.dumps({'prompt':'artist:test','seed':4,'steps':28,'model':'nai-diffusion-5-full'}))
        buffer = io.BytesIO()
        Image.new('RGB',(16,16),(30,40,50)).save(buffer,'PNG',pnginfo=info)
        (self.source_images / 'original.png').write_bytes(buffer.getvalue())

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        return build_archive(self.seed,[(self.seed,self.source_images)],self.root / 'pack',workers=1)

    def install(self, info):
        return archive_module.install_image_archive(
            self.root / 'pack' / info['filename'],self.local,self.images,self.seed,
            expected_archive_sha256=info['sha256'],expected_archive_bytes=info['bytes'],
            expected_count=info['image_count'],expected_bytes=info['image_bytes'],
        )

    def test_webp_pack_links_every_local_duplicate_and_preserves_original(self):
        before = hashlib.sha256((self.source_images/'original.png').read_bytes()).hexdigest()
        with closing(sqlite3.connect(self.local)) as db, db:
            db.execute("INSERT INTO arca_style_images(id,item_id,image_url,metadata_status,created_at) VALUES(31,20,?,'ok','now')",(self.url,))
        info = self.build()
        result = self.install(info)
        self.assertEqual(result, {'installed':1,'reused':0,'updated_rows':2,'skipped_rows':0})
        self.assertEqual(archive_module._missing_seed_images(self.local,self.images,self.seed),0)
        with closing(sqlite3.connect(self.local)) as db:
            paths = db.execute('SELECT image_path FROM arca_style_images').fetchall()
            representative = db.execute('SELECT representative_image_path FROM arca_style_items').fetchone()[0]
        self.assertEqual(paths[0],paths[1])
        self.assertEqual(representative,paths[0][0])
        self.assertTrue(representative.endswith('.webp'))
        self.assertEqual(hashlib.sha256((self.source_images/'original.png').read_bytes()).hexdigest(),before)
        self.assertEqual(self.install(info)['reused'],1)

    def test_modern_pack_rejects_newer_seed_with_uncovered_images(self):
        info = self.build()
        with closing(sqlite3.connect(self.seed)) as db, db:
            db.execute("INSERT INTO arca_style_images(item_id,image_url,metadata_status,created_at) VALUES(1,'https://ac.namu.la/two.webp','ok','now')")
        with self.assertRaisesRegex(archive_module.ArcaImageArchiveError,'빠져'):
            self.install(info)

    def test_upgrade_reuses_old_png_without_duplicate_rows_and_adds_only_missing(self):
        self.images.mkdir()
        original = (self.source_images / 'original.png').read_bytes()
        (self.images / 'original.png').write_bytes(original)
        with closing(sqlite3.connect(self.seed)) as db, db:
            db.execute("INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,created_at) VALUES(1,'https://ac.namu.la/new.png','original.png','ok','now')")
        info = self.build()
        result = import_arca_style_seed(self.local, self.seed)
        self.assertEqual(result['images'], 1)
        # A metadata-only seed never supplies paths for newly imported rows.
        with closing(sqlite3.connect(self.local)) as db, db:
            db.execute("UPDATE arca_style_images SET image_path='' WHERE image_url LIKE '%new.png'")
        result = self.install(info)
        self.assertEqual(result, {'installed': 1, 'reused': 1, 'updated_rows': 2, 'skipped_rows': 0})
        self.assertEqual((self.images / 'original.png').read_bytes(), original)
        self.assertEqual(len(list(self.images.iterdir())), 2)
        self.assertEqual(archive_module._missing_seed_images(self.local, self.images, self.seed), 0)
        self.assertFalse(import_arca_style_seed(self.local, self.seed)['imported'])
        self.assertEqual(self.install(info)['installed'], 0)

    def test_broken_existing_file_is_repaired(self):
        self.images.mkdir()
        (self.images / 'original.png').write_bytes(b'broken')
        info = self.build()
        self.assertEqual(self.install(info)['installed'], 1)
        self.assertEqual(archive_module._missing_seed_images(self.local, self.images, self.seed), 0)

    def test_modified_pack_file_is_repaired_even_if_it_is_a_valid_image(self):
        info = self.build()
        self.install(info)
        target = next(self.images.glob('*.webp'))
        expected = hashlib.sha256(target.read_bytes()).hexdigest()
        Image.new('RGB', (16, 16), 'red').save(target, 'WEBP')
        self.assertEqual(self.install(info)['installed'], 1)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), expected)

    def test_statistics_separates_models_within_one_shared_post(self):
        with closing(sqlite3.connect(self.local)) as db, db:
            db.execute("UPDATE arca_style_items SET title='그림체 공유',board_tab='NAI',metadata_status='ok',prompt='artist:shared'")
            db.execute("DELETE FROM arca_style_images")
            for index, generation in enumerate(('v4.5', 'v5', 'unknown')):
                db.execute("INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,model_family,model_generation,created_at) VALUES(20,?,'ok',?,?,?,'now')", (f'https://img/{index}.png', f'artist:model{index}, masterpiece', generation, generation))
        for index, model in enumerate(('v4.5', 'v5')):
            result = get_arca_style_statistics(self.local, {'model': model})
            self.assertEqual([entry['tag'] for entry in result['artists']], [f'artist:model{index}'])
            details = get_arca_tag_statistics(self.local, 'quality', 'masterpiece', filters={'model': model})
            self.assertEqual(len(details['images']), 1)
            self.assertEqual(details['images'][0]['image_url'], f'https://img/{index}.png')

    def test_completed_legacy_job_warns_about_images_absent_from_manifest(self):
        path = self.root / 'legacy.zip'
        path.write_bytes(b'fixture')
        job_id = archive_module._create_archive_job(self.local,'local',path)
        with patch.object(archive_module,'install_image_archive',return_value={
            'installed':1,'reused':0,'updated_rows':1,'skipped_rows':0,
        }):
            archive_module._run_archive_job(self.local,self.images,self.root,self.seed,job_id,'local',path)
        job = get_collection_job(self.local,job_id)
        self.assertIn('1장이 아직 없습니다',job['error'])
        self.assertTrue(path.exists())
