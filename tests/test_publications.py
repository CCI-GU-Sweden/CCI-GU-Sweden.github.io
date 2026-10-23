"""Synthetic fixtures only: no network access and no real CCI attribution."""

import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("publications", Path(__file__).parents[1] / "scripts/publications.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


@pytest.fixture
def citation():
    return {"file": "synthetic.md", "line": 3, "title": "Synthetic microscopy test paper",
            "authors_text": "Åström A; Doe J", "journal": "Test Journal 1:1",
            "year": 2024, "doi": "10.1234/test", "original_doi": "10.1234/test", "doi_error": None}


@pytest.fixture
def registry(citation):
    return p.import_citations([citation])


@pytest.fixture
def vocabulary():
    return {"technologies": [{"id": "confocal"}, {"id": "light_sheet"}], "services": []}


@pytest.fixture
def metadata():
    return p.normalize_metadata({"DOI": "10.1234/test", "title": ["Synthetic microscopy test paper"],
                                 "author": [{"given": "Anna", "family": "Åström"}, {"literal": "Test Consortium"}],
                                 "container-title": ["Test Journal"], "issued": {"date-parts": [[2024]]},
                                 "type": "journal-article"})


@pytest.mark.parametrize("raw", ["10.1234/TEST", "https://doi.org/10.1234/test", r"https\://doi.org/10.1234/test.",
                                 "[DOI](https://doi.org/10.1234/TEST)", "doi: 10.1234/test"])
def test_normalize_doi(raw):
    assert p.normalize_doi(raw) == "10.1234/test"


def test_parenthesized_doi():
    assert p.normalize_doi("[link](https://doi.org/10.1234/test(abc))") == "10.1234/test(abc)"


@pytest.mark.parametrize("raw", ["not a DOI", "10.1/no", "10.1234/has space", "https://evil.org/test"])
def test_bad_doi(raw):
    with pytest.raises(ValueError):
        p.normalize_doi(raw)


def test_table_formats_and_invalid_doi(tmp_path):
    path = tmp_path / "table.md"
    path.write_text("| Author | Year | Title | Source | DOI |\n| --- | --- | --- | --- | --- |\n"
                    "| Åström A | 2024 | Synthetic test | Test journal | bad-doi |\n"
                    "| 2 | Doe J | 2025 | Other test | Journal | 10.1234/second |\n")
    rows = p.read_tables([path])
    assert len(rows) == 2
    assert rows[0]["doi"] is None
    assert rows[0]["doi_error"]
    assert rows[1]["doi"] == "10.1234/second"


def test_duplicate_merges_provenance_not_citations(registry, citation):
    other = {**citation, "year": 2025, "file": "another.md"}
    result = p.import_citations([other, other], registry)
    assert len(result["publications"]) == 1
    record = result["publications"][0]
    assert record["reporting_years"] == [2024, 2025]
    assert len(record["original_citations"]) == 2
    assert record["approved"] is True


def test_article_doi_table_keeps_citation_and_section_years(tmp_path):
    path = tmp_path / "incoming.md"
    path.write_text("# Publications (2021–2024)\n\n## 2024\n\n| Article | DOI |\n| --- | --- |\n"
                    "| Full citation, not just a title. | [link](https://doi.org/10.1234/TEST) |\n"
                    "\n## 2021\n\n| Article | DOI |\n| --- | --- |\n| Other citation | 10.1234/other |\n")
    rows = p.read_tables([path])
    assert [r["year"] for r in rows] == [2024, 2021]
    assert rows[0]["doi"] == "10.1234/test"
    assert rows[0]["citation_text"] == "Full citation, not just a title."
    assert rows[0]["title"] == rows[0]["authors_text"] == rows[0]["journal"] == ""


def test_doi_only_table_can_use_retrieved_year(tmp_path, metadata, vocabulary):
    path = tmp_path / "incoming.md"
    path.write_text("| DOI |\n| --- |\n| 10.1234/test |\n")
    rows = p.read_tables([path])
    assert rows[0]["year"] is None
    result, updates = p.import_table_records(rows, {"schema_version": 1, "publications": []}, FakeClient(metadata))
    record = result["publications"][0]
    assert record["metadata"] == metadata
    assert record["reporting_years"] == [2024]
    assert record["metadata_check"]["status"] == "review"
    assert updates[0]["status"] == "new"
    p.validate(result, vocabulary)


def test_optional_columns_can_be_reordered_and_year_overrides_heading(tmp_path):
    path = tmp_path / "incoming.md"
    path.write_text("## 2021\n| DOI | Title | Year |\n| --- | --- | --- |\n"
                    "| 10.1234/test | Actual title | 2024 |\n")
    row = p.read_tables([path])[0]
    assert row["title"] == "Actual title"
    assert row["year"] == 2024
    assert row["authors_text"] == row["journal"] == ""


@pytest.mark.parametrize("cell", ["", "n/a", "bad-doi"])
def test_doi_only_table_rejects_missing_identity(tmp_path, cell):
    path = tmp_path / "incoming.md"
    path.write_text(f"| DOI |\n| --- |\n|{cell}|\n")
    with pytest.raises(ValueError, match="DOI"):
        p.read_tables([path])


def test_reordered_rows_match_doi_not_previous_line(registry, citation):
    other = {**citation, "line": 4, "doi": "10.1234/other", "title": "Other paper"}
    registry = p.import_citations([other], registry)
    swapped = [{**other, "line": 3}, {**citation, "line": 4}]
    result = p.import_citations(swapped, registry)
    assert len(result["publications"]) == 2
    for record in result["publications"]:
        assert all(c["doi"] == record["doi"] for c in record["original_citations"])


def test_repeat_import_reports_unchanged_and_checks_once(registry, citation, metadata):
    p.enrich(registry, FakeClient(metadata))
    calls = []

    class CountingClient(FakeClient):
        def lookup(self, doi):
            calls.append(doi)
            return super().lookup(doi)

    result, updates = p.import_table_records([citation, citation], registry, CountingClient(metadata))
    assert calls == [citation["doi"]]
    assert result == registry
    assert updates == [{"id": registry["publications"][0]["id"], "doi": citation["doi"],
                        "status": "unchanged", "changes": {}}]


def test_repeat_import_updates_bibliography_but_preserves_curation(registry, citation, metadata):
    record = registry["publications"][0]
    record.update(approved=False, technologies=["confocal"], services=["synthetic-service"],
                  tagging_status="reviewed", cci_involvement="scientific-collaboration",
                  cci_involvement_override="scientific-collaboration", notes="Curator annotation")
    record["overrides"] = {"year": 2023}
    record["reporting_years_override"] = record["reporting_years"] = [2024]
    protected = {key: copy.deepcopy(value) for key, value in record.items()
                 if key not in {"metadata", "metadata_check"}}
    updated = {**metadata, "title": "Final publication title", "year": 2025}
    result, updates = p.import_table_records([citation], registry, FakeClient(updated))
    after = result["publications"][0]
    assert after["metadata"] == updated
    assert all(after[key] == value for key, value in protected.items())
    assert p.effective_metadata(after)["year"] == 2023
    assert updates[0]["status"] == "updated"
    assert updates[0]["changes"]["title"]["after"] == updated["title"]


def test_repeat_import_outage_preserves_record(registry, citation):
    before = copy.deepcopy(registry)
    result, updates = p.import_table_records([citation], registry, FakeClient(error=True))
    assert updates[0]["status"] == "lookup_failed"
    assert updates[0]["changes"] == {}
    assert result["publications"][0]["metadata"] == before["publications"][0]["metadata"]
    assert registry == before


def test_repeat_import_does_not_replace_metadata_with_incomplete_response(registry, citation, metadata):
    metadata["journal"] = ""
    result, updates = p.import_table_records([citation], registry, FakeClient(metadata))
    assert result["publications"][0]["metadata"] == registry["publications"][0]["metadata"]
    assert result["publications"][0]["metadata_check"]["status"] == "review"
    assert updates[0]["changes"] == {}
    assert updates[0]["status"] == "review_required"


def test_failed_live_check_does_not_regress_metadata_from_cached_fallback(registry, citation, metadata):
    record = registry["publications"][0]
    record["metadata"]["title"] = "Newer manually supplied title"

    class StaleClient(FakeClient):
        def lookup(self, doi):
            return {**super().lookup(doi), "refresh_error": "Provider unavailable"}

    result, updates = p.import_table_records([citation], registry, StaleClient(metadata))
    assert result["publications"][0]["metadata"] == record["metadata"]
    assert updates[0]["status"] == "lookup_failed"
    assert updates[0]["changes"] == {}


def test_reimport_keeps_manual_doi_correction_and_refreshes_preserved_id(registry, citation, metadata):
    record = registry["publications"][0]
    record["doi"] = "10.1234/corrected"
    record["id"] = "explicitly-preserved-id"
    calls = []

    class CorrectedClient(FakeClient):
        def lookup(self, doi):
            calls.append(doi)
            return super().lookup(doi)

    result, updates = p.import_table_records([citation], registry, CorrectedClient(metadata))
    assert len(result["publications"]) == 1
    assert calls == ["10.1234/corrected"]
    assert updates[0]["id"] == "explicitly-preserved-id"


def test_import_cli_forces_live_refresh_and_writes_change_report(tmp_path, monkeypatch, registry, metadata, vocabulary):
    path = tmp_path / "incoming.md"
    path.write_text("| DOI |\n| --- |\n| 10.1234/test |\n")
    registry_path, vocab_path, report = (tmp_path / name for name in ("registry.yml", "vocab.yml", "report.json"))
    p.save_registry(registry_path, registry)
    p.save_registry(vocab_path, vocabulary)
    options = []

    def client_factory(*args, **kwargs):
        options.append(kwargs)
        return FakeClient(metadata)

    monkeypatch.setattr(p, "MetadataClient", client_factory)
    p.main(["--registry", str(registry_path), "--vocabulary", str(vocab_path), "--report", str(report),
            "import-tables", str(path)])
    assert options[0]["refresh"] is True
    assert p.read_json(report)["import_updates"][0]["status"] == "updated"
    assert len(p.read_registry(registry_path)["publications"]) == 1


def test_failed_doi_only_import_writes_report_without_overwriting_registry(tmp_path, monkeypatch, vocabulary):
    path = tmp_path / "incoming.md"
    path.write_text("| DOI |\n| --- |\n| 10.1234/test |\n")
    registry_path, vocab_path, report = (tmp_path / name for name in ("registry.yml", "vocab.yml", "report.json"))
    p.save_registry(registry_path, {"schema_version": 1, "publications": []})
    before = registry_path.read_bytes()
    p.save_registry(vocab_path, vocabulary)
    monkeypatch.setattr(p, "MetadataClient", lambda *a, **k: FakeClient(error=True))
    with pytest.raises(ValueError, match="title is required"):
        p.main(["--registry", str(registry_path), "--vocabulary", str(vocab_path), "--report", str(report),
                "import-tables", str(path)])
    assert registry_path.read_bytes() == before
    assert p.read_json(report)["import_updates"][0]["status"] == "lookup_failed"


def test_no_doi_has_stable_id(citation):
    citation["doi"] = None
    assert p.import_citations([citation]) == p.import_citations([citation])
    assert p.import_citations([citation])["publications"][0]["id"].startswith("cci-")


def test_metadata_cleaning_and_missing_fields():
    result = p.normalize_metadata({"DOI": "10.1234/test", "title": ["<i>Test</i> &amp; work"],
                                   "author": [{"family": "Åström"}], "issued": {"date-parts": [[2023]]}})
    assert result["title"] == "Test & work"
    assert result["authors"] == ["Åström"]
    assert result["journal"] == ""
    with pytest.raises(ValueError):
        p.normalize_metadata({"DOI": "10.1234/test", "title": []})


def test_comparison_tolerates_formatting(citation, metadata):
    metadata["title"] = "Synthetic microscopy test paper."
    metadata["year"] = 2025
    assert not any(i["severity"] == "review" for i in p.compare_metadata(citation, metadata))
    metadata["title"] = "Completely different biology paper"
    metadata["authors"] = ["Different Person"]
    assert {i["field"] for i in p.compare_metadata(citation, metadata) if i["severity"] == "review"} == {"title", "authors"}


class FakeClient:
    def __init__(self, metadata=None, error=False):
        self.metadata, self.error = metadata, error

    def lookup(self, doi):
        if self.error:
            raise LookupError("Synthetic outage")
        return {"doi": doi, "provider": "fixture", "metadata": self.metadata}


def test_overrides_and_approval_survive_refresh(registry, metadata):
    record = registry["publications"][0]
    record["overrides"] = {"title": "Manually corrected title"}
    record["technologies"] = ["confocal", "light_sheet"]
    record["cci_involvement"] = "scientific-collaboration"
    record["cci_involvement_override"] = "scientific-collaboration"
    original_id = record["id"]
    p.enrich(registry, FakeClient(metadata))
    assert record["metadata_check"]["status"] == "matched"
    assert p.effective_metadata(record)["title"] == "Manually corrected title"
    assert record["approved"] is True
    assert record["technologies"] == ["confocal", "light_sheet"]
    assert record["reporting_years"] == [2024]
    p.enrich(registry, FakeClient(error=True))
    assert record["metadata"]["authors"] == metadata["authors"]
    assert record["metadata_check"]["status"] == "matched"
    assert record["id"] == original_id


def test_mismatch_keeps_original_citation(registry, metadata):
    metadata["title"] = "Unrelated work"
    p.enrich(registry, FakeClient(metadata))
    record = registry["publications"][0]
    assert record["metadata_check"]["status"] == "review"
    assert record["metadata"]["title"] == "Synthetic microscopy test paper"
    assert record["retrieved"]["metadata"]["title"] == "Unrelated work"


def test_failed_lookup_keeps_approved_fallback(registry, vocabulary):
    p.enrich(registry, FakeClient(error=True))
    assert registry["publications"][0]["metadata_check"]["status"] == "lookup_failed"
    assert len(p.public_catalogue(registry, vocabulary)["publications"]) == 1


def test_public_export_allowlist_and_determinism(registry, vocabulary):
    record = registry["publications"][0]
    record["notes"] = "PRIVATE synthetic note"
    record["cci_involvement"] = "scientific-collaboration"
    record["cci_involvement_override"] = "scientific-collaboration"
    record["technologies"] = ["confocal", "light_sheet"]
    exported = p.public_catalogue(registry, vocabulary)
    public = exported["publications"][0]
    assert "notes" not in public
    assert "original_citations" not in public
    assert public["technologies"] == ["confocal", "light_sheet"]
    assert public["cci_involvement"] == "scientific-collaboration"
    assert "cci_involvement_override" not in public
    assert exported == p.public_catalogue(copy.deepcopy(registry), vocabulary)
    record["approved"] = False
    assert not p.public_catalogue(registry, vocabulary)["publications"]


@pytest.mark.parametrize("change", [
    {"approved": "true"}, {"technologies": ["invented"]}, {"technologies": ["confocal", "confocal"]},
    {"overrides": {"notes": "private"}}, {"overrides": {"year": True}},
    {"overrides": {"publication_url": "javascript:alert(1)"}},
    {"overrides": {"title": ""}}, {"overrides": {"authors": "Not a list"}},
])
def test_validation_errors(registry, vocabulary, change):
    registry["publications"][0].update(change)
    with pytest.raises(ValueError):
        p.validate(registry, vocabulary)


def test_duplicate_registry_rejected(registry, vocabulary):
    registry["publications"].append(copy.deepcopy(registry["publications"][0]))
    with pytest.raises(ValueError):
        p.validate(registry, vocabulary)


def test_cached_lookup_never_uses_network(tmp_path, monkeypatch, metadata):
    client = p.MetadataClient(tmp_path, offline=True)
    key = p.hashlib.sha256(b"10.1234/test").hexdigest() + ".json"
    p.write_json(tmp_path / key, {"doi": "10.1234/test", "provider": "fixture", "metadata": metadata})
    monkeypatch.setattr(client.crossref, "works", lambda **kwargs: pytest.fail("Network used"))
    assert client.lookup("10.1234/test")["cached"]
    with pytest.raises(LookupError):
        client.lookup("10.1234/missing")


def test_manual_cli_and_preserved_corrections(tmp_path, vocabulary):
    registry_path, report_path, vocab_path = (tmp_path / name for name in ["registry.yml", "report.json", "vocab.yml"])
    p.save_registry(vocab_path, vocabulary)
    common = ["--registry", str(registry_path), "--vocabulary", str(vocab_path), "--report", str(report_path), "--offline"]
    p.main(common + ["add", "--manual", "--title", "Synthetic manual record", "--author", "Åström A",
                     "--journal", "Test journal", "--year", "2024", "--approved"])
    result = p.read_registry(registry_path)
    record_id = result["publications"][0]["id"]
    p.main(common + ["edit", record_id, "--title", "Corrected synthetic title"])
    assert p.read_registry(registry_path)["publications"][0]["overrides"]["title"] == "Corrected synthetic title"
    p.main(common + ["build", "--output", str(tmp_path / "public.json")])
    assert p.read_json(tmp_path / "public.json")["publications"][0]["id"] == record_id


def test_preprint_disclaimer_and_book_citation(tmp_path, metadata, citation):
    path = tmp_path / "table.md"
    path.write_text("| Åström A | 2024 | Synthetic test | Journal | doi:10.1234/test This content is a preprint and has not been peer-reviewed. |\n")
    row = p.read_tables([path])[0]
    assert row["doi"] == "10.1234/test"
    assert row["doi_warning"]
    assert "preprint" in row["original_doi"]
    citation["title"] += ". In: Editor E. (eds) Synthetic Book."
    assert not any(i["severity"] == "review" for i in p.compare_metadata(citation, metadata))


def test_missing_provider_journal_keeps_fallback(registry, metadata):
    metadata["journal"] = ""
    p.enrich(registry, FakeClient(metadata))
    assert registry["publications"][0]["metadata_check"]["status"] == "review"
    assert registry["publications"][0]["metadata"]["journal"] == "Test Journal 1:1"


def test_doi_correction_keeps_id_and_import_does_not_duplicate(tmp_path, registry, vocabulary, citation):
    registry_path = tmp_path / "registry.yml"
    vocab_path = tmp_path / "vocabulary.yml"
    p.save_registry(registry_path, registry)
    p.save_registry(vocab_path, vocabulary)
    original_id = registry["publications"][0]["id"]
    p.main(["--registry", str(registry_path), "--vocabulary", str(vocab_path),
            "--report", str(tmp_path / "report.json"), "edit", original_id, "--doi", "10.1234/corrected"])
    corrected = p.read_registry(registry_path)
    assert corrected["publications"][0]["doi"] == "10.1234/corrected"
    assert corrected["publications"][0]["id"] == original_id
    assert len(p.import_citations([citation], corrected)["publications"]) == 1


def test_provider_fallback_and_cache(tmp_path, monkeypatch):
    client = p.MetadataClient(tmp_path)
    calls = []

    def crossref_failure(**kwargs):
        raise LookupError("Synthetic Crossref miss")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"DOI": "10.1234/test", "title": "Synthetic CSL title",
                    "author": [{"family": "Åström"}], "issued": {"date-parts": [[2024]]}}

    def get(*args, **kwargs):
        calls.append(args[0])
        assert kwargs["headers"]["Accept"] == "application/vnd.citationstyles.csl+json"
        return Response()

    monkeypatch.setattr(client.crossref, "works", crossref_failure)
    monkeypatch.setattr(p.requests, "get", get)
    monkeypatch.setattr(p.time, "sleep", lambda seconds: None)
    assert client.lookup("10.1234/test")["provider"] == "doi-csl"
    assert client.lookup("10.1234/test")["cached"]
    assert len(calls) == 1


