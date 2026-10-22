"""Offline synthetic identity, membership and curator-preservation checks."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import classify_cci_involvement as c
import publications as p


@pytest.fixture
def roster():
    return {'schema_version': 1, 'staff': [
        {'id': 'synthetic', 'name': 'Amélie Test-Person', 'name_variants': ['Amelie Example'],
         'membership_periods': [{'start_year': 2020, 'end_year': 2024}]}]}


def record(author='Amélie Test-Person', year=2023):
    return {'id': 'test', 'doi': '10.1234/test', 'metadata': {'title': 'Synthetic paper',
            'authors': [author], 'year': year}, 'overrides': {}, 'services': [],
            'technologies': [], 'tagging_status': 'pending', 'reporting_years': [2019]}


@pytest.mark.parametrize('name', ['Amélie Test-Person', 'Amelie Test‐Person', 'AMELIE TEST PERSON', 'Amelie Example'])
def test_full_names_and_verified_aliases(roster, name):
    result = c.identify(record(name), c.staff_index(roster))
    assert result['cci_involvement'] == 'scientific-collaboration'
    assert result['matches'][0]['publication_year'] == 2023


@pytest.mark.parametrize('name', ['A. Test-Person', 'Amelie Other', 'Different Person', 'Test-Person'])
def test_no_fuzzy_or_initial_only_assignment(roster, name):
    result = c.identify(record(name), c.staff_index(roster))
    assert result['cci_involvement'] == 'service-provision'
    assert result['basis'] == 'default_no_confirmed_roster_match'


@pytest.mark.parametrize('year,expected', [(2019, False), (2020, True), (2024, True), (2025, False)])
def test_inclusive_membership_uses_publication_not_reporting_year(roster, year, expected):
    result = c.identify(record(year=year), c.staff_index(roster))
    assert bool(result['matches']) == expected


def test_effective_year_override_and_ongoing_membership(roster):
    roster['staff'][0]['membership_periods'][0]['end_year'] = None
    r = record(year=2019)
    r['overrides']['year'] = 2026
    assert c.identify(r, c.staff_index(roster))['matches'][0]['publication_year'] == 2026


def test_duplicate_full_names_require_review(roster):
    duplicate = copy.deepcopy(roster['staff'][0])
    duplicate['id'] = 'other-person'
    roster['staff'].append(duplicate)
    result = c.identify(record(), c.staff_index(roster))
    assert not result['matches']
    assert result['review_notes'][0]['reason'] == 'name shared by multiple roster entries'


def test_classification_changes_only_involvement_and_preserves_manual_correction(roster):
    r = record()
    r['cci_involvement_override'] = 'service-provision'
    source = {'publications': [r]}
    before = copy.deepcopy(source)
    classified, rows = c.classify(source, roster)
    assert source == before
    updated = classified['publications'][0]
    assert updated.pop('cci_involvement') == 'service-provision'
    assert updated == r
    assert rows[0]['basis'] == 'curator_override'
    assert rows[0]['suggested_cci_involvement'] == 'scientific-collaboration'
