# Phase 4G manual screenshot replacement

## Finding and reproduction

The v0.5 release candidate gate identified a partial replacement path. On the clean `feature/case-management` branch at `2411c97a`, headless Chrome reproduced it using a version-1 case with an accepted screenshot and reassessment. A single drop contained a valid PNG and a TXT file. Streamlit rejected the TXT in the browser, passed the PNG to Python, and the previous callback immediately replaced accepted evidence. The case advanced to version 2 and lost its active reassessment. Version 1 stayed intact.

## Changes

- `dashboard_v1_2.py` validates the full delivered batch before staging prepared screenshots. Staging holds a transient candidate scoped to the current case widget namespace, row version, and evidence revision. It leaves accepted bytes, provenance, the assessment fingerprint, and SQLite untouched. A new delivered selection first clears the old candidate. A delivered batch with any invalid image leaves no candidate.
- The wizard lists the exact candidate filenames and requires **Apply screenshot replacement**. The button identity belongs to that specific candidate. A changed version or evidence revision in the same session requires restaging. An unchanged candidate cannot be applied.
- Apply updates a copy of the investigation and uses the existing optimistic checkpoint. Only a successful save publishes the copy to the live session. A genuine replacement invalidates the reassessment once and creates one case version. A write failure leaves the prior live evidence and saved history intact, and a stale save preserves the competing version. **Clear uploaded screenshots** is an explicit removal action and uses the same commit-before-publication behavior. Unsaved cases apply in memory until saved.
- `test_case_management_ui.py` checks staging, complete and mixed delivered failures, invalidation count, no version on rerun, failed and stale saves, and exact preservation of earlier reports and snapshots. `test_inc_27517.py` and `test_ticket_lab_integration.py` apply staged manual evidence explicitly and retain the existing consent and provenance assertions.

## Verification results

- The full automated suite passed **50 of 50 tests** on Streamlit **1.67.0** in 68.313 seconds, with zero failures, errors or skips. An initial run exposed an older integration test that attempted Gemini reassessment immediately after upload. The test now checks that consent stays disabled until the first screenshot set is applied, then verifies the existing explicit consent flow.
- Desktop headless Chrome confirmed that an all-rejected TXT selection produced no applicable candidate. A mixed valid PNG and rejected TXT staged only the visible PNG. Accepted evidence and reassessment stayed intact until explicit confirmation, which created one version and incremented the evidence revision once. A delivered batch containing a valid PNG and a corrupt PNG was rejected as a unit.
- A separate Chrome run injected a repository write failure, then created a competing row version. Both attempts retained the prior live screenshot and reassessment. The stale attempt also retained the competing saved verdict. AppTest verified exact preservation of prior issued Markdown and JSON bytes.
- `git diff --check` passed.

## Boundaries

Streamlit's Python callback sees only the files the browser delivered. It cannot reliably distinguish a file rejected by the browser from a file the user never selected. An all-rejected browser action cannot create a candidate and can leave an earlier, explicitly listed candidate visible if Streamlit sends no callback. In all cases the accepted investigation remains unchanged without confirmation of the displayed candidate.

Verification used synthetic screenshots, disposable SQLite, and mocked or blocked Gemini. The schema, real database, historical reports, and original audit were untouched. Browser verification used desktop headless Chrome.
