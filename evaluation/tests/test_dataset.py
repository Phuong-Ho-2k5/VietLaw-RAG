import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evaluation import dataset


ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / 'data/manifests/m1/labor-corpus-v1.json'


def row(corpus, index, split='dev'):
    chunk = corpus['chunks'][index]
    return {
        'schema_version': 1, 'question_id': f'q-{index}',
        'question': f'Câu hỏi {index}?', 'split': split,
        'family_id': f'article-{chunk["article_label"]}',
        'category': 'direct', 'scope': 'in_scope',
        'topic': chunk['topic_tags'][0], 'as_of_date': chunk['as_of_date'],
        'expected_behavior': 'answer', 'expected_answer': 'Câu trả lời có căn cứ.',
        'gold': [{'document_number': chunk['document_number'],
                  'article': chunk['article_label'], 'clause': chunk['clause_label'],
                  'point': chunk['point_label'], 'chunk_id': chunk['chunk_id']}],
        'snapshot_id': corpus['manifest_hash'],
        'reviewer': 'Codex (assistant)', 'reviewed_at': '2026-10-08',
        'review_note': 'Đã kiểm câu hỏi, gold và điều kiện trong nguồn.',
        'evidence': [{'kind': 'legal_source', 'chunk_id': chunk['chunk_id'],
                      'url': chunk['source_evidence']['url'],
                      'pdf_page': chunk['source_evidence']['pdf_page']}],
    }


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows),
                    encoding='utf-8')


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads(CORPUS_PATH.read_text(encoding='utf-8'))
        self.dev = [row(self.corpus, 0)]
        self.test = [row(self.corpus, 3, 'test')]

    def validate(self):
        return dataset.validate_dataset(self.dev, self.test, self.dev, self.corpus,
                                        min_questions=2, seed_count=1)

    def reject(self, mutation, message):
        mutation()
        with self.assertRaisesRegex(ValueError, message):
            self.validate()

    def test_valid_dataset_maps_gold_and_counts(self):
        self.assertEqual(self.validate()['counts'], {'dev': 1, 'test': 1, 'total': 2, 'seed': 1})

    def test_schema_rejects_missing_wrong_and_unknown_fields(self):
        for field, value in [('question', ''), ('gold', 'bad'), ('as_of_date', '2026-02-30'),
                             ('reviewer', ''), ('scope', 'unknown'), ('extra', True),
                             ('schema_version', True), ('reviewed_at', '2026-1-1')]:
            with self.subTest(field=field):
                saved = copy.deepcopy(self.dev)
                self.dev[0][field] = value
                with self.assertRaises(ValueError):
                    self.validate()
                self.dev = saved
        del self.dev[0]['review_note']
        with self.assertRaises(ValueError):
            self.validate()

    def test_gold_labels_chunk_and_source_must_match(self):
        for field, value in [('article', '99'), ('clause', '9'), ('document_number', 'fake'),
                             ('chunk_id', '0' * 64)]:
            with self.subTest(field=field):
                saved = copy.deepcopy(self.dev)
                self.dev[0]['gold'][0][field] = value
                with self.assertRaises(ValueError):
                    self.validate()
                self.dev = saved
        self.reject(lambda: self.dev[0]['evidence'][0].update(url='https://example.com'), 'evidence')

    def test_multi_unit_requires_multiple_gold_and_all_evidence(self):
        self.dev[0]['category'] = 'multi_unit'
        with self.assertRaisesRegex(ValueError, 'multi_unit'):
            self.validate()
        second = row(self.corpus, 1)
        self.dev[0]['gold'] += second['gold']
        with self.assertRaisesRegex(ValueError, 'evidence'):
            self.validate()
        self.dev[0]['evidence'] += second['evidence']
        self.validate()

    def test_article_and_family_cannot_cross_splits(self):
        self.test = [row(self.corpus, 1, 'test')]
        self.test[0]['family_id'] = 'different-family'
        with self.assertRaisesRegex(ValueError, 'article leakage'):
            self.validate()
        self.test = [row(self.corpus, 3, 'test')]
        self.test[0]['family_id'] = self.dev[0]['family_id']
        with self.assertRaisesRegex(ValueError, 'family leakage'):
            self.validate()

    def test_duplicate_questions_use_unicode_and_whitespace_normalization(self):
        self.dev[0]['question'] = 'Câu hỏi này?'
        self.test[0]['question'] = '  Ca\u0302u  HO\u0309I này?  '
        with self.assertRaisesRegex(ValueError, 'duplicate question'):
            self.validate()

    def test_answer_cannot_use_unverified_date_or_snapshot(self):
        self.reject(lambda: self.dev[0].update(as_of_date='2026-10-08'), 'date')
        self.dev[0]['as_of_date'] = '2026-02-12'
        self.reject(lambda: self.dev[0].update(snapshot_id='0' * 64), 'snapshot')

    def test_abstain_requires_empty_gold_and_scope_evidence(self):
        self.dev[0].update(category='insufficient_evidence', expected_behavior='abstain')
        with self.assertRaisesRegex(ValueError, 'abstain'):
            self.validate()
        self.dev[0]['gold'] = []
        self.dev[0]['evidence'] = [{'kind': 'corpus_scope', 'snapshot_id': self.corpus['manifest_hash'],
                                   'reason': 'Chưa có điều quy định nội dung cần hỏi.'}]
        self.validate()

    def test_temporal_abstain_rejects_verified_date(self):
        self.dev[0].update(category='temporal', expected_behavior='abstain', gold=[],
            evidence=[{'kind': 'corpus_scope', 'snapshot_id': self.corpus['manifest_hash'],
                       'reason': 'Ngày chưa được kiểm chứng.'}])
        with self.assertRaisesRegex(ValueError, 'temporal'):
            self.validate()
        self.dev[0]['as_of_date'] = None
        self.validate()

    def test_seed_must_be_exact_dev_subset(self):
        seed = copy.deepcopy(self.dev)
        seed[0]['expected_answer'] = 'Khác'
        with self.assertRaisesRegex(ValueError, 'seed'):
            dataset.validate_dataset(self.dev, self.test, seed, self.corpus,
                                     min_questions=2, seed_count=1)

    def test_seed_invalid_question_id_raises_value_error(self):
        for invalid_id in ([], {}, None, 123, True, '', '   '):
            with self.subTest(question_id=invalid_id):
                seed = copy.deepcopy(self.dev)
                seed[0]['question_id'] = invalid_id
                with self.assertRaisesRegex(ValueError, 'seed'):
                    dataset.validate_dataset(self.dev, self.test, seed, self.corpus,
                                             min_questions=2, seed_count=1)

    def test_inactive_or_tampered_corpus_rejected(self):
        saved = copy.deepcopy(self.corpus)
        self.corpus['active'] = False
        with self.assertRaisesRegex(ValueError, 'inactive'):
            self.validate()
        self.corpus = saved
        self.corpus['chunks'][0]['text'] += 'sửa'
        with self.assertRaisesRegex(ValueError, 'corpus'):
            self.validate()

    def test_non_string_enum_values_fail_with_validation_error(self):
        for field in ('category', 'topic', 'scope', 'as_of_date'):
            with self.subTest(field=field):
                saved = copy.deepcopy(self.dev)
                self.dev[0][field] = []
                with self.assertRaises(ValueError):
                    self.validate()
                self.dev = saved

    def test_curation_reproduces_published_question_records(self):
        from evaluation.curate import build_rows
        expected = {r['question_id']: r for r in build_rows(self.corpus)}
        source = ROOT / 'evaluation/data'
        published = dataset.read_jsonl(source / 'dev.jsonl') + dataset.read_jsonl(source / 'test.jsonl')
        self.assertEqual(expected, {r['question_id']: r for r in published})

    def test_frozen_hashes_ignore_json_key_order_and_crlf(self):
        source = ROOT / 'evaluation/data'
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ('dev.jsonl', 'test.jsonl', 'seed.jsonl', 'split-manifest.json'):
                directory.joinpath(name).write_bytes(source.joinpath(name).read_bytes())
            records = dataset.read_jsonl(directory / 'test.jsonl')
            rendered = ''.join(json.dumps(dict(reversed(list(r.items()))), ensure_ascii=False) + '\r\n'
                               for r in records)
            directory.joinpath('test.jsonl').write_bytes(rendered.encode('utf-8'))
            dataset.verify_frozen(directory, CORPUS_PATH)

    def test_release_dataset_and_freeze_are_reproducible_and_immutable(self):
        source = ROOT / 'evaluation/data'
        self.assertTrue(source.joinpath('test.jsonl').exists(), 'M2 data is missing')
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ('dev.jsonl', 'test.jsonl', 'seed.jsonl'):
                directory.joinpath(name).write_bytes(source.joinpath(name).read_bytes())
            manifest = dataset.freeze_dataset(directory, CORPUS_PATH)
            original = directory.joinpath('split-manifest.json').read_bytes()
            self.assertEqual(manifest['counts']['total'], 72)
            self.assertEqual(manifest['counts']['seed'], 12)
            dataset.freeze_dataset(directory, CORPUS_PATH)
            self.assertEqual(directory.joinpath('split-manifest.json').read_bytes(), original)
            dataset.verify_frozen(directory, CORPUS_PATH)
            rows = dataset.read_jsonl(directory / 'test.jsonl')
            rows[0]['expected_answer'] += ' sửa'
            write_rows(directory / 'test.jsonl', rows)
            with self.assertRaisesRegex(ValueError, 'frozen'):
                dataset.freeze_dataset(directory, CORPUS_PATH)
            with self.assertRaisesRegex(ValueError, 'frozen'):
                dataset.verify_frozen(directory, CORPUS_PATH)
            self.assertEqual(directory.joinpath('split-manifest.json').read_bytes(), original)

    def test_freeze_rejects_under_minimum_without_writing_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name, rows in [('dev.jsonl', self.dev), ('test.jsonl', self.test), ('seed.jsonl', self.dev)]:
                write_rows(directory / name, rows)
            with self.assertRaises(ValueError):
                dataset.freeze_dataset(directory, CORPUS_PATH)
            self.assertFalse(directory.joinpath('split-manifest.json').exists())

    def test_committed_freeze_and_cli(self):
        result = subprocess.run([sys.executable, '-m', 'evaluation.dataset', 'validate'],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('72', result.stdout)


if __name__ == '__main__':
    unittest.main()
