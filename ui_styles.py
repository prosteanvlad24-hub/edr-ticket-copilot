"""Design tokens, native Streamlit theme, and shared layout styles."""

import base64
import json
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import quote

SANS = "IBM Plex Sans"
MONO = "IBM Plex Mono"
SANS_STACK = f"{SANS}, system-ui, Segoe UI, sans-serif"
MONO_STACK = f"{MONO}, ui-monospace, Consolas, monospace"

ASSETS = Path(__file__).resolve().parent / "assets"
FAVICON = ASSETS / "favicon.png"
BRAND_IMAGE = ASSETS / "chess-knight-sidebar.png"
COLORS = {
    "canvas": "#081223",
    "sidebar": "#091528",
    "surface": "#101F34",
    "raised": "#152842",
    "border": "#304C6C",
    "text": "#EDF4FF",
    "muted": "#B6C7DD",
    "blue": "#2861AB",
    "accent": "#83D9EF",
    "violet": "#7871E6",
    "success": "#7BE1B9",
    "warning": "#F0C780",
    "danger": "#F4A7B0",
}
SIZE = {"base": 15, "h1": "24px", "h2": "17px", "h3": "16px", "meta": "13px", "code": "13px"}
WEIGHT = {"body": 400, "medium": 500, "strong": 600}
RADIUS = ".76rem"
SPACING = {"compact": ".5rem", "small": ".75rem", "normal": "1rem", "large": "1.5rem"}
FONT_RANGES = {
    "latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
    "latin-ext": "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF",
}


def theme_config() -> str:
    """Render the startup configuration without writing to disk on app reruns."""
    options = {
        "base": "dark",
        "primaryColor": COLORS["blue"],
        "backgroundColor": COLORS["canvas"],
        "secondaryBackgroundColor": COLORS["surface"],
        "textColor": COLORS["text"],
        "linkColor": COLORS["accent"],
        "borderColor": COLORS["border"],
        "codeBackgroundColor": COLORS["sidebar"],
        "font": SANS_STACK,
        "headingFont": SANS_STACK,
        "codeFont": MONO_STACK,
        "baseFontSize": SIZE["base"],
        "baseFontWeight": WEIGHT["body"],
        "headingFontSizes": [SIZE["h1"], SIZE["h2"], SIZE["h3"]],
        "headingFontWeights": [WEIGHT["strong"]] * 3,
        "codeFontSize": SIZE["code"],
        "baseRadius": RADIUS,
        "buttonRadius": RADIUS,
        "showWidgetBorder": True,
    }

    def entries(values):
        return [f"{key} = {json.dumps(value)}" for key, value in values.items()]

    lines = [
        "# Generated from ui_styles.py. Run python ui_styles.py to refresh.",
        "[server]", 'address = "127.0.0.1"', "enableStaticServing = true", "", "[theme]", *entries(options),
        "", "[theme.sidebar]", *entries({
            "backgroundColor": COLORS["sidebar"], "secondaryBackgroundColor": COLORS["raised"],
        }),
    ]
    for family, filename, weight in (
        (SANS, "ibm-plex-sans-{}-wght-normal.woff2", "100 700"),
        (MONO, "ibm-plex-mono-{}-400-normal.woff2", "400"),
    ):
        for subset, unicode_range in FONT_RANGES.items():
            lines.extend(["", "[[theme.fontFaces]]", *entries({
                "family": family,
                "url": "app/static/fonts/" + filename.format(subset),
                "style": "normal",
                "weight": weight,
                "unicodeRange": unicode_range,
            })])
    return "\n".join(lines) + "\n"


ICONS = {
    "layers": '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
    "server": '<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01M12 7.5h5m-5 9h5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
    "display": '<rect x="3" y="4" width="18" height="13" rx="1.5"/><path d="M12 17v4m-4 0h8"/>',
    "radar": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><path d="M12 12l7-7m-7-3v2m0 16v2M2 12h2m16 0h2"/>',
    "checklist": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 8h8m-8 5 2 2 5-5"/>',
    "spark": '<path d="M12 2c1 6 4 9 10 10-6 1-9 4-10 10-1-6-4-9-10-10 6-1 9-4 10-10Z"/>',
    "file": '<path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10l-7-7Z"/><path d="M13 3v7h7M8 14h8m-8 3h5"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
}


