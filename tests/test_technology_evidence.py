"""Synthetic checks prevent stale or fabricated citations entering a review batch."""
import copy
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import validate_technology_evidence as v


@pytest.fixture
def evidence(tmp_path):
    text = '# Synthetic paper\n\nCells were imaged using confocal microscopy.\n'
    (tmp_path / 'paper.md').write_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    registry = {'publications': [{'id': 'test', 'doi': '10.1234/synthetic', 'metadata': {'year': 2023}, 'overrides': {}}]}
    vocabulary = {'technologies': [{'id': 'light-microscopy'}]}
    manifest = {'articles': [{'id': 'test', 'coverage': 'full_article_body', 'file': 'paper.md', 'sha256': digest}]}
    findings = [{'id': 'test', 'doi': '10.1234/synthetic', 'effective_year': 2023,
                 'coverage': 'full_article_body', 'review_status': 'proposed',
                 'input_file': 'paper.md', 'input_sha256': digest,
                 'proposed_technology_ids': ['light-microscopy'], 'discussed_technology_ids': [],
                 'findings': {'microscopy_acquisition': [{'proposed_tags': ['light-microscopy'], 'evidence': {'file': 'paper.md', 'line': 3,
                                                'excerpt': 'confocal microscopy'}}]}}]
    return findings, registry, vocabulary, manifest, tmp_path


def test_complete_verified_batch(evidence):
    result = v.validate_findings(*evidence, 2023)
    assert result == {'year': 2023, 'records': 1, 'verified_references': 1}


@pytest.mark.parametrize('change', ['hash', 'line', 'excerpt', 'tag', 'missing', 'duplicate', 'year', 'no_evidence'])
def test_invalid_evidence_is_rejected(evidence, change):
    findings, registry, vocabulary, manifest, root = copy.deepcopy(evidence)
    if change == 'hash': findings[0]['input_sha256'] = 'wrong'
    if change == 'line': findings[0]['findings']['microscopy_acquisition'][0]['evidence']['line'] = 1
    if change == 'excerpt': findings[0]['findings']['microscopy_acquisition'][0]['evidence']['excerpt'] = 'fabricated claim'
    if change == 'tag': findings[0]['proposed_technology_ids'] = ['invented']
    if change == 'missing': findings.clear()
    if change == 'duplicate': findings.append(copy.deepcopy(findings[0]))
    if change == 'year': findings[0]['effective_year'] = 2024
    if change == 'no_evidence': findings[0]['findings'] = {}
    with pytest.raises(ValueError):
        v.validate_findings(findings, registry, vocabulary, manifest, root, 2023)


def test_unavailable_text_is_not_positive_evidence(evidence):
    findings, registry, vocabulary, manifest, root = evidence
    manifest['articles'][0] = {'id': 'test', 'coverage': 'unavailable'}
    findings[0].update(coverage='unavailable', input_file=None, input_sha256=None, findings={})
    with pytest.raises(ValueError, match='Unavailable text'):
        v.validate_findings(findings, registry, vocabulary, manifest, root, 2023)
    findings[0]['proposed_technology_ids'] = []
    assert v.validate_findings(findings, registry, vocabulary, manifest, root, 2023)['verified_references'] == 0


def test_labels_need_specific_supporting_findings(evidence):
    findings, *rest = evidence
    findings[0]['findings']['microscopy_acquisition'][0]['proposed_tags'] = []
    with pytest.raises(ValueError, match='supporting finding'):
        v.validate_findings(findings, *rest, 2023)


def test_unknown_finding_level_tag_is_rejected(evidence):
    findings, *rest = evidence
    findings[0]['findings']['microscopy_acquisition'][0]['proposed_tags'] = ['invented']
    with pytest.raises(ValueError, match='finding-level'):
        v.validate_findings(findings, *rest, 2023)