def test_wrong_returned_doi_is_rejected(tmp_path, monkeypatch):
    client = p.MetadataClient(tmp_path)
    monkeypatch.setattr(client.crossref, "works", lambda **kwargs: {"message": {"DOI": "10.1234/wrong", "title": ["Wrong"]}})
    monkeypatch.setattr(p.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(LookupError("Synthetic miss")))
    with pytest.raises(LookupError, match="different DOI"):
        client.lookup("10.1234/test")
    assert not list(tmp_path.glob("*.json"))


def test_import_is_idempotent_and_preserves_unapproval(registry, citation):
    registry["publications"][0]["approved"] = False
    assert p.import_citations([citation], registry) == registry


def test_public_order_is_independent_of_registry_order(registry, citation, vocabulary):
    other = {**citation, "line": 9, "doi": "10.1234/other", "year": 2025}
    registry = p.import_citations([other], registry)
    forward = p.public_catalogue(registry, vocabulary)
    registry["publications"].reverse()
    assert p.public_catalogue(registry, vocabulary) == forward
    assert forward["publications"][0]["year"] == 2025


def test_correction_doi_is_flagged_even_when_title_is_similar(citation, metadata):
    citation["title"] = "A long synthetic title about cellular microscopy and image acquisition in cultured tissues"
    metadata["title"] = "Corrigendum to " + citation["title"]
    assert any("correction" in issue.get("reason", "") for issue in p.compare_metadata(citation, metadata))


