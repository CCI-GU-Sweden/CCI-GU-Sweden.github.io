"""Guard the year-scoped application of curated technology suggestions."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import apply_technology_tags as t
import publications as p


@pytest.fixture
def registry():
    citation = {'file': 'synthetic.md', 'line': 1, 'title': 'Synthetic study',
                'authors_text': 'Synthetic Author', 'journal': 'Synthetic Journal',
                'year': 2026, 'doi': '10.1234/synthetic', 'original_doi': '10.1234/synthetic',
                'doi_error': None, 'doi_warning': None}
    registry = p.import_citations([citation])
    record = registry['publications'][0]
    record['cci_involvement'] = 'service-provision'
    other = copy.deepcopy(record)
    other.update(id='older', doi='10.1234/older')
    other['metadata']['year'] = 2025
    registry['publications'].append(other)
    return registry


@pytest.fixture
def vocabulary():
    return {'technologies': [{'id': 'light-microscopy', 'label': 'Light Microscopy'},
                              {'id': 'image-analysis', 'label': 'Image Analysis'}], 'services': []}


def plan(registry):
    record = registry['publications'][0]
    return {'schema_version': 1, 'year': 2026, 'publications': [
        {'id': record['id'], 'doi': record['doi'], 'technologies': ['light-microscopy', 'image-analysis']}]}


def test_multi_tags_preserve_other_years_and_all_other_record_fields(registry, vocabulary):
    original = copy.deepcopy(registry)
    result = t.apply_assignments(registry, vocabulary, plan(registry), 2026)
    assert registry == original
    assert result['publications'][0]['technologies'] == ['light-microscopy', 'image-analysis']
    result['publications'][0]['technologies'] = []
    assert result == original


@pytest.mark.parametrize('change', ['wrong_year', 'wrong_doi', 'unknown_tag', 'duplicate_tag', 'duplicate_record'])
def test_invalid_assignments_do_not_partially_mutate_registry(registry, vocabulary, change):
    assignments = plan(registry)
    row = assignments['publications'][0]
    if change == 'wrong_year': assignments['year'] = 2025
    if change == 'wrong_doi': row['doi'] = '10.1234/wrong'
    if change == 'unknown_tag': row['technologies'] = ['invented']
    if change == 'duplicate_tag': row['technologies'] = ['image-analysis', 'image-analysis']
    if change == 'duplicate_record': assignments['publications'].append(copy.deepcopy(row))
    original = copy.deepcopy(registry)
    with pytest.raises(ValueError): t.apply_assignments(registry, vocabulary, assignments, 2026)
    assert registry == original


def test_prior_labels_are_not_silently_replaced(registry, vocabulary):
    registry['publications'][0]['technologies'] = ['image-analysis']
    with pytest.raises(ValueError, match='Existing labels differ'):
        t.apply_assignments(registry, vocabulary, plan(registry), 2026)


def test_record_from_another_year_is_rejected(registry, vocabulary):
    assignments = plan(registry)
    assignments['publications'].append({'id': 'older', 'doi': '10.1234/older', 'technologies': ['image-analysis']})
    with pytest.raises(ValueError, match='year/DOI mismatch'):
        t.apply_assignments(registry, vocabulary, assignments, 2026)
