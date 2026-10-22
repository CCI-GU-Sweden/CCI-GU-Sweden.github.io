"""Offline checks for full-text collection integrity and resumability."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publications_fulltext as p


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'HERE', tmp_path)
    return tmp_path


def entry():
    return {'id': 'cci-test', 'doi': '10.1234/test', 'title': 'Test paper',
            'source_url': 'https://example.org/article', 'extraction': 'fixture',
            'coverage': 'full_article_body'}


def test_refresh_preserves_better_text_and_records_failed_attempt(store):
    old = entry()
    old.update(p.save(old, 'Detailed microscopy sample preparation and image analysis. ' * 10))
    original = (store / old['file']).read_bytes()
    new = dict(entry(), coverage='unavailable', attempts=[{'route': 'publisher_html', 'error': '403'}])
    kept = p.preserve_best(old, new)
    assert kept['file'] == old['file']
    assert kept['coverage'] == 'full_article_body'
    assert kept['last_check']['attempts'] == new['attempts']
    assert (store / old['file']).read_bytes() == original


def test_content_changes_do_not_overwrite_old_files(store):
    e = entry()
    old = p.save(e, 'Original detailed methods for microscopy and image analysis. ' * 10)
    new = p.save(e, 'Updated detailed methods for microscopy and image analysis. ' * 10)
    assert old['file'] != new['file']
    assert (store / old['file']).exists()
    assert (store / new['file']).exists()


def test_checksum_detects_corrupted_or_missing_text(store):
    e = entry()
    e.update(p.save(e, 'Detailed microscopy sample preparation and image analysis. ' * 10))
    assert p.valid_saved(e)
    (store / e['file']).write_text('truncated')
    assert not p.valid_saved(e)
    assert not p.valid_saved(dict(e, file='../outside.md'))


def test_upgrading_abstract_keeps_history(store):
    old = dict(entry(), coverage='abstract_only', attempts=[{'route': 'saved_doi_abstract', 'result': 'success'}])
    old.update(p.save(old, 'Abstract text describing microscopy and analysis. ' * 10))
    new = entry()
    new.update(p.save(new, 'Full paper with preparation acquisition and analysis. ' * 100))
    kept = p.preserve_best(old, new)
    assert kept['coverage'] == 'full_article_body'
    assert kept['previous_checks'][0]['file'] == old['file']


def test_jats_preserves_methods_table_caption_and_removes_processing_instructions():
    text = p.convert_jats('''<article><body><sec><title>Methods</title>
      <p>Fixed cells were imaged.</p><table-wrap><caption><p>Sample settings</p></caption>
      <table><tr><th>Method</th></tr><tr><td>Confocal</td></tr></table></table-wrap>
      <?cloudpmc private-artifact?><fig><caption><p>Cell image caption</p></caption></fig>
      </sec></body></article>''')
    assert 'Methods' in text and 'Fixed cells' in text
    assert 'Confocal' in text and 'Cell image caption' in text
    assert 'private-artifact' not in text


def test_resume_skips_saved_results_without_network(store, monkeypatch):
    root = store / 'repo'
    private = root / 'private_data' / 'fulltext'
    private.mkdir(parents=True)
    (root / '_publications').mkdir()
    r = {'id': 'cci-test', 'doi': '10.1234/test', 'metadata': {'title': 'Test paper'}}
    (root / '_publications/registry.yml').write_text(p.yaml.safe_dump({'publications': [r]}))
    monkeypatch.setattr(p, 'ROOT', root)
    monkeypatch.setattr(p, 'HERE', private)
    e = entry()
    e.update(p.save(e, 'Detailed microscopy sample preparation and image analysis. ' * 10))
    (private / 'manifest.json').write_text(json.dumps({'articles': [e]}))
    monkeypatch.setattr(p, 'collect', lambda record: pytest.fail('Resume must not collect again'))
    p.main(['--output', str(private)])
    assert len(json.loads((private / 'manifest.json').read_text())['articles']) == 1
    assert (private / 'retrieval-summary.csv').exists()


def test_public_output_is_rejected(store, monkeypatch):
    monkeypatch.setattr(p, 'ROOT', store)
    with pytest.raises(SystemExit):
        p.main(['--output', str(store / 'assets')])


def test_request_retries_transient_failure_only(monkeypatch):
    class Response:
        headers = {}
        status_code = 503
        def close(self): pass
        def raise_for_status(self): pass
        def iter_content(self, size): return [b'full text']
    first, second = Response(), Response()
    second.status_code = 200
    responses = iter([first, second])
    monkeypatch.setattr(p.SESSION, 'get', lambda *a, **kw: next(responses))
    monkeypatch.setattr(p.time, 'sleep', lambda seconds: None)
    assert p.get('https://example.org')._content == b'full text'


def test_blocked_publisher_uses_doi_matched_repository_abstract(store, monkeypatch):
    record = {'id': 'cci-test', 'doi': '10.1234/test', 'metadata': {'title': 'Test paper'}}
    class Response:
        def json(self):
            return {'resultList': {'result': [{'doi': '10.1234/test', 'title': 'Test paper',
                    'source': 'MED', 'id': '123', 'isOpenAccess': 'N',
                    'abstractText': 'Cells were imaged using confocal microscopy and quantified with image analysis. ' * 3}]}}
    def get(url, **kwargs):
        if 'europepmc' in url:
            return Response()
        raise p.requests.HTTPError('403 blocked')
    monkeypatch.setattr(p, 'get', get)
    monkeypatch.setattr(p, 'ROOT', store)
    result = p.collect(record)
    assert result['coverage'] == 'abstract_only'
    assert result['attempts'][-1]['route'] == 'europe_pmc_abstract'
    assert 'confocal microscopy' in (store / result['file']).read_text()


def test_subscription_preview_is_abstract_only_even_with_many_references(store, monkeypatch):
    record = {'id': 'cci-test', 'doi': '10.1234/test', 'metadata': {'title': 'Test paper'}}
    class Response:
        url = 'https://link.springer.com/test'
        text = ('<meta name="citation_doi" content="10.1234/test"><div class="c-article-body">'
                '<section><h2 id="Abs1">Abstract</h2><p>' + 'Microscopy was used for cell imaging. ' * 10 +
                '</p></section><p>This is a preview of subscription content</p>' +
                '<section><h2>References</h2>' + 'Other scientific references. ' * 1000 + '</section></div>')
        def json(self): return {'resultList': {'result': []}}
    monkeypatch.setattr(p, 'get', lambda *a, **kw: Response())
    result = p.collect(record)
    assert result['coverage'] == 'abstract_only'
    assert 'Other scientific references' not in (store / result['file']).read_text()


def test_xml_doi_mismatch_never_becomes_full_text(store, monkeypatch):
    record = {'id': 'cci-test', 'doi': '10.1234/test', 'metadata': {'title': 'Test paper'}}
    class Response:
        text = '<article><front><article-id pub-id-type="doi">10.1234/wrong</article-id></front><body><p>Wrong paper</p></body></article>'
        def json(self):
            return {'resultList': {'result': [{'doi': '10.1234/test', 'isOpenAccess': 'Y', 'pmcid': 'PMC1'}]}}
    def get(url, **kw):
        if 'europepmc' in url: return Response()
        raise p.requests.HTTPError('blocked')
    monkeypatch.setattr(p, 'get', get)
    monkeypatch.setattr(p, 'ROOT', store)
    result = p.collect(record)
    assert result['coverage'] == 'unavailable'
    assert any('XML article DOI' in a.get('error', '') for a in result['attempts'])


def test_cached_abstract_awaiting_identity_review_is_not_used(store, monkeypatch):
    record = {'id': 'cci-test', 'doi': '10.1234/test', 'metadata': {'title': 'Test paper'}}
    private = store / 'private_data'
    private.mkdir()
    (private / 'publication-abstracts.json').write_text(json.dumps({'abstracts': [
        {'id': 'cci-test', 'doi': '10.1234/test', 'status': 'identity_review',
         'abstract': {'text': 'Wrong paper microscopy methods. ' * 20}}]}))
    monkeypatch.setattr(p, 'ROOT', store)
    def blocked(*args, **kwargs):
        raise p.requests.HTTPError('blocked')
    monkeypatch.setattr(p, 'get', blocked)
    result = p.collect(record)
    assert result['coverage'] == 'unavailable'
    assert 'file' not in result
