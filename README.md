# Kuku Promo Intelligence

A small Python and Streamlit tool for **Problem 1: Find the Promos** in the Kuku AI Generalist assignment.

It reads timestamped episode scripts and suggests 20–60 second promo clips. For each clip, it shows the episode, start and end time, hook, cliffhanger, and a short reason for choosing it.

## Run the app

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

In the app, upload the screenplay ZIP and choose a mode:

- **Heuristic:** Works without an API key. Useful for trying the app.
- **Gemini AI:** Enter a Gemini API key and run the AI-based evaluation. The model used for my run was `gemini-3.5-flash-lite`.

You can download the ranked CSV and the full JSON from the app.

To run it from the terminal instead:

```bash
python cli.py episodes.zip --method heuristic --output outputs/demo
python cli.py episodes.zip --method gemini --model gemini-3.5-flash-lite --ai-budget 60 --output outputs/gemini
```

For the Gemini command, set `GEMINI_API_KEY` in your terminal first.

## How it works

1. Read the scripts and extract timed dialogue and actions.
2. Find possible 20–60 second clips and use simple rules to narrow the choices.
3. Ask Gemini to judge the opening hook, cliffhanger, clarity, and pacing.
4. Rank the clips and export the results. The latest code also avoids cuts inside dialogue and filters out clips with weak hook, cliffhanger, or clarity scores.

The final score uses 35% hook, 35% cliffhanger, 20% clarity, and 10% pacing. Each AI recommendation includes evidence from the script.

## Results

My saved full-pack run produced:

| Measure | Result |
|---|---:|
| Episodes processed | 50 |
| Timed entries | 3,727 |
| Possible clips found | 6,985 |
| Clips evaluated by Gemini | 60 |
| Final recommendations | 12 |

The `kuku_raw_run.json` and `kuku_promo_shortlist.csv` files are the original saved outputs. The separately named `quality_checked` files apply the newer selection checks to those saved Gemini scores; they are not a new API run. Since Gemini judges story quality, rankings can change between runs, including the run shown in the video.

## Tests

```bash
python -m pytest -q
```

All 13 tests pass. They cover script parsing, clip timing, selection rules, and mocked AI responses.

## Limits

The tool works from screenplay timestamps, so the exact cut still needs to be checked against video. It currently picks one continuous clip at a time, and the first-pass rules may miss some good moments.