def icon(name):
    paths = ICONS.get(name)
    if not paths:
        return ""
    return (
        '<svg class="edr-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true" focusable="false">{paths}</svg>'
    )


@lru_cache(maxsize=1)
def _atmosphere():
    svg = (ASSETS / "technical-field.svg").read_text(encoding="utf-8")
    return "data:image/svg+xml," + quote(svg, safe="")


@lru_cache(maxsize=1)
def _brand_source():
    if not BRAND_IMAGE.is_file():
        return ""
    return "data:image/png;base64," + base64.b64encode(BRAND_IMAGE.read_bytes()).decode("ascii")


INTERFACE_CSS = r"""
.stApp {
    background-color: var(--edr-canvas);
    background-image: var(--edr-field),
        radial-gradient(ellipse at 93% 4%, #2d40714f 0, transparent 40%),
        radial-gradient(ellipse at 35% 46%, #15385a2d 0, transparent 66%),
        linear-gradient(155deg, #0b172a, var(--edr-canvas) 68%);
    background-size: min(49vw, 690px) auto, auto, auto, auto;
    background-position: right top, center, center, center;
    background-repeat: no-repeat;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] {
    max-width: 1540px;
    padding: 3.2rem clamp(1.25rem, 3vw, 3.35rem) 2.15rem;
}
[data-testid="stSidebar"] {
    background:
        radial-gradient(ellipse at 35% 2%, #1c426951, transparent 35%),
        radial-gradient(ellipse at 46% 99%, #39316e4b, transparent 43%),
        linear-gradient(180deg, #0a192d, var(--edr-sidebar) 63%);
    border-right: 1px solid var(--edr-border);
}
[data-testid="stSidebarUserContent"] { padding-top: 1.35rem; }
.stAppDeployButton { display: none; }
.edr-icon { width: 1.42rem; height: 1.42rem; flex: none; }

.edr-brand {
    display: grid; grid-template-columns: auto minmax(0, 1fr);
    align-items: center; gap: .4rem; padding: .16rem 0 1.05rem;
}
.edr-brand img {
    width: 4.35rem; height: 4.35rem; object-fit: contain; border-radius: .72rem;
}
.edr-brand-name {
    color: var(--edr-text); font-size: 1.23rem; font-weight: var(--edr-strong);
    line-height: 1.16; letter-spacing: -.022em;
}
.edr-brand-caption { margin-top: .38rem; color: var(--edr-muted); font-size: var(--edr-meta); }
.st-key-edr_operations button {
    min-height: 2.75rem;
    justify-content: flex-start;
    text-align: left;
    font-weight: var(--edr-strong);
}
.st-key-edr_operations button:focus-visible {
    outline: 2px solid var(--edr-accent);
    outline-offset: 2px;
}
.st-key-edr_active_case, .st-key-edr_system_status {
    background-color: #10223a;
    border-color: var(--edr-border);
    border-radius: var(--edr-radius);
}
.edr-pill {
    display: inline-flex; align-items: center; gap: .28rem;
    border: 1px solid #49729a; border-radius: 999px; padding: .16rem .52rem;
    background: #122d49; color: #d6edfc; font-size: .8rem;
    font-weight: var(--edr-medium); line-height: 1.32; overflow-wrap: anywhere;
}

.edr-case-meta {
    display: flex; flex-wrap: wrap; gap: .52rem; align-items: center;
    color: var(--edr-muted); font-size: var(--edr-meta); margin: 0;
}
.edr-case-id { font-family: var(--edr-mono); }
.st-key-stage-heading { margin-bottom: .4rem; }
/* Keep each header element's full height in the Streamlit layout. */
.st-key-stage-heading [data-testid="stMarkdownContainer"] { margin-block: 0; }
.st-key-stage-heading > [data-testid="stElementContainer"]:has(.edr-case-meta) { margin-bottom: 7px; }
.st-key-stage-heading > [data-testid="stElementContainer"]:has(.edr-stage-caption) { margin-top: 5px; }
.st-key-stage-heading h1 {
    font-size: 20px; line-height: 1.25; font-weight: var(--edr-strong);
    margin: 0; padding: 0;
}
.edr-stage-caption {
    color: var(--edr-muted); font-size: 14px; line-height: 1.45;
    margin: 0; max-width: 84ch;
}
h1, h2, h3 { letter-spacing: -.022em; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
    color: var(--edr-muted) !important; font-size: var(--edr-meta);
}
[data-testid="stMarkdownContainer"] p { line-height: 1.62; overflow-wrap: anywhere; }
.st-key-initial-ai-findings [data-testid="stMarkdownContainer"],
.st-key-report-copy [data-testid="stMarkdownContainer"],
.st-key-full-report-copy [data-testid="stMarkdownContainer"],
.st-key-evidence-assessment [data-testid="stMarkdownContainer"] {
    font-size: 15px; line-height: 1.6;
}
.st-key-initial-ai-findings [data-testid="stMarkdownContainer"] :is(p, ul, ol),
.st-key-report-copy [data-testid="stMarkdownContainer"] :is(p, ul, ol),
.st-key-full-report-copy [data-testid="stMarkdownContainer"] :is(p, ul, ol),
.st-key-evidence-assessment [data-testid="stMarkdownContainer"] :is(p, ul, ol) {
    font-size: 15px; max-width: 124ch;
}
.st-key-full-report-copy [data-testid="stMarkdownContainer"] h1 {
    font-size: 20px; line-height: 1.3;
}
[data-testid="stTextArea"] textarea { font-size: 1rem; line-height: 1.63; }
[data-testid="stVerticalBlockBorderWrapper"] { min-width: 0; }
[data-testid="stExpander"] details {
    background: linear-gradient(120deg, #10223a, #0c192d);
    border-color: #304c6c;
}
[data-testid="stExpander"] summary { padding-block: .47rem; }
[data-testid="stExpander"] summary p { font-weight: var(--edr-medium); }

.edr-progress {
    list-style: none; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr));
    padding: 0 !important; margin: 0 0 1.18rem !important; border-bottom: 1px solid #2a4665;
    padding-bottom: 1.12rem !important;
}
.edr-progress li {
    position: relative; min-width: 0; margin: 0 !important;
    display: flex; flex-direction: column; align-items: center; gap: .52rem;
    color: var(--edr-muted); font-size: var(--edr-meta); line-height: 1.25;
}
.edr-progress li:not(:last-child)::after {
    content: ""; height: 2px; position: absolute; top: 1rem; z-index: 0;
    left: calc(50% + 1.46rem); right: calc(-50% + 1.46rem);
    background: #3a5675;
}
.edr-progress li[data-state="complete"]:not(:last-child)::after {
    background: linear-gradient(90deg, #6ad6ec, #3f7cba);
}
.edr-progress [aria-current="step"] { color: var(--edr-text); font-weight: var(--edr-strong); }
.edr-progress-number {
    display: grid; place-items: center; position: relative; z-index: 1;
    min-width: 2.05rem; height: 2.05rem; border-radius: 50%;
    border: 1px solid #597795; background: #0e1d33; color: #c2d4e8;
    font-size: .83rem; font-variant-numeric: tabular-nums;
}
.edr-progress-number .edr-icon { width: 1.05rem; height: 1.05rem; }
.edr-progress [data-state="complete"] .edr-progress-number {
    color: var(--edr-accent); border-color: #4d9ec1; background: #102c47;
}
.edr-progress [aria-current="step"] .edr-progress-number {
    background: #113354; color: #c8f5ff; border-color: #81d8ef;
    box-shadow: 0 0 0 3px #55c1ea26, 0 0 14px #3bb9ee25;
}
.edr-progress-label { text-align: center; padding-inline: .3rem; }
.edr-sr-only {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip-path: inset(50%); white-space: nowrap;
}

.edr-metrics {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
    gap: var(--edr-space-small); margin: 0 !important;
}
.edr-metric {
    position: relative; min-width: 0;
    --card-padding: clamp(.78rem, 1.3vw, 1.12rem);
    padding: var(--card-padding);
    border: 1px solid #385777; border-radius: var(--edr-radius);
    background: linear-gradient(135deg, #162c47, #10203a 88%);
    box-shadow: 0 9px 22px #02081325, inset 0 1px 0 #e1f2ff0b;
}
.edr-metric[data-icon="true"] { padding-inline-start: calc(var(--card-padding) + 3.15rem); }
.edr-metric-icon {
    position: absolute; inset: var(--card-padding) auto auto var(--card-padding);
    display: flex; align-items: center; justify-content: center;
    width: 2.38rem; height: 2.38rem; border-radius: .62rem;
    background: linear-gradient(155deg, #1b3b5f, #252f60); color: var(--edr-accent);
    border: 1px solid #47648980;
}
.edr-metric dt { font-size: .93rem; line-height: 1.3; color: var(--edr-muted); }
.edr-metric dd {
    display: flex; align-items: center; gap: .36rem;
    margin: .36rem 0 0 !important; font-size: 1.3rem; font-weight: var(--edr-strong);
    line-height: 1.23; overflow-wrap: anywhere;
}
.edr-metric dd .edr-icon { width: 1.02rem; height: 1.02rem; }
.edr-metric dd[data-tone="success"] { color: var(--edr-success); }
.edr-metric dd[data-tone="warning"] { color: var(--edr-warning); }
.edr-metric dd[data-tone="danger"] { color: var(--edr-danger); }
.edr-metric dd[data-tone="accent"] { color: var(--edr-accent); }
.edr-metrics[data-variant="modules"] .edr-metric { min-height: 5.32rem; }
.edr-metrics[data-variant="modules"] dd { font-size: 1.08rem; }

.st-key-initial-actions { max-width: 40rem; margin-top: .84rem; }
.st-key-wizard-navigation {
    border-top: 1px solid #395678; padding-top: 1.12rem; margin-top: .8rem;
}
.st-key-wizard-navigation button, .st-key-initial-actions button { min-height: 2.68rem; }
.st-key-wizard-navigation button p, .st-key-initial-actions button p {
    font-size: .96rem; font-weight: var(--edr-strong);
}
.stApp button[kind="primary"]:enabled {
    color: #f1f7ff;
    border-color: #559dce;
    background: linear-gradient(109deg, #225cb0, #116c98);
    box-shadow: 0 3px 12px #13629336, inset 0 1px 0 #e0f9ff22;
}
.st-key-wizard-navigation button[kind="primary"]:enabled {
    background: linear-gradient(105deg, #5149a9, #2553b5 56%, #17688f);
    border-color: #7189e3;
}
.stApp button[kind="primary"]:enabled:hover { filter: brightness(1.12); }
.stApp button:focus-visible { outline: 2px solid var(--edr-accent); outline-offset: 2px; }
@media (prefers-reduced-motion: no-preference) {
    .stApp button[kind="primary"] { transition: filter .14s ease, border-color .14s ease; }
}
@media (max-width: 720px) {
    .stApp { background-size: min(88vw, 480px) auto, auto, auto, auto; }
    [data-testid="stMainBlockContainer"] { padding: 3.35rem 1rem 1.45rem; }
    .edr-progress { margin-bottom: .62rem !important; padding-bottom: .8rem !important; }
    .edr-progress li { font-size: .78rem; }
    .edr-progress-label { padding-inline: .08rem; }
    .edr-progress-number { min-width: 1.86rem; height: 1.86rem; }
    .edr-progress li:not(:last-child)::after { top: .9rem; left: calc(50% + 1.2rem); right: calc(-50% + 1.2rem); }
    .edr-metric { --card-padding: .74rem; }
    .edr-metric[data-icon="true"] { padding-inline-start: calc(var(--card-padding) + 2.45rem); }
    .edr-metric dd { font-size: 1.12rem; }
    .edr-metric-icon { width: 1.9rem; height: 1.9rem; }
    .edr-metric-icon .edr-icon { width: 1.12rem; height: 1.12rem; }
    .edr-stage-caption { font-size: 14px; }
    .st-key-stage-heading h1 { font-size: 18px; }
}
@media (max-width: 450px) {
    .edr-progress-label {
        position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%);
    }
    .edr-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .52rem; }
    .edr-metric[data-icon="true"] { padding-inline-start: var(--card-padding); }
    .edr-metric-icon { position: static; margin-bottom: .52rem; }
    .edr-metrics[data-variant="modules"] .edr-metric { min-height: 0; }
    .edr-progress { padding-bottom: .62rem !important; }
}
"""


