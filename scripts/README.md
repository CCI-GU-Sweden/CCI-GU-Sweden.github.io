# CCI publication import and curation

Use these tools to import DOI or PubMed identifiers, retrieve bibliographic
metadata, review changes and generate the website catalogue. Importing locally
does not publish anything; merging a release PR into `main` publishes the site.

Run commands from the repository root. This document is also the workflow for
coding agents. The portable agent entry point is
[skills/cci-publications/SKILL.md](skills/cci-publications/SKILL.md).

For an agent-assisted import, a starting prompt is: "Read
`scripts/skills/cci-publications/SKILL.md` and import the supplied file following
`scripts/README.md`; prepare a validated local result for review."

## Environment and files

Create the Python environment once, then activate it:

```bash
conda env create -f environment.yml
conda activate cci-page
python scripts/publications.py --help
```

On later visits, only activate the existing environment. See
[local development setup](../_development/README.txt) for Ruby/Jekyll setup.

| Path | Purpose |
| --- | --- |
| `_publications/registry.yml` | Canonical publication records and curator overrides |
| `_publications/vocabulary.yml` | Stable technology/service labels |
| `assets/data/publications.json` | Generated public catalogue; rebuild rather than edit |
| `private_data/` | Source tables, staff roster, reports and private evidence; ignored by Git and Jekyll |
| `.local/publications-cache/` | Cached DOI and PubMed responses; ignored by Git |

The registry is committed to a public repository, including its source-citation
provenance. Keep confidential notes in `private_data/`.

## Personal data and agent use

Keep public records limited to bibliographic information and the agreed
publication-level labels. Author names are personal data even when published
elsewhere; CCI/university policy must cover the purpose, lawful basis and handling
of corrections or objections. Do not add patient-level information, personal
contact details or private staff/employment notes to source citations or the
canonical registry. Public availability alone is not an exemption from GDPR.

Run staff matching locally and report the resulting classifications/counts.
Avoid copying the roster, individual employment periods or full private reports
into PRs or agent chats. Use an institution-approved service and only the
necessary data if nonpublic information needs to be processed by an external
agent. Publication metadata queries send the selected identifier to Crossref,
DOI.org or NCBI; an optional contact email is also sent when configured.

