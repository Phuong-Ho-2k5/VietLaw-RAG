"""Validate M2 gold against M1 and seal dev/test without modifying questions.

Only the standard library is required. Frozen releases are content addressed;
to revise a dataset, use a new directory rather than replacing its manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / 'data/manifests/m1/labor-corpus-v1.json'
DEFAULT_DATA = ROOT / 'evaluation/data'
TOPICS = {'contract', 'probation', 'wages', 'hours_rest', 'termination', 'outside_scope'}
CATEGORIES = {'direct', 'scenario', 'multi_unit', 'insufficient_evidence', 'out_of_scope', 'temporal'}
FIELDS = {'schema_version', 'question_id', 'question', 'split', 'family_id', 'category',
          'scope', 'topic', 'as_of_date', 'expected_behavior', 'expected_answer', 'gold',
          'snapshot_id', 'reviewer', 'reviewed_at', 'review_note', 'evidence'}
GOLD_FIELDS = {'document_number', 'article', 'clause', 'point', 'chunk_id'}


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _date(value, field):
    _require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value),
             f'invalid {field}')
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f'invalid {field}: {value}') from error


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f'{path}:{number}: invalid JSON') from error
            _require(isinstance(row, dict), f'{path}:{number}: expected object')
            rows.append(row)
    return rows


def _check_corpus(corpus):
    _require(isinstance(corpus, dict) and corpus.get('active') is True, 'corpus is inactive')
    payload = {k: v for k, v in corpus.items() if k != 'manifest_hash'}
    digest = canonical_hash(payload)
    _require(digest == corpus.get('manifest_hash'), 'corpus manifest hash mismatch')
    chunks = {}
    for chunk in corpus['chunks']:
        _require(chunk['review_status'] == 'approved', 'corpus chunk is not approved')
        _require(chunk['chunk_id'] not in chunks, 'corpus has duplicate chunk IDs')
        _require(hashlib.sha256(chunk['text'].encode('utf-8')).hexdigest() == chunk['content_hash'],
                 'corpus chunk content hash mismatch')
        chunks[chunk['chunk_id']] = chunk
    _require(bool(chunks), 'corpus has no chunks')
    return chunks


def _check_row(row, split, corpus, chunks):
    _require(isinstance(row, dict) and set(row) == FIELDS, 'invalid question schema fields')
    qid = row['question_id']
    _require(type(row['schema_version']) is int and row['schema_version'] == 1, 'invalid schema_version')
    for field in ('question_id', 'question', 'family_id', 'expected_answer', 'reviewer', 'review_note'):
        _require(_text(row[field]), f'{qid}: missing {field}')
    _require(row['split'] == split, f'{qid}: incorrect split')
    _require(isinstance(row['category'], str) and row['category'] in CATEGORIES, f'{qid}: invalid category')
    _require(isinstance(row['topic'], str) and row['topic'] in TOPICS, f'{qid}: invalid topic')
    _require(row['scope'] in ('in_scope', 'out_of_scope'), f'{qid}: invalid scope')
    _date(row['reviewed_at'], 'reviewed_at')
    if row['as_of_date'] is not None:
        _date(row['as_of_date'], 'as_of_date')
    _require(row['snapshot_id'] == corpus['manifest_hash'], f'{qid}: snapshot mismatch')
    _require(isinstance(row['gold'], list) and isinstance(row['evidence'], list) and row['evidence'],
             f'{qid}: gold/evidence must be lists with evidence')

    answerable = row['category'] in ('direct', 'scenario', 'multi_unit')
    outside = row['category'] == 'out_of_scope'
    _require(row['scope'] == ('out_of_scope' if outside else 'in_scope'), f'{qid}: scope/category mismatch')
    _require((row['topic'] == 'outside_scope') == outside, f'{qid}: topic/scope mismatch')
    _require(row['expected_behavior'] == ('answer' if answerable else 'abstain'),
             f'{qid}: expected behavior inconsistent with category')
    if not answerable:
        _require(not row['gold'], f'{qid}: abstain requires empty gold')
        _require(len(row['evidence']) == 1, f'{qid}: abstain requires one scope evidence')
        evidence = row['evidence'][0]
        _require(isinstance(evidence, dict) and set(evidence) == {'kind', 'snapshot_id', 'reason'}
                 and evidence['kind'] == 'corpus_scope'
                 and evidence['snapshot_id'] == corpus['manifest_hash'] and _text(evidence['reason']),
                 f'{qid}: invalid abstain scope evidence')
        if row['category'] == 'temporal':
            _require(row['as_of_date'] not in corpus['temporal_scope']['as_of_dates'],
                     f'{qid}: temporal abstain must use unspecified/unverified date')
        else:
            _require(row['as_of_date'] in corpus['temporal_scope']['as_of_dates'],
                     f'{qid}: unsupported date requires temporal category')
        return set()

    _require(row['gold'], f'{qid}: answer needs gold')
    if row['category'] == 'multi_unit':
        _require(len(row['gold']) >= 2, f'{qid}: multi_unit needs at least two gold units')
    _require(row['as_of_date'] in corpus['temporal_scope']['as_of_dates'], f'{qid}: unverified answer date')
    articles, gold_ids = set(), set()
    for gold in row['gold']:
        _require(isinstance(gold, dict) and set(gold) == GOLD_FIELDS, f'{qid}: invalid gold schema')
        _require(_text(gold['chunk_id']) and gold['chunk_id'] in chunks, f'{qid}: unknown gold chunk')
        chunk = chunks[gold['chunk_id']]
        _require(gold['chunk_id'] not in gold_ids, f'{qid}: duplicate gold')
        gold_ids.add(gold['chunk_id'])
        for field, chunk_field in [('document_number', 'document_number'), ('article', 'article_label'),
                                   ('clause', 'clause_label'), ('point', 'point_label')]:
            _require(gold[field] == chunk[chunk_field], f'{qid}: gold {field} mismatch')
        _require(row['topic'] in chunk['topic_tags'], f'{qid}: gold topic mismatch')
        _require(row['as_of_date'] == chunk['as_of_date'], f'{qid}: chunk date mismatch')
        articles.add((gold['document_number'], gold['article']))
    evidence_ids = set()
    for evidence in row['evidence']:
        _require(isinstance(evidence, dict) and set(evidence) == {'kind', 'chunk_id', 'url', 'pdf_page'},
                 f'{qid}: invalid evidence schema')
        chunk_id = evidence['chunk_id']
        _require(_text(chunk_id) and chunk_id in gold_ids and chunk_id not in evidence_ids,
                 f'{qid}: evidence must map exactly to gold')
        source = chunks[chunk_id]['source_evidence']
        _require(evidence['kind'] == 'legal_source' and evidence['url'] == source['url']
                 and type(evidence['pdf_page']) is int and evidence['pdf_page'] == source['pdf_page'],
                 f'{qid}: evidence source/page mismatch')
        evidence_ids.add(chunk_id)
    _require(evidence_ids == gold_ids, f'{qid}: missing gold evidence')
    return articles


def validate_dataset(dev: list[dict], test: list[dict], seed: list[dict], corpus: dict,
                     *, min_questions: int = 60, seed_count: int = 12) -> dict:
    chunks = _check_corpus(corpus)
    _require(dev and test and len(dev) + len(test) >= min_questions, 'insufficient dev/test questions')
    seen_ids, seen_questions = set(), set()
    families, articles = {}, {}
    for split, rows in [('dev', dev), ('test', test)]:
        families[split], articles[split] = set(), set()
        for row in rows:
            refs = _check_row(row, split, corpus, chunks)
            _require(row['question_id'] not in seen_ids, 'duplicate question_id')
            seen_ids.add(row['question_id'])
            normalized = ' '.join(unicodedata.normalize('NFC', row['question']).casefold().split())
            _require(normalized not in seen_questions, 'duplicate question text')
            seen_questions.add(normalized)
            families[split].add(row['family_id'])
            articles[split].update(refs)
    _require(not articles['dev'] & articles['test'], 'article leakage across dev/test')
    _require(not families['dev'] & families['test'], 'family leakage across dev/test')
    _require(len(seed) == seed_count, 'incorrect seed count')
    dev_by_id = {row['question_id']: row for row in dev}
    _require(all(isinstance(row, dict) and _text(row.get('question_id'))
                 and row['question_id'] in dev_by_id
                 and row == dev_by_id[row['question_id']] for row in seed), 'seed must be exact dev subset')
    _require(len({row['question_id'] for row in seed}) == len(seed), 'duplicate seed question')
    if min_questions >= 60:
        rows = dev + test
        _require({row['topic'] for row in rows} >= TOPICS, 'missing topic coverage')
        _require({row['category'] for row in rows} >= CATEGORIES, 'missing category coverage')
        for split_rows in (dev, test):
            _require({row['expected_behavior'] for row in split_rows} == {'answer', 'abstain'},
                     'each split needs answer and abstain cases')
    return {
        'counts': {'dev': len(dev), 'test': len(test), 'total': len(dev) + len(test), 'seed': len(seed)},
        'categories': {s: dict(sorted(Counter(r['category'] for r in rows).items()))
                       for s, rows in [('dev', dev), ('test', test)]},
        'topics': {s: dict(sorted(Counter(r['topic'] for r in rows).items()))
                   for s, rows in [('dev', dev), ('test', test)]},
        'articles': {s: [list(ref) for ref in sorted(articles[s])] for s in ('dev', 'test')},
        'families': {s: sorted(families[s]) for s in ('dev', 'test')},
    }


def _manifest(directory: Path, corpus_path: Path) -> dict:
    corpus = json.loads(corpus_path.read_text(encoding='utf-8'))
    splits = {name: read_jsonl(directory / f'{name}.jsonl') for name in ('dev', 'test', 'seed')}
    report = validate_dataset(splits['dev'], splits['test'], splits['seed'], corpus)
    manifest = {
        'schema_version': 1, 'release_id': 'm2-v1', 'frozen': True,
        'snapshot_id': corpus['manifest_hash'], 'corpus_sha256': canonical_hash(corpus),
        'as_of_dates': corpus['temporal_scope']['as_of_dates'],
        'split_policy': 'disjoint_articles_and_semantic_families; seed_is_dev_subset',
        'test_policy': 'held_out; never use test to select parameters',
        'files': {f'{name}.jsonl': canonical_hash(rows) for name, rows in splits.items()},
        'reviewers': sorted({r['reviewer'] for r in splits['dev'] + splits['test']}),
        'reviewed_at': sorted({r['reviewed_at'] for r in splits['dev'] + splits['test']}),
        **report,
    }
    manifest['manifest_hash'] = canonical_hash(manifest)
    return manifest


def freeze_dataset(directory: Path, corpus_path: Path) -> dict:
    manifest = _manifest(directory, corpus_path)
    target = directory / 'split-manifest.json'
    if target.exists():
        _require(json.loads(target.read_text(encoding='utf-8')) == manifest,
                 'frozen release differs; create a new release directory')
        return manifest
    # Exclusive creation avoids replacing a freeze created by another process.
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    return manifest


def verify_frozen(directory: Path, corpus_path: Path) -> dict:
    target = directory / 'split-manifest.json'
    _require(target.exists(), 'missing frozen split manifest')
    expected = json.loads(target.read_text(encoding='utf-8'))
    manifest = _manifest(directory, corpus_path)
    _require(expected == manifest, 'frozen release hash/content mismatch')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('validate', 'freeze'))
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--corpus', type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args(argv)
    try:
        result = (freeze_dataset if args.command == 'freeze' else verify_frozen)(args.data, args.corpus)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f'M2 validation failed: {ascii(str(error))}\n')
    print(json.dumps({'valid': True, 'snapshot_id': result['snapshot_id'],
                      'manifest_hash': result['manifest_hash'], 'counts': result['counts']}))


if __name__ == '__main__':
    main()