def apply_styles(st) -> None:
    """Apply decorations and component layout on top of the native theme."""
    colors = " ".join(f"--edr-{name}: {value};" for name, value in COLORS.items())
    spacing = " ".join(f"--edr-space-{name}: {value};" for name, value in SPACING.items())
    tokens = (
        f':root {{ {colors} {spacing} --edr-radius: {RADIUS}; --edr-meta: {SIZE["meta"]}; '
        f'--edr-medium: {WEIGHT["medium"]}; --edr-strong: {WEIGHT["strong"]}; '
        f'--edr-mono: {MONO_STACK}; --edr-field: url("{_atmosphere()}"); }}'
    )
    st.markdown("<style>" + tokens + INTERFACE_CSS + "</style>", unsafe_allow_html=True)


def render_sidebar_brand(st):
    src = _brand_source()
    emblem = f'<img src="{src}" alt="EDR Ticket Copilot chess knight emblem" width="192" height="192">' if src else ""
    st.markdown(
        f'<div class="edr-brand">{emblem}<div><div class="edr-brand-name">EDR Ticket<br>Copilot</div>'
        '<div class="edr-brand-caption">Endpoint investigation workspace</div></div></div>',
        unsafe_allow_html=True,
    )


def render_progress(st, steps: tuple[str, ...], current: int) -> None:
    items = []
    for index, name in enumerate(steps):
        complete = index < current
        state = "complete" if complete else "upcoming"
        active = ' aria-current="step"' if index == current else ""
        number = f"{index + 1:02}"
        marker = f'{icon("check")}<span class="edr-sr-only">{number} complete</span>' if complete else number
        items.append(
            f'<li data-state="{state}"{active}><span class="edr-progress-number">{marker}</span>'
            f'<span class="edr-progress-label">{escape(name)}</span></li>'
        )
    st.markdown(
        '<ol class="edr-progress" role="list" aria-label="Investigation progress">' + "".join(items) + "</ol>",
        unsafe_allow_html=True,
    )


