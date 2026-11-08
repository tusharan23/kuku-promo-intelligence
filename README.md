# Kuku Promo Intelligence — screenplay promo finder

**Status:** working parser + deterministic candidate generator; optional Gemini semantic evaluation.

This project discovers continuous 20–60-second promotional moments from timestamped microdrama screenplays. Python produces actual time boundaries; AI (when enabled) assesses hook, cold-viewer clarity, cliffhanger, and pacing. It does **not** create or edit video.

## Run locally (Mac / Windows / Linux)

1. Unzip this project's code into its own folder. **Keep the company's screenplay ZIP outside GitHub.**
2. In Terminal, run from the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

On Windows, use `.venv\Scripts\activate` rather than `source .venv/bin/activate`.

3. Upload the private screenplay ZIP in the sidebar. The offline baseline runs immediately.
4. Optional AI mode: obtain a Gemini API key from Google AI Studio, enter it in the sidebar, choose your available model ID, confirm the external processing notice, and click **Find promo moments**. If quota restricts the default model, select another permitted model. **ChatGPT Plus and Gemini Pro consumer subscriptions do not automatically provide API usage credits.**
5. Download `kuku_raw_run.json` and `kuku_promo_shortlist.csv` from the **Quality and export** tab.

## Headless repeatable runs

Offline baseline (no key):

```bash
python cli.py "/private/path/to/episodes.zip" --output outputs/baseline
```

With Gemini semantic ranking (external AI provider, requires API key):

```bash
export GEMINI_API_KEY="YOUR_KEY"   # only in your own terminal, never in Git
python cli.py "/private/path/to/episodes.zip" --method gemini --model gemini-3.5-flash-lite --ai-budget 60 --output outputs/gemini
```

If you want a full episode coverage on the AI stage, use an AI budget at least equal to the episode count (50 for the assignment pack). All episodes are parsed and scored offline before API shortlisting.

## How it works

1. Parse episode numbers, loglines, continuity notes, scene timing and dialogue/action/camera events.
2. Generate time-bounded candidate clips using actual event starts and ends (20–60s each). Rule-based scoring selects a manageable pool across all episodes; this stage is an imperfect **prefilter**.
3. In **Gemini AI mode**, evaluate candidate clips twice: a cold-viewer pass (no story context) checks hook and clarity; a story-editor pass (with logline/continuity) checks cliffhanger and pacing.
4. Score `0.35 * hook + 0.35 * cliffhanger + 0.20 * clarity + 0.10 * pacing` (component scores 0–5, scaled to 100), validate evidence IDs, diversify final ranking, export readable shortlist.
5. Fully traceable run data includes method, episodes, scores, evidence and diagnostic counts.

## Verified assignment run (November 2026)

A private 50-episode test pack produced the following reproducible run summary:

| Measure | Result |
|---|---:|
| Episodes parsed | 50/50 |
| Timecoded screenplay entries | 3,727 |
| Potential 20–60 second windows enumerated | 6,985 |
| Windows sent to Gemini semantic evaluation | 60 |
| Successful semantic evaluations | 60/60 |
| Episodes represented in AI evaluation | 50/50 |
| Ranked promo recommendations exported | 12 |

**Important:** Gemini evaluated 60 *prefiltered candidates*, not all 6,985 windows. These are model-generated recommendations, not proven advertising outcomes.

**Quality check:** A separate AI-assisted review of the timestamped screenplay found weak cliffhangers in some recommendations and one cut that ended during a spoken line. The project reports these as limitations; it does not claim a human video review or improved viewer retention. The private screenplay pack and raw result files are intentionally not included in this repository.

## What is and isn't proven

- Parser tests and duration validation **can** establish correct input coverage and timestamps.
- Heuristic scores are **not** an AI quality assessment. The app labels this explicitly.
- LLM scores are **model judgments**, not measured promo engagement or viewer retention.
- The script is not the actual video, so final on-screen pacing and visual execution need footage review.
- The version 1 candidate generator considers **continuous clips only**, not multi-episode stitched promos.
- The heuristic prefilter may miss unusual but compelling scenes. Evaluate failures and omissions honestly.
- Some submitted scripts have atypical capitalization or scenes with short durations; parsing is case-insensitive and events use episode-level timings.

## Safety and confidentiality

The input scripts are Kuku's confidential material. Do not publish the input pack, include it in a public repository, or deploy an app with scripts preloaded. A public demo can use a fictional example script instead. Gemini AI mode **sends screenplay excerpts to a third-party provider**; check their data-processing terms and get comfortable with the tradeoff before enabling it. Free-tier provider prompts may be used to improve their products. All scripts are read in memory by default; the `.cache` folder and `outputs` directory (which may contain source excerpts) are gitignored.

## Interview demonstration

Upload a new similarly formatted screenplay ZIP or a single episode TXT, click **Find promo moments**, inspect timestamps and source excerpts, show ranking and raw outputs, and explain one genuine failure. The AI provider/model is a replaceable function rather than mixed into parsing logic.

## Test

```bash
python -m pytest -q
```

## Package / GitHub checklist

Only commit `app.py`, `promo_core.py`, `promo_ai.py`, `cli.py`, `requirements.txt`, `.gitignore`, `README.md`, `tests/`, and `examples/fictional_demo_episode.txt`.
Keep `.venv/`, `.cache/`, unedited Kuku scripts, generated raw outputs, and review notes **out of public GitHub**. Submit the raw outputs separately using the assignment's requested sharing workflow. Never commit API keys.

**Rate limits:** Gemini mode spaces *uncached* requests (about 6 seconds between calls) and makes a bounded retry after a 429. If you still see quota errors, retain previous outputs and report the partial AI coverage. `ai_successful` is the number of candidate clips with both semantic evaluations, not the number of model requests.
