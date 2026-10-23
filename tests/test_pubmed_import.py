"""Synthetic PubMed responses: no network and no real publication fixtures."""
import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('pubmed_publications', Path(__file__).parents[1] / 'scripts/publications.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


@pytest.fixture
def xml():
    return '''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID><Article>
      <Journal><Title>Synthetic Journal</Title><JournalIssue><PubDate><Year>2015</Year></PubDate></JournalIssue></Journal>
      <ArticleTitle>A synthetic <i>microscopy</i> paper</ArticleTitle>
      <AuthorList><Author><LastName>Åström</LastName><ForeName>Anna</ForeName></Author>
      <Author><CollectiveName>Synthetic Consortium</CollectiveName></Author></AuthorList>
      <Abstract><AbstractText Label="RESULTS">Synthetic <b>abstract</b> text.</AbstractText></Abstract>
      </Article></MedlineCitation><PubmedData><ArticleIdList>
      <ArticleId IdType="pubmed">12345678</ArticleId><ArticleId IdType="pmc">PMC777777</ArticleId>
      </ArticleIdList><ReferenceList><Reference><ArticleIdList>
      <ArticleId IdType="pubmed">99999999</ArticleId><ArticleId IdType="doi">10.1234/reference</ArticleId>
      </ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>'''


@pytest.fixture
def citation(tmp_path):
    path = tmp_path / 'incoming.md'
    path.write_text('## 2015\n| Article | DOI |\n| --- | --- |\n| Synthetic citation | PMID:12345678 |\n')
    return p.read_tables([path])[0]


@pytest.fixture
def vocabulary():
    return {'technologies': [{'id': 'light-microscopy'}], 'services': []}


class PubMedClient:
    def __init__(self, result=None, error=False):
        self.result, self.error, self.calls = result, error, []

    def lookup_pubmed(self, pmid):
        self.calls.append(pmid)
        if self.error:
            raise LookupError('Synthetic outage')
        return copy.deepcopy(self.result)

    def lookup(self, doi):
        raise AssertionError('DOI endpoint used for PMID input')


@pytest.mark.parametrize('value', ['PMID:12345678', 'pmid: 12345678',
    'https://pubmed.ncbi.nlm.nih.gov/12345678/', '[PubMed](https://pubmed.ncbi.nlm.nih.gov/12345678/)'])
def test_explicit_pmid_identifiers(value):
    assert p.parse_identifier(value) == (None, '12345678')


@pytest.mark.parametrize('value', ['12345678', 'PMID:0', 'PMID:abc', 'PMID:12/34',
                                      'https://evil.org/12345678'])
def test_invalid_or_ambiguous_identifiers(value):
    with pytest.raises(ValueError):
        p.parse_identifier(value)


def test_identifier_header_and_confirmed_absence(tmp_path):
    path = tmp_path / 'table.md'
    path.write_text('| Identifier | DOI status |\n| --- | --- |\n| PMID:12345678 | confirmed-unavailable |\n')
    row = p.read_tables([path])[0]
    assert row['pmid'] == '12345678' and row['doi'] is None
    assert row['doi_status'] == 'confirmed-unavailable'


def test_pubmed_normalization_excludes_reference_identifiers(xml):
    result = p.normalize_pubmed(xml, '12345678')
    assert result['doi'] is None and result['pmid'] == '12345678'
    assert result['pmcid'] == 'PMC777777'
    assert result['metadata']['title'] == 'A synthetic microscopy paper'
    assert result['metadata']['authors'] == ['Anna Åström', 'Synthetic Consortium']
    assert result['metadata']['year'] == 2015
    assert result['abstract']['text'] == 'RESULTS: Synthetic abstract text.'
    assert result['abstract']['public_license_url'] is None


def test_pubmed_wrong_record_and_conflicting_dois_are_rejected(xml):
    with pytest.raises(ValueError, match='no article'):
        p.normalize_pubmed(xml, '87654321')
    changed = xml.replace('</ArticleIdList><ReferenceList>',
        '<ArticleId IdType="doi">10.1234/a</ArticleId><ArticleId IdType="doi">10.1234/b</ArticleId></ArticleIdList><ReferenceList>')
    # Duplicate DOI elements are not silently allowed to overwrite each other.
    with pytest.raises(ValueError, match='conflicting'):
        p.normalize_pubmed(changed, '12345678')


def test_pmid_import_deduplicates_and_preserves_curation(xml, citation, vocabulary):
    client = PubMedClient(p.normalize_pubmed(xml, '12345678'))
    registry, updates = p.import_table_records([citation, citation], {'schema_version': 1, 'publications': []}, client)
    assert client.calls == ['12345678']
    record = registry['publications'][0]
    assert record['doi_status'] == 'not-listed'
    record.update(technologies=['light-microscopy'], cci_involvement='scientific-collaboration',
                  approved=False, notes='Curator note', doi_status='confirmed-unavailable')
    record['overrides'] = {'year': 2014}
    original = copy.deepcopy(registry)
    repeated, changes = p.import_table_records([{**citation, 'file': 'another.md', 'line': 90}], registry, client)
    assert len(repeated['publications']) == 1
    after = repeated['publications'][0]
    for key in ['id', 'doi', 'doi_status', 'technologies', 'cci_involvement', 'approved', 'notes', 'overrides']:
        assert after[key] == record[key]
    assert changes[0]['status'] == 'unchanged'
    assert registry == original
    p.validate(repeated, vocabulary)


def test_pubmed_doi_alias_merges_existing_doi_record(xml, citation):
    result = p.normalize_pubmed(xml, '12345678')
    result['doi'] = '10.1234/example'
    doi_citation = {**citation, 'file': 'doi.md', 'doi': result['doi']}
    doi_citation.pop('pmid')
    baseline = p.import_citations([doi_citation])
    baseline['publications'][0].update(technologies=['light-microscopy'], notes='Existing curation')
    registry, _ = p.import_table_records([citation], baseline, PubMedClient(result))
    assert len(registry['publications']) == 1
    record = registry['publications'][0]
    assert record['id'] == baseline['publications'][0]['id']
    assert record['pmid'] == '12345678' and record['doi_status'] == 'available'
    assert record['notes'] == 'Existing curation' and record['technologies'] == ['light-microscopy']


def test_later_doi_keeps_pmid_record_id(xml, citation, tmp_path):
    result = p.normalize_pubmed(xml, '12345678')
    registry, _ = p.import_table_records([citation], {'schema_version': 1, 'publications': []}, PubMedClient(result))
    previous_id = registry['publications'][0]['id']
    result['doi'] = '10.1234/discovered'
    assert p.check_updates(registry, PubMedClient(result), tmp_path / 'updates.json')['changed'] == 1
    updated, updates = p.import_table_records([citation], registry, PubMedClient(result))
    assert len(updated['publications']) == 1
    assert updated['publications'][0]['id'] == previous_id
    assert updated['publications'][0]['doi'] == result['doi']
    assert updated['publications'][0]['doi_status'] == 'available'
    assert updates[0]['status'] == 'updated'
    assert updates[0]['identifier_changes']['doi'] == {'before': None, 'after': result['doi']}


def test_conflicting_existing_alias_records_require_explicit_merge(xml, citation):
    result = p.normalize_pubmed(xml, '12345678')
    registry, _ = p.import_table_records([citation], {'schema_version': 1, 'publications': []}, PubMedClient(result))
    doi_citation = {**citation, 'file': 'doi.md', 'doi': '10.1234/discovered'}
    doi_citation.pop('pmid')
    registry = p.import_citations([doi_citation], registry)
    result['doi'] = doi_citation['doi']
    before = copy.deepcopy(registry)
    with pytest.raises(ValueError, match='merge explicitly'):
        p.import_table_records([citation], registry, PubMedClient(result))
    assert registry == before


def test_pubmed_cache_and_failed_refresh_preserve_metadata(tmp_path, monkeypatch, xml):
    result = p.normalize_pubmed(xml, '12345678')
    path = tmp_path / (p.hashlib.sha256(b'pmid:12345678').hexdigest() + '.json')
    p.write_json(path, result)
    offline = p.MetadataClient(tmp_path, offline=True)
    monkeypatch.setattr(p.requests, 'get', lambda *a, **k: (_ for _ in ()).throw(p.requests.ConnectionError('Outage')))
    assert offline.lookup_pubmed('12345678')['cached']
    live = p.MetadataClient(tmp_path, refresh=True)
    assert live.lookup_pubmed('12345678')['refresh_error']
    assert p.read_json(path) == result
    with pytest.raises(LookupError):
        offline.lookup_pubmed('87654321')


def test_pubmed_refresh_export_and_failure(xml, citation, vocabulary, tmp_path):
    result = p.normalize_pubmed(xml, '12345678')
    registry, _ = p.import_table_records([citation], {'schema_version': 1, 'publications': []}, PubMedClient(result))
    public = p.public_catalogue(registry, vocabulary)['publications'][0]
    assert public['pmid'] == '12345678' and public['doi'] is None
    assert 'doi_status' not in public and 'abstract' not in public
    assert p.check_updates(registry, PubMedClient(result), tmp_path / 'updates.json')['unchanged'] == 1
    unchanged = copy.deepcopy(registry)
    p.enrich(registry, PubMedClient(error=True))
    assert registry['publications'][0]['metadata'] == unchanged['publications'][0]['metadata']
    assert registry['publications'][0]['last_lookup_error']


def test_duplicate_pmids_are_invalid(xml, citation, vocabulary):
    registry, _ = p.import_table_records([citation], {'schema_version': 1, 'publications': []}, PubMedClient(p.normalize_pubmed(xml, '12345678')))
    another = copy.deepcopy(registry['publications'][0]); another['id'] = 'different'
    registry['publications'].append(another)
    with pytest.raises(ValueError, match='duplicate PMID'):
        p.validate(registry, vocabulary)


def test_live_pubmed_client_parses_and_caches_response(tmp_path, monkeypatch, xml):
    calls = []

    class Response:
        content = xml.encode()
        def raise_for_status(self):
            pass

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(p.requests, 'get', get)
    monkeypatch.setattr(p.time, 'sleep', lambda seconds: None)
    client = p.MetadataClient(tmp_path, mailto='synthetic@example.org')
    result = client.lookup_pubmed('12345678')
    assert result['doi'] is None
    assert calls[0][1]['params']['db'] == 'pubmed'
    assert calls[0][1]['params']['id'] == '12345678'
    assert calls[0][1]['params']['email'] == 'synthetic@example.org'
    assert client.lookup_pubmed('12345678')['cached']
    assert len(calls) == 1


def test_pmid_cli_failed_lookup_reports_without_saving(tmp_path, monkeypatch, vocabulary):
    source, registry, report, vocab = [tmp_path / name for name in ['in.md', 'registry.yml', 'report.json', 'vocab.yml']]
    source.write_text('| Identifier |\n| --- |\n| PMID:12345678 |\n')
    p.save_registry(vocab, vocabulary)
    monkeypatch.setattr(p, 'MetadataClient', lambda *a, **k: PubMedClient(error=True))
    with pytest.raises(ValueError, match='title is required'):
        p.main(['--registry', str(registry), '--vocabulary', str(vocab), '--report', str(report),
                'import-tables', str(source)])
    assert not registry.exists()
    assert p.read_json(report)['import_updates'][0]['status'] == 'lookup_failed'
    assert 'PMID:12345678' in report.with_suffix('.txt').read_text()


def test_confirmed_absence_can_be_recorded_with_existing_cli(xml, citation, vocabulary, tmp_path):
    registry, _ = p.import_table_records([citation], {'schema_version': 1, 'publications': []},
                                       PubMedClient(p.normalize_pubmed(xml, '12345678')))
    registry_path, vocab_path, report = [tmp_path / name for name in ['registry.yml', 'vocab.yml', 'report.json']]
    p.save_registry(registry_path, registry); p.save_registry(vocab_path, vocabulary)
    rid = registry['publications'][0]['id']
    p.main(['--registry', str(registry_path), '--vocabulary', str(vocab_path), '--report', str(report),
            'edit', rid, '--doi-status', 'confirmed-unavailable'])
    result = p.read_registry(registry_path)['publications'][0]
    assert result['doi'] is None and result['doi_status'] == 'confirmed-unavailable'
    assert result['pmid'] == '12345678' and result['id'] == rid


def test_pubmed_error_does_not_save_contact_email(tmp_path, monkeypatch, xml):
    email = 'private-contact@example.org'
    response = p.requests.Response()
    response.status_code = 403
    response.url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?email=' + email

    def get(*args, **kwargs):
        response.raise_for_status()

    monkeypatch.setattr(p.requests, 'get', get)
    client = p.MetadataClient(tmp_path, refresh=True, mailto=email)
    with pytest.raises(LookupError) as exc:
        client.lookup_pubmed('12345678')
    assert 'HTTP 403' in str(exc.value)
    assert email not in str(exc.value) and 'email=' not in str(exc.value)
    cached = p.normalize_pubmed(xml, '12345678')
    p.write_json(tmp_path / (p.hashlib.sha256(b'pmid:12345678').hexdigest() + '.json'), cached)
    result = client.lookup_pubmed('12345678')
    assert email not in result['refresh_error'] and 'email=' not in result['refresh_error']
    monkeypatch.setattr(client.crossref, 'works', lambda **kwargs: response.raise_for_status())
    with pytest.raises(LookupError) as doi_error:
        client.lookup('10.1234/synthetic')
    assert 'HTTP 403' in str(doi_error.value)
    assert email not in str(doi_error.value) and 'email=' not in str(doi_error.value)
