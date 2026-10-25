import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin
import arca_style_collector as collector


class WebpCollectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'data.sqlite'
        collector.init_arca_style_tables(self.db)
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('Comment', json.dumps({'prompt': 'artist:test, 한국어', 'uc': 'bad', 'seed': 73, 'model': 'nai-diffusion-5-full'}))
        buffer = io.BytesIO()
        Image.new('RGB', (32, 32), 'blue').save(buffer, 'PNG', pnginfo=metadata)
        self.original = buffer.getvalue()
        self.article = dict(source_url='https://arca.live/b/aiart/123', article_id='123', board_tab='NAI',
                            title='그림체 공유', author='test', posted_at='2026-09-14', body_text='',
                            image_urls=['https://img.example/image.png'])

    def tearDown(self):
        self.temp.cleanup()

    def save(self, compress):
        summary = dict(saved=0, updated=0, metadata_ok=0, no_metadata=0, items=[])
        with patch.object(collector, 'download_image', return_value=(self.original, 'image/png')) as download:
            collector._save_article(self.db, self.root / 'images', object(), self.article, summary, webp_compress=compress)
        with closing(sqlite3.connect(self.db)) as db:
            row = db.execute('SELECT image_path,content_type FROM arca_style_images').fetchone()
        return self.root / 'images' / row[0], row[1], download.call_count

    def test_compression_preserves_metadata_and_reuses_existing_file(self):
        path, mime, calls = self.save(True)
        self.assertEqual(mime, 'image/webp')
        self.assertEqual(path.suffix, '.webp')
        before, after = collector.extract_novelai_metadata(self.original), collector.extract_novelai_metadata(path.read_bytes())
        before['raw_metadata_json'] = json.loads(before['raw_metadata_json'])
        after['raw_metadata_json'] = json.loads(after['raw_metadata_json'])
        self.assertEqual(before, after)
        self.assertEqual(calls, 1)
        self.assertEqual(self.save(False)[2], 0)

    def test_unchecked_keeps_png_and_later_check_does_not_convert_existing(self):
        path, mime, _ = self.save(False)
        self.assertEqual(mime, 'image/png')
        self.assertEqual(path.read_bytes(), self.original)
        with patch('shared_style_webp.verified_webp', side_effect=AssertionError('must reuse')):
            self.assertEqual(self.save(True)[2], 0)

    def test_failed_metadata_verification_keeps_original(self):
        with patch('shared_style_webp.verified_webp', side_effect=ValueError('metadata mismatch')):
            path, mime, _ = self.save(True)
        self.assertEqual(mime, 'image/png')
        self.assertEqual(path.read_bytes(), self.original)

    def test_option_survives_job_storage_and_direct_resume(self):
        params = collector.normalize_collect_payload({'webp_compress': True})
        self.assertTrue(params['webp_compress'])
        job = collector.create_collection_job(self.db, params)
        self.assertTrue(json.loads(collector.get_collection_job(self.db, job)['request_json'])['webp_compress'])
        job = collector.create_url_collection_job(self.db, self.article['source_url'], webp_compress=True)
        collector.update_collection_job(self.db, job, status='failed')
        with patch.object(collector, 'start_url_collection_job', return_value=99) as start:
            self.assertEqual(collector.resume_collection_job(self.db, self.root / 'images', job), 99)
        self.assertTrue(start.call_args.kwargs['webp_compress'])
        with self.assertRaises(collector.ArcaCollectorError):
            collector.normalize_collect_payload({'webp_compress': 'false'})
