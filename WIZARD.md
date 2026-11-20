# EDR Ticket Copilot investigation wizard

Run from the project directory so Streamlit loads the bundled theme. The wizard requires Streamlit 1.67.0 or later in the 1.x series.

```bash
python -m pip install -r requirements.txt
python -m streamlit run dashboard_v1_2.py --server.address=127.0.0.1
```

Set `GEMINI_API_KEY` in the environment or a local `.env` to enable remote analysis. Local triage, IOC extraction, Ticket Lab generation and report exports work independently. In step 2, authorize and submit ticket validation and Gemini AI analysis separately. In step 4, review the selected screenshots and authorize that submission. Each form describes what Google Gemini receives. A retry requires a fresh confirmation. **Skip evidence** produces a preliminary report.

Case data remains available while the Streamlit session is open. After returning to step 4, retained manual screenshots appear in the preview. Use **Clear uploaded screenshots** to remove them before making a new selection. Gemini results depend on the configured provider and require analyst verification. The app works with submitted case data and screenshots and has no live EDR connection.

## Changed files

| File | Role |
| --- | --- |
| `dashboard_v1_2.py` | Renders the active step, dispatches explicit analysis actions, and presents results and exports. |
| `investigation_state.py` | Stores case data separately from transient widgets and manages invalidation and evidence consent. |
| `ui_styles.py`, `.streamlit/config.toml`, `static/fonts/` | Design tokens, native Streamlit theme, responsive layout, and locally bundled IBM Plex fonts. After editing tokens, run `python ui_styles.py` and restart Streamlit. The font license files are bundled with the assets. |
| `assets/` | Exact source PNG for the chess knight emblem, scaled sidebar and favicon images, and the decorative SVG used by the CSS background. |
| `report_engine_v2.py` | Separates report availability from analyst verification and renders untrusted Markdown fields as literal code. JSON retains the original analysis data and includes the verification status. |
| `drive_streamlit.py` | Drives the current wizard and prompts the operator before each Google Gemini submission. |
| `test_ticket_lab_integration.py` | Tests navigation, case transitions, both evidence sources, consent, exports, and provider failures with Gemini simulated. |

Run the integration checks with `python -m unittest -v test_ticket_lab_integration`. The browser uploader simulation in Streamlit AppTest is available on newer Streamlit releases.

## Compact UI and INC-27517 corrections

| Modified file | Change |
| --- | --- |
| `ui_styles.py`, `.streamlit/config.toml` | 24 px desktop and 23 px narrow-screen wizard titles, 15 px report prose, and a wider reading area. |
| `dashboard_v1_2.py` | Shows the three severity values, disagreement warnings, partial hashes, and separate screenshot and ticket observations. |
| `rules_engine.py`, `severity_engine.py` | Detects distinct ransomware behaviors, shows their score contributions, and keeps source severity independent of the heuristic. Investigation priority uses the higher rated severity, and a two-level gap triggers a review warning. |
| `ioc_engine.py`, `requirements.txt` | Validates public suffixes from an offline snapshot, recognizes selected internal and test suffixes, and separates partial digests from complete hashes. |
| `ai_engine.py`, `ticket_validator.py`, `evidence_engine.py` | Passes untrusted input separately from fixed system instructions. Screenshot findings cite application-assigned IDs. Unrecognized IDs remain unattributed. |
| `evidence_inputs.py`, `investigation_state.py` | Binds consent to the selected inputs and records each screenshot source, filename, type, and SHA256 of the prepared submission. |
| `report_engine_v2.py` | Writes the severity breakdown, partial hashes, and screenshot register to Markdown. The wizard exports the same data in JSON. |
| `test_inc_27517.py`, `WIZARD.md` | Adds regression coverage and documents the release. |

The local heuristic works from reported text. A single matching behavior does not establish ransomware, and an explicit analyst-comment block is excluded from local scoring. Domain candidates are ASCII names and the suffix check does not establish reachability or maliciousness. Screenshot IDs and hashes establish which submitted image was cited. They do not authenticate the events depicted. The mocked injection tests check input separation, attribution, and the application's decision boundary. Provider output still requires analyst verification.

Run both suites with `python -m unittest -v test_inc_27517 test_ticket_lab_integration`.