def test_failed_refresh_reuses_last_good_cache(tmp_path, metadata, monkeypatch):
    key = p.hashlib.sha256(b"10.1234/test").hexdigest() + ".json"
    p.write_json(tmp_path / key, {"doi": "10.1234/test", "provider": "fixture", "metadata": metadata})
    client = p.MetadataClient(tmp_path, refresh=True)

    def failure(*args, **kwargs):
        raise LookupError("Synthetic outage")

    monkeypatch.setattr(client.crossref, "works", failure)
    monkeypatch.setattr(p.requests, "get", failure)
    result = client.lookup("10.1234/test")
    assert result["metadata"] == metadata
    assert result["refresh_error"]


def test_accepted_review_survives_identical_refresh_but_not_changed_metadata(registry, metadata):
    metadata["authors"] = ["Different First Author"]
    p.enrich(registry, FakeClient(metadata))
    record = registry["publications"][0]
    accepted_metadata = copy.deepcopy(record["metadata"])
    p.accept_review(record, note="Synthetic discrepancy accepted")
    p.enrich(registry, FakeClient(metadata))
    assert record["metadata_check"]["status"] == "accepted"
    assert record["metadata"] == accepted_metadata
    changed = {**metadata, "title": "Different title requiring fresh review"}
    p.enrich(registry, FakeClient(changed))
    assert record["metadata_check"]["status"] == "review"