def render_stage_heading(st, incident, title, description, step, count):
    tag = f'<span class="edr-pill edr-case-id">{escape(incident)}</span>' if incident else '<span class="edr-pill">Manual ticket</span>'
    with st.container(key="stage-heading", gap=None):
        st.markdown(f'<p class="edr-case-meta">{tag}<span>Step {step} of {count}</span></p>', unsafe_allow_html=True)
        st.title(title)
        st.markdown(f'<p class="edr-stage-caption">{escape(description)}</p>', unsafe_allow_html=True)


def render_metrics(st, cards, icons=(), variant="summary") -> None:
    items = []
    for index, (label, value, tone) in enumerate(cards):
        has_icon = index < len(icons)
        glyph = f'<span class="edr-metric-icon">{icon(icons[index])}</span>' if has_icon else ""
        status = icon("check") if variant == "modules" and tone == "success" else ""
        items.append(
            f'<div class="edr-metric" data-icon="{str(has_icon).lower()}"><dt>{glyph}{escape(label)}</dt>'
            f'<dd data-tone="{escape(tone)}">{status}{escape(str(value))}</dd></div>'
        )
    st.markdown(f'<dl class="edr-metrics" data-variant="{escape(variant)}">' + "".join(items) + "</dl>", unsafe_allow_html=True)


if __name__ == "__main__":
    path = Path(__file__).with_name(".streamlit") / "config.toml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(theme_config(), encoding="utf-8")