Git ignores and Jekyll exclusions prevent ordinary inclusion here; they do not
provide access control, encryption, or erase previous Git history. The README
and skill will themselves be public in Git, although `scripts/` is excluded
from the rendered site. Review the staged files before release. See
[IMY's GDPR guidance](https://www.imy.se/verksamhet/dataskydd/det-har-galler-enligt-gdpr/)
and the [EU data-minimisation principles](https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/principles-gdpr_en).

## Input format

Save a Markdown table under `private_data/`. `DOI` and `Identifier` are equivalent
column headers. A table may contain mixed identifiers:

```markdown
## 2015

| Article | Identifier |
| --- | --- |
| Optional citation for reference | 10.1234/example |
| Another optional citation | PMID:12345678 |
```

All identifiers in these examples are illustrative; replace them before importing.
Supported values:

- A DOI, `doi:10.…`, a DOI URL, or a Markdown DOI link.
- `PMID:12345678`, a PubMed URL such as
  `https://pubmed.ncbi.nlm.nih.gov/12345678/`, or a Markdown PubMed link.
- Bare numeric IDs are rejected: use the `PMID:` prefix.

Only the identifier is needed for provider retrieval. Optional `Authors` (or
`Author`), `Year`, `Title`, `Journal` (or `Source`) and `Article` columns may be
in any order. `Article` retains a complete citation for reference; it is not
mistaken for a structured title. Original five-column and numbered six-column
tables remain supported.

A `## 2015` heading supplies the historical **reporting year** when a Year cell
is absent. The website uses the provider's publication year, with explicit
curator overrides taking priority. Without a source year, the retrieved year
also supplies the reporting year. Different historical groupings are retained.

For confirmed DOI absence, use a PMID and optionally add a `DOI status` column
containing `confirmed-unavailable`. Missing DOI metadata from PubMed alone is
recorded as `not-listed`, which does not establish confirmed absence. Do not
invent an identifier or place `no-doi-available` in an identifier-only table.

## Import into a private candidate

Start on a clean checkout and create a task branch. Keep unrelated work intact.
Use a fresh review directory for each batch; the names below are examples.

```bash
git status --short --branch
git switch -c feature/publications-next-batch
mkdir -p private_data/import-review-next-batch
cp _publications/registry.yml private_data/import-review-next-batch/baseline.yml
cp _publications/registry.yml private_data/import-review-next-batch/candidate.yml

python scripts/publications.py \
  --registry private_data/import-review-next-batch/candidate.yml \
  --report private_data/import-review-next-batch/report.json \
  import-tables private_data/incoming-publications.md
```

Replace the source filename with the supplied file. Global options such as
`--registry`, `--report` and `--offline` go **before** the subcommand. Each
command's `--help` lists its options. There is no `--dry-run` switch: the private
candidate is the preview. Use `--offline` to reuse cached metadata without a
live update check.

Online table imports query fresh metadata once per selected record. Repeated
DOIs/PMIDs are expected. They merge provenance/reporting years into existing
records and refresh changed bibliographic fields while retaining IDs,
technology/service lists, CCI involvement, approval, overrides, abstracts and
other curated annotations. Separate preprint and published DOIs remain separate.

PMIDs are resolved before merging. If PubMed returns an already registered DOI,
the existing DOI record is reused. A DOI discovered later for a PMID-only record
keeps that record's internal ID. If DOI and PMID already identify two separate
records, the importer stops for explicit reconciliation rather than losing either
record's annotations.

## Review and classify new records

Inspect `report.txt`, `report.csv` and `report.json` in the review directory.
JSON `import_updates` distinguishes new, unchanged, updated, review-required and
failed lookups, with before/after fields and identifier changes when applicable.
Review DOI/PMID identity, title, authors, journal and effective year. PMID/DOI-only
rows without a structured source title are marked for review even when retrieval
succeeds; that flag is not itself a lookup failure.

Incomplete new metadata prevents saving an incomplete candidate; the report is
still written. Failed refreshes retain usable existing metadata. Retry the lookup
or supply verified manual fields; do not present cached data as a successful live
check or fabricate missing information.

CCI's existing policy approves entries supplied in its publication tables. New
records start with empty technology lists and pending technology review. Do not
infer technology tags merely from staff expertise or CCI involvement. The public
incomplete-tagging notice must remain visible while coverage is incomplete.

Classify **new records only** with the private roster and established exact
staff-name/effective-year policy. Confirmed matches mean scientific collaboration;
otherwise the requested default is service provision. Older staff absent from the
roster may need later curation. This example also verifies preservation of existing
annotations before saving the candidate:

```python
# Run from the repository root with the cci-page Python environment.
import sys
from pathlib import Path
sys.path.insert(0, "scripts")
from publications import read_registry, save_registry, validate, VOCABULARY
from classify_cci_involvement import classify, write_reports, STAFF

folder = Path("private_data/import-review-next-batch")
before = read_registry(folder / "baseline.yml")
candidate = read_registry(folder / "candidate.yml")
old = {r["id"]: r for r in before["publications"]}
current = {r["id"]: r for r in candidate["publications"]}
assert old.keys() <= current.keys()
mutable = {"metadata", "retrieved", "metadata_check", "original_citations",
           "reporting_years", "last_lookup_error", "doi", "pmid", "pmcid", "doi_status"}
for rid, previous in old.items():
    assert {k: v for k, v in previous.items() if k not in mutable} == {
        k: v for k, v in current[rid].items() if k not in mutable}
    assert all(c in current[rid]["original_citations"] for c in previous["original_citations"])
    assert set(previous["reporting_years"]) <= set(current[rid]["reporting_years"])

new = {"schema_version": 1, "publications": [
    r for r in candidate["publications"] if r["id"] not in old]}
classified, evidence = classify(new, read_registry(STAFF))
by_id = {r["id"]: r for r in classified["publications"]}
candidate["publications"] = [by_id.get(r["id"], r) for r in candidate["publications"]]
validate(candidate, read_registry(VOCABULARY))
save_registry(folder / "candidate.yml", candidate)
write_reports(evidence, STAFF, folder / "new-cci-involvement")
```

Inspect all intended bibliographic/identifier changes in the report separately;
they are excluded from the annotation-preservation assertion. Reimport the same
file into a separate candidate copy with `--offline` to verify idempotency: the
record count and record data should stay unchanged. This tests repeat handling,
not whether providers have changed since the original live check.

## Apply, build and review locally

After the candidate passes review:

```bash
cp private_data/import-review-next-batch/candidate.yml _publications/registry.yml
python scripts/publications.py validate
python scripts/publications.py build
python -m pytest -q
node tests/publications.test.mjs
bash _development/site.sh check
```

Preview with `bash _development/site.sh serve` (or `serve cci-page` when the local
alias is installed). Inspect result counts, search, year/involvement/technology
filters and DOI/PubMed links at desktop and mobile widths.

For automated browser checks, see [portal testing setup](../_development/portal.txt).
After installing its local Playwright dependencies, run a separate test server:

```bash
python3 -m http.server 4001 --bind 127.0.0.1 --directory _site
```

Then in another terminal run `bash _development/test-portal.sh`. The browser suite
uses synthetic fixtures for PMID links/search and other edge cases; it does not
add synthetic publications to the real catalogue.

Review the diff and stage only intended files. Keep source tables, reports,
staff evidence and cache files out of Git. Follow the user's release instruction;
the usual workflow here is a pushed feature branch, a web-created PR, local
review, and merge into `main`. An import request alone does not request publishing.

## Manual corrections and other operations

Use `show RECORD_ID` to inspect a record and `edit RECORD_ID` for explicit
corrections. Run the same commands against the candidate with global `--registry`
and `--report` options while reviewing an import.

```bash
python scripts/publications.py show RECORD_ID
python scripts/publications.py edit RECORD_ID --year 2015
python scripts/publications.py edit RECORD_ID --doi-status confirmed-unavailable
python scripts/publications.py edit RECORD_ID --doi 10.1234/corrected
```

Replace the placeholders. `edit` stores bibliographic overrides; ordinary provider
refreshes preserve them. Explicit DOI corrections keep the internal ID. Rebuild
the public JSON after any adopted record changes.

A publication with neither DOI nor PMID can be added manually with verified
fields and a publication URL:

```bash
python scripts/publications.py add --manual \
  --title "Verified article title" --author "Given Family" \
  --journal "Verified journal" --year 2015 \
  --publication-url https://example.org/article --approved
```

Without an external identifier, repeated manual additions are not automatically
deduplicated; edit the existing record instead. Manual `add` defaults to unapproved
unless `--approved` is supplied, unlike the agreed table-import policy.

Other tools are separate steps, not prerequisites for ordinary imports:

- `publications.py check-updates`: report fresh metadata differences without
  editing the registry. PMID-only records use PubMed. `refresh --id RECORD_ID`
  applies eligible provider metadata changes.
- `publications.py fetch-abstracts --id RECORD_ID`: collect abstracts privately;
  only separately eligible text may enter the public abstract field.
- `classify_cci_involvement.py`: involvement reports from the private staff roster.
  Its `--apply` mode recalculates all supplied records; use the new-only pattern
  above when existing curator choices must be preserved.
- `publications_fulltext.py`: separate article-text collection; inspect `--help`
  before use. Metadata import does not download full texts or infer technology tags.
- `validate_technology_evidence.py` and `apply_technology_tags.py`: validate private
  evidence and apply a separately curated technology plan. Plans with conflicting
  existing tags require explicit curation rather than silent replacement.

See [detailed publication workflow](../_development/publications.txt) for the
metadata review, abstract, update-check and technology-assignment commands.