def test_accepting_retrieved_metadata_preserves_explicit_overrides(registry, metadata, vocabulary):
    metadata["authors"] = ["Different First Author"]
    p.enrich(registry, FakeClient(metadata))
    record = registry["publications"][0]
    record["overrides"]["year"] = 2025
    p.accept_review(record, use_retrieved=True, note="Synthetic author update accepted")
    assert p.effective_metadata(record)["authors"] == ["Different First Author"]
    assert record["overrides"] == {"year": 2025}
    assert "metadata_review" not in p.public_catalogue(registry, vocabulary)["publications"][0]


def test_year_overrides_survive_refresh_and_reimport(registry, citation, metadata, vocabulary):
    record = registry["publications"][0]
    record["overrides"]["year"] = 2025
    record["reporting_years_override"] = [2025]
    record["reporting_years"] = [2025]
    p.enrich(registry, FakeClient(metadata))
    imported = p.import_citations([citation], registry)
    public = p.public_catalogue(imported, vocabulary)["publications"][0]
    assert public["year"] == 2025
    assert public["reporting_years"] == [2025]
    assert imported["publications"][0]["original_citations"][0]["year"] == 2024


def test_final_issue_year_has_priority_over_online_year():
    result = p.normalize_metadata({"DOI": "10.1234/test", "title": ["Synthetic test"],
                                   "published": {"date-parts": [[2024, 9, 1]]},
                                   "published-print": {"date-parts": [[2025, 2, 1]]}})
    assert result["year"] == 2025


