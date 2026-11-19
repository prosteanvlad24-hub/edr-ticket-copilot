#!/usr/bin/env python3
"""
drive_streamlit.py - feeds a ticket_lab run into your running Streamlit app through a real browser.

Setup (once)
  pip install playwright
  playwright install chromium

Usage
  1. streamlit run dashboard_v1_2.py                        # your app, e.g. http://localhost:8501
  2. python ticket_lab.py generate -n 6 --seed 42           # creates runs/<run>
  3. python drive_streamlit.py runs/<run> --headed --tickets INC-20418      # try ONE ticket first
  4. python drive_streamlit.py runs/<run> --headed                          # all tickets
  5. python ticket_lab.py report runs/<run>

Evidence (screenshots) too
  python ticket_lab.py evidence runs/<run> --tickets INC-20418 --variants match,contradict,injection
  python drive_streamlit.py runs/<run> --evidence --tickets INC-20418 --headed

Selectors are built from the visible labels in the app (see the --label-* and --btn-* options).
If a step fails, a debug screenshot is saved as <run>/debug_<name>.png and the run continues.
Initial analysis calls the configured Gemini models. --evidence explicitly submits the
selected fictional screenshots for evidence reassessment.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sys.exit("Playwright is missing: pip install playwright && playwright install chromium")


def idle(page, timeout):
    """Wait until Streamlit finishes its current run."""
    page.wait_for_timeout(900)
    page.locator('[data-testid="stStatusWidget"]').wait_for(state="hidden", timeout=timeout)


def btn(page, pattern):
    return page.get_by_role("button", name=re.compile(pattern, re.I)).first


def tab(page, pattern):
    return page.get_by_role("tab", name=re.compile(pattern, re.I)).first


def set_select(page, label, value):
    page.get_by_label(label).first.click()
    page.get_by_role("option", name=str(value), exact=True).first.click()


def set_number(page, label, value):
    box = page.get_by_label(label).first
    box.fill(str(value))
    box.press("Enter")


def fill_ticket(page, text, ctx, a):
    area = page.get_by_role("textbox", name=a.label_description, exact=True).first
    area.fill(text)
    area.press("Control+Enter")
    idle(page, a.timeout)
    set_select(page, a.label_criticality, ctx["asset_criticality"])
    set_number(page, a.label_hours, ctx["hours_since_agent"])
    set_number(page, a.label_endpoints, ctx["affected_endpoints"])
    idle(page, a.timeout)


def run_analysis(page, text, ctx, a):
    page.goto(a.url, wait_until="networkidle")
    fill_ticket(page, text, ctx, a)
    wizard = page.get_by_role("heading", name="Ticket Lab / Ticket Entry", exact=True).count() > 0
    if wizard:
        next_step(page, "Initial Analysis", a)
    btn(page, a.btn_run).click()
    idle(page, a.timeout)
    if wizard:
        next_step(page, "Initial Findings", a)
    else:
        tab(page, a.tab_first_result).wait_for(timeout=a.timeout)
    return wizard


def next_step(page, heading, a):
    page.get_by_role("button", name="Next", exact=True).click()
    page.get_by_role("heading", name=heading, exact=True).wait_for(timeout=a.timeout)


def tab_text(page, name):
    t = tab(page, name)
    if t.get_attribute("aria-selected") != "true":
        t.click()
        page.wait_for_timeout(400)
    return "\n".join(page.locator('[role="tabpanel"]:visible').all_inner_texts())


def ticket_response(page, text, ctx, a):
    if not run_analysis(page, text, ctx, a):
        return "\n\n".join(f"=== {t} ===\n{tab_text(page, t)}" for t in a.tabs)
    main = page.get_by_test_id("stMainBlockContainer")
    findings = main.inner_text()
    wizard_sections = {name: findings for name in ("overview", "indicators", "initial findings")}
    ai = main.locator(".st-key-initial-ai-findings")
    if ai.count():
        wizard_sections["gemini ai"] = ai.inner_text()
    if any(name.lower() in {"report", "final report"} for name in a.tabs):
        next_step(page, "Evidence Investigation", a)
        next_step(page, "Final Report", a)
        page.get_by_text("Full report preview", exact=True).click()
        wizard_sections["report"] = wizard_sections["final report"] = main.inner_text()
    return "\n\n".join(f"=== {name} ===\n{wizard_sections.get(name.lower(), findings)}" for name in a.tabs)


def evidence_response(page, text, ctx, image, a):
    if run_analysis(page, text, ctx, a):
        next_step(page, "Evidence Investigation", a)
        page.locator('input[type="file"]').first.set_input_files(str(image))
        box = page.get_by_role("checkbox", name=re.compile(a.consent_text, re.I)).first
        expect(box).to_be_enabled(timeout=a.timeout)
        if not box.is_checked():
            page.get_by_text(re.compile(a.consent_text, re.I)).first.click()
        btn(page, a.btn_evidence).click()
        idle(page, a.timeout)
        page.get_by_role("heading", name="Evidence reassessment", exact=True).wait_for(timeout=a.timeout)
        next_step(page, "Final Report", a)
        return page.locator(".st-key-evidence-assessment").inner_text()
    before = tab_text(page, a.tab_guided)
    btn(page, a.btn_validate).click()
    idle(page, a.timeout)
    page.locator('input[type="file"]').first.set_input_files(str(image))
    page.wait_for_timeout(800)
    page.get_by_text(re.compile(a.consent_text, re.I)).first.click()
    btn(page, a.btn_evidence).click()
    idle(page, a.timeout)
    after = tab_text(page, a.tab_guided)
    seen = set(before.splitlines())
    return "\n".join(line for line in after.splitlines() if line not in seen)


def main():
    p = argparse.ArgumentParser(description="Drive a Streamlit app with a ticket_lab run")
    p.add_argument("run")
    p.add_argument("--url", default="http://localhost:8501")
    p.add_argument("--headed", action="store_true", help="show the browser (great for a live demo)")
    p.add_argument("--slow-mo", type=int, default=0, help="ms between actions, e.g. 250")
    p.add_argument("--timeout", type=int, default=180000, help="ms to wait for the analysis")
    p.add_argument("--delay", type=float, default=2.0, help="seconds between tickets (rate limits)")
    p.add_argument("--tickets", help="comma-separated ticket IDs (default: all)")
    p.add_argument("--evidence", action="store_true", help="submit selected fictional screenshots to the app's model")
    p.add_argument("--variants", help="evidence variants to send (default: all in evidence_key.json)")
    p.add_argument("--tabs", default="Gemini AI,Report", help="result tabs saved as the response")
    p.add_argument("--tab-first-result", default="Gemini")
    p.add_argument("--tab-guided", default="Guided Investigation")
    p.add_argument("--label-description", default="Incident description")
    p.add_argument("--label-criticality", default="Asset criticality")
    p.add_argument("--label-hours", default="Hours since agent communication")
    p.add_argument("--label-endpoints", default="Affected endpoints")
    p.add_argument("--btn-run", default="run full (?:initial|incident) analysis")
    p.add_argument("--btn-validate", default="validate ticket request")
    p.add_argument("--btn-evidence", default="analyze evidence")
    p.add_argument("--consent-text", default="I have reviewed")
    a = p.parse_args()
    a.tabs = [t.strip() for t in a.tabs.split(",")]

    run = Path(a.run)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    contexts = {
        item["id"]: {field: item["context"][field] for field in (
            "asset_criticality", "hours_since_agent", "affected_endpoints",
        )}
        for item in manifest["tickets"]
    }
    only = {t.strip() for t in a.tickets.split(",")} if a.tickets else None

    jobs = []
    if a.evidence:
        ek = json.loads((run / "evidence_key.json").read_text(encoding="utf-8"))
        want = {v.strip() for v in a.variants.split(",")} if a.variants else None
        for stem, e in ek.items():
            if (only is None or e["ticket"] in only) and (want is None or e["variant"] in want):
                jobs.append((stem, e["ticket"], run / "evidence" / e["file"]))
        (run / "evidence_responses").mkdir(exist_ok=True)
        print(f"{len(jobs)} evidence tests to drive")
    else:
        for tid in contexts:
            if only is None or tid in only:
                jobs.append((tid, tid, None))
        print(f"{len(jobs)} tickets to drive")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not a.headed, slow_mo=a.slow_mo)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.set_default_timeout(30000)
        for name, tid, image in jobs:
            text = (run / "tickets" / f"{tid}.txt").read_text(encoding="utf-8")
            ctx = contexts[tid]
            out = run / ("evidence_responses" if image else "responses") / f"{name}.txt"
            t0 = time.time()
            try:
                resp = evidence_response(page, text, ctx, image, a) if image else ticket_response(page, text, ctx, a)
                out.write_text(resp, encoding="utf-8")
                print(f"ok     {name}  ({time.time() - t0:.0f}s, {len(resp)} chars)")
            except Exception as ex:
                shot = run / f"debug_{name}.png"
                try:
                    page.screenshot(path=str(shot), full_page=True)
                except Exception:
                    pass
                out.write_text(f"[driver error] {type(ex).__name__}: {str(ex)[:300]}", encoding="utf-8")
                print(f"FAILED {name}: {type(ex).__name__} (see {shot.name})")
            time.sleep(a.delay)
        browser.close()
    print(f"Done. Next: python ticket_lab.py report {run}")


if __name__ == "__main__":
    main()
