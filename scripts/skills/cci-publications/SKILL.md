---
name: cci-publications
description: Import and curate CCI website publications from DOI/PMID tables, preserve existing annotations, validate candidate registries and prepare local review. Use for publication database work in this repository.
---

# CCI publications

Read [the maintained workflow](../../README.md) before running imports or making
curation changes. It contains the supported identifiers, exact commands, candidate
review process, annotation-preservation checks, staff classification policy and
local/browser validation. Run commands from the repository root.

Use the existing scripts rather than constructing a second importer. Work within
the user's requested scope and existing session authorization. DOI/PMID metadata
updates must preserve curated annotations; follow the README's new-record-only
pattern for staff classification. Keep private source/evidence files local;
run matching locally and report only the necessary results. Follow the README's
personal-data guidance before sending nonpublic material to an external agent.

Report the batch's additions, unchanged/updated records, failures, preservation
checks and test results. Distinguish local changes from publishing. Use the user's
requested release workflow; preparing an import does not itself request a push
or merge. Maintain detailed procedures in the README rather than duplicating them
in this skill.