def test_doi_metadata_preferred_for_updated_author_list(registry, metadata):
    metadata["authors"] = ["New First Author", "Anna Åström"]
    metadata["authors_text"] = "; ".join(metadata["authors"])
    p.enrich(registry, FakeClient(metadata))
    assert registry["publications"][0]["metadata"]["authors"] == metadata["authors"]
    assert registry["publications"][0]["metadata_check"]["status"] == "review"


def test_update_check_reports_changes_without_mutation(registry, metadata, tmp_path):
    record = registry["publications"][0]
    record["technologies"] = ["confocal", "light_sheet"]
    record["cci_contributions"] = {"image_analysis": True}
    record["overrides"]["year"] = 2025
    before = copy.deepcopy(registry)
    summary = p.check_updates(registry, FakeClient(metadata), tmp_path / "updates.json")
    assert registry == before
    assert summary["changed"] == 1
    report = p.read_json(tmp_path / "updates.json")
    assert "year" in report["records"][0]["protected_fields"]
    assert set(report["records"][0]["changes"]) <= p.FIELDS
    assert "cci_contributions" not in report["records"][0]["changes"]


def test_update_check_reports_unchanged_failure_and_missing_doi(registry, metadata, tmp_path):
    record = registry["publications"][0]
    record["retrieved"] = {"metadata": metadata, "provider": "fixture"}
    assert p.check_updates(registry, FakeClient(metadata), tmp_path / "updates.json")["unchanged"] == 1
    assert p.check_updates(registry, FakeClient(error=True), tmp_path / "updates.json")["failed"] == 1
    record["doi"] = None
    assert p.check_updates(registry, FakeClient(error=True), tmp_path / "updates.json")["no_doi"] == 1


def test_refresh_cannot_change_cci_contributions(registry, metadata):
    record = registry["publications"][0]
    curated = {"approved": True, "technologies": ["confocal", "light_sheet"],
               "services": ["analysis"], "tagging_status": "reviewed",
               "cci_contributions": {"imaging": True, "staff_support": "curated"}}
    curated.update(cci_involvement="scientific-collaboration", cci_involvement_override="scientific-collaboration")
    record.update(copy.deepcopy(curated))
    p.enrich(registry, FakeClient(metadata))
    assert {field: record[field] for field in curated} == curated


def test_update_check_cli_exit_codes_and_registry_unchanged(tmp_path, registry, vocabulary, metadata, monkeypatch):
    registry_path, vocab_path = tmp_path / "registry.yml", tmp_path / "vocabulary.yml"
    p.save_registry(registry_path, registry)
    p.save_registry(vocab_path, vocabulary)
    before = registry_path.read_bytes()
    monkeypatch.setattr(p, "MetadataClient", lambda *args, **kwargs: FakeClient(metadata))
    common = ["--registry", str(registry_path), "--vocabulary", str(vocab_path)]
    command = ["check-updates", "--output", str(tmp_path / "updates.json")]
    assert p.main(common + command) == 0
    assert p.main(common + command + ["--fail-on-changes"]) == 2
    monkeypatch.setattr(p, "MetadataClient", lambda *args, **kwargs: FakeClient(error=True))
    assert p.main(common + command) == 3
    assert registry_path.read_bytes() == before


def test_stale_cache_is_failure_in_live_update_check(registry, metadata, tmp_path):
    class StaleClient:
        def lookup(self, doi):
            return {"provider": "fixture", "metadata": metadata, "refresh_error": "Synthetic outage"}

    summary = p.check_updates(registry, StaleClient(), tmp_path / "updates.json")
    assert summary["failed"] == 1
    assert summary["unchanged"] == 0


def test_build_with_update_check_does_not_apply_changes(tmp_path, registry, vocabulary, metadata, monkeypatch):
    registry_path, vocab_path = tmp_path / "registry.yml", tmp_path / "vocabulary.yml"
    p.save_registry(registry_path, registry)
    p.save_registry(vocab_path, vocabulary)
    before = registry_path.read_bytes()
    monkeypatch.setattr(p, "MetadataClient", lambda *args, **kwargs: FakeClient(metadata))
    monkeypatch.setattr(p, "UPDATES", tmp_path / "updates.json")
    p.main(["--registry", str(registry_path), "--vocabulary", str(vocab_path),
            "build", "--output", str(tmp_path / "public.json"), "--check-updates"])
    assert registry_path.read_bytes() == before
    assert p.read_json(tmp_path / "public.json")["publications"][0]["authors"] == []


def test_public_vocabulary_excludes_internal_notes(registry, vocabulary):
    vocabulary["technologies"][0].update(label="Confocal microscopy", notes="Synthetic private note")
    exported = p.public_catalogue(registry, vocabulary)["vocabulary"]
    assert exported["technologies"][0] == {"id": "confocal", "label": "Confocal microscopy"}


def test_abstract_jats_to_plain_text_preserves_paragraphs():
    text = p.abstract_text('<jats:abstract><jats:title>Abstract</jats:title><jats:p>First <jats:italic>paragraph</jats:italic> &amp; result.</jats:p><jats:p>Second paragraph.</jats:p><script>bad code</script></jats:abstract>')
    assert text == "First paragraph & result.\n\nSecond paragraph."


@pytest.mark.parametrize("value", [None, "", "  ", "<jats:p/>", "No abstract available.", "Abstract not available."])
def test_missing_abstract_is_optional(value):
    assert p.abstract_text(value) is None


def test_abstract_license_provenance_and_private_candidate():
    raw = {"abstract": "Synthetic abstract.", "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/", "content-version": "vor"}]}
    abstract = p.extract_abstract(raw, "10.1234/test")
    assert abstract["source_url"] == "https://doi.org/10.1234/test"
    assert abstract["public_license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    private = p.extract_abstract({"abstract": "Synthetic private abstract."}, "10.1234/test")
    assert private["text"] == "Synthetic private abstract."
    assert private["public_license_url"] is None


@pytest.mark.parametrize("license", [
    {"URL": "https://publisher.example/terms"},
    {"URL": "https://creativecommons.org/licenses/by/4.0/", "content-version": "am"},
    {"URL": "https://creativecommons.org/licenses/by/4.0/", "start": {"date-parts": [[2999, 1, 1]]}},
    {"URL": "https://creativecommons.org/licenses/by/4.0/", "start": {"date-parts": [[2024, 99, 99]]}},
    {"URL": "https://creativecommons.org/licenses/by/4.0/", "start": {"date-time": "unparseable"}},
    {"URL": "https://creativecommons.org.evil.example/licenses/by/4.0/"},
])
def test_uncertain_abstract_licenses_remain_private(license):
    abstract = p.extract_abstract({"abstract": "Synthetic abstract.", "license": [license]}, "10.1234/test")
    assert abstract["public_license_url"] is None


class AbstractClient(FakeClient):
    def __init__(self, metadata, abstract):
        super().__init__(metadata)
        self.abstract = abstract

    def lookup(self, doi):
        return {**super().lookup(doi), "abstract": self.abstract}


def test_private_abstract_never_exported_and_cci_fields_unchanged(registry, metadata, vocabulary, tmp_path):
    before = copy.deepcopy(registry)
    candidate = p.extract_abstract({"abstract": "Synthetic restricted abstract."}, "10.1234/test")
    store = tmp_path / "abstracts.json"
    summary = p.fetch_abstracts(registry, AbstractClient(metadata, candidate), store)
    assert summary["private_only"] == 1
    assert registry == before
    assert p.read_json(store)["abstracts"][0]["abstract"]["text"] == "Synthetic restricted abstract."
    assert "abstract" not in p.public_catalogue(registry, vocabulary)["publications"][0]


def test_public_abstract_allowlist_and_bibliography_preserved(registry, metadata, vocabulary, tmp_path):
    before = copy.deepcopy(registry["publications"][0])
    candidate = p.extract_abstract({"abstract": "Synthetic open abstract.", "license": "https://creativecommons.org/licenses/by/4.0/"}, "10.1234/test")
    summary = p.fetch_abstracts(registry, AbstractClient(metadata, candidate), tmp_path / "abstracts.json")
    assert summary["publicly_displayable"] == 1
    record = registry["publications"][0]
    assert {k: v for k, v in record.items() if k != "abstract"} == before
    record["abstract"]["notes"] = "Synthetic private note"
    public = p.public_catalogue(registry, vocabulary)["publications"][0]
    assert set(public["abstract"]) == {"text", "source_url", "license_url"}
    assert public["abstract"]["text"] == "Synthetic open abstract."


def test_abstract_for_different_title_needs_review(registry, metadata, tmp_path):
    metadata["title"] = "A completely unrelated synthetic paper"
    candidate = p.extract_abstract({"abstract": "Synthetic abstract.", "license": "https://creativecommons.org/licenses/by/4.0/"}, "10.1234/test")
    summary = p.fetch_abstracts(registry, AbstractClient(metadata, candidate), tmp_path / "abstracts.json")
    assert summary["identity_review"] == 1
    assert "abstract" not in registry["publications"][0]


def test_abstract_outage_retains_last_known_good_text(registry, metadata, tmp_path):
    candidate = p.extract_abstract({"abstract": "Synthetic abstract.", "license": "https://creativecommons.org/licenses/by/4.0/"}, "10.1234/test")
    store = tmp_path / "abstracts.json"
    p.fetch_abstracts(registry, AbstractClient(metadata, candidate), store)
    before = copy.deepcopy(registry)
    summary = p.fetch_abstracts(registry, FakeClient(error=True), store)
    assert summary["failed"] == 1
    assert registry == before
    assert p.read_json(store)["abstracts"][0]["abstract"]["text"] == "Synthetic abstract."


def test_abstract_missing_on_refresh_keeps_private_history(registry, metadata, tmp_path):
    candidate = p.extract_abstract({"abstract": "Synthetic retained abstract."}, "10.1234/test")
    store = tmp_path / "abstracts.json"
    p.fetch_abstracts(registry, AbstractClient(metadata, candidate), store)
    summary = p.fetch_abstracts(registry, AbstractClient(metadata, None), store)
    assert summary["not_available"] == 1
    assert p.read_json(store)["abstracts"][0]["abstract"]["text"] == "Synthetic retained abstract."


def test_unlicensed_public_abstract_rejected(registry, vocabulary):
    registry["publications"][0]["abstract"] = {"text": "Synthetic private abstract.",
                                               "source_url": "https://doi.org/10.1234/test", "license_url": None}
    with pytest.raises(ValueError, match="public abstract"):
        p.public_catalogue(registry, vocabulary)


def test_old_bibliographic_cache_upgraded_for_abstracts(tmp_path, metadata, monkeypatch):
    key = p.hashlib.sha256(b"10.1234/test").hexdigest() + ".json"
    p.write_json(tmp_path / key, {"doi": "10.1234/test", "provider": "fixture", "metadata": metadata})
    client = p.MetadataClient(tmp_path, include_abstracts=True)
    calls = []

    def works(**kwargs):
        calls.append(kwargs)
        return {"message": {"DOI": "10.1234/test", "title": ["Synthetic title"], "abstract": "Synthetic new abstract."}}

    monkeypatch.setattr(client.crossref, "works", works)
    monkeypatch.setattr(p.time, "sleep", lambda delay: None)
    assert client.lookup("10.1234/test")["abstract"]["text"] == "Synthetic new abstract."
    assert client.lookup("10.1234/test")["cached"]
    assert len(calls) == 1


def test_fetch_abstract_cli_saves_private_store(registry, metadata, vocabulary, tmp_path, monkeypatch):
    registry_path, vocab_path, store = (tmp_path / name for name in ["registry.yml", "vocab.yml", "private.json"])
    p.save_registry(registry_path, registry)
    p.save_registry(vocab_path, vocabulary)
    monkeypatch.setattr(p, "ABSTRACT_STORE", store)
    monkeypatch.setattr(p, "MetadataClient", lambda *args, **kwargs: AbstractClient(metadata, None))
    p.main(["--registry", str(registry_path), "--vocabulary", str(vocab_path),
            "--report", str(tmp_path / "report.json"), "fetch-abstracts"])
    assert store.exists()
    assert p.read_registry(registry_path) == registry
