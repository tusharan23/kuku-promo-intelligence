"""Deterministic screenplay parsing and promo-candidate discovery.

No model is needed to parse scripts, choose exact cut points, or check clip lengths.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from collections import defaultdict
from pathlib import Path
import io
import json
import re
import zipfile

SCENE_RE = re.compile(r"(?im)^SCENE\s+(\d+)\s*$")
TAG_RE = re.compile(r"(?m)^\*\*(.+?):\*\*\s*$")
TIMING_RE = re.compile(r"(?im)^Start:\s*\((\d{2}:\d{2}(?:\.\d+)?)\)\s*\|\s*End:\s*\((\d{2}:\d{2}(?:\.\d+)?)\)\s*$")
META_RE = re.compile(r"(?im)^(EPISODE NUMBER|EPISODE LOGLINE|CONTINUITY NOTES):\s*(.*)$")
SCENE_INFO_RE = re.compile(r"(?im)^Scene\s+(heading|start|end):\s*(.*)$")

# Text-only fallback: consciously coarse, not a substitute for semantic model ranking.
HOOK_TERMS = (
    "never", "cannot", "won't", "don't", "secret", "betray", "marry", "kill",
    "dead", "blood", "poison", "pregnant", "father", "mother", "daughter",
    "husband", "wife", "duke", "divorce", "thief", "liar", "love", "hate",
    "stop", "wait", "leave", "you dare", "how could", "who are", "why", "what",
    "no!", "help", "truth", "shocked", "slap", "gasp", "scream", "reveal",
    "grab", "knife", "gun", "cry", "accuse", "discovered", "confess",
)
CLIFF_TERMS = (
    "?", "who", "why", "how", "what", "will", "or else", "but", "unless",
    "reveal", "secret", "suddenly", "stunned", "horrif", "shocked", "gasp",
    "freeze", "cut to black", "about to", "before", "interrupt", "unknown",
    "trembl", "arriv", "enters", "witness", "discovered", "truth", "shout",
)
RESOLUTION_TERMS = ("fade to black", "fade out", "gentle music", "relief", "peaceful", "resolv", "warmly", "final beat")


def sec(timestamp: str) -> float:
    mm, ss = timestamp.split(":", 1)
    return round(int(mm) * 60 + float(ss), 2)


def stamp(value: float) -> str:
    m, s = divmod(round(max(0.0, value), 2), 60)
    return f"{int(m):02d}:{s:05.2f}"


@dataclass(frozen=True)
class Event:
    id: str
    scene: int
    kind: str
    speaker: str
    start: float
    end: float
    text: str

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Episode:
    number: int
    title: str
    logline: str
    continuity: str
    duration: float
    scenes: list[dict]
    events: list[Event]
    filename: str

    def to_json(self, include_events: bool = False) -> dict:
        data = {"number": self.number, "title": self.title, "logline": self.logline,
                "continuity": self.continuity, "duration_seconds": self.duration,
                "scenes": self.scenes, "event_count": len(self.events), "filename": self.filename}
        if include_events:
            data["events"] = [e.to_json() for e in self.events]
        return data


def parse_script(script: str, filename: str = "episode.txt") -> Episode:
    metadata = {k.upper(): v.strip() for k, v in META_RE.findall(script)}
    match = re.search(r"\bEpisode\s+(\d+)\b", metadata.get("EPISODE NUMBER", ""), re.I)
    if not match:
        match = re.search(r"episode[-_ ]0*(\d+)", filename, re.I)
    if not match:
        raise ValueError(f"Cannot determine episode number: {filename}")
    number = int(match.group(1))

    scene_matches = list(SCENE_RE.finditer(script))
    if not scene_matches:
        raise ValueError(f"No scene headers in {filename}")
    scenes = []
    events = []
    for idx, m in enumerate(scene_matches):
        scene_no = int(m.group(1))
        section = script[m.end():scene_matches[idx + 1].start() if idx + 1 < len(scene_matches) else len(script)]
        info = {k.lower(): v.strip() for k, v in SCENE_INFO_RE.findall(section)}
        scene_start = sec(info['start']) if 'start' in info else 0.0
        scene_end = sec(info['end']) if 'end' in info else 0.0
        scenes.append({"number": scene_no, "heading": info.get("heading", ""),
                       "start": scene_start, "end": scene_end})

        tags = list(TAG_RE.finditer(section))
        for j, tag in enumerate(tags):
            segment = section[tag.end():tags[j+1].start() if j+1 < len(tags) else len(section)]
            timed = TIMING_RE.search(segment)
            if not timed:
                continue
            start, end = sec(timed.group(1)), sec(timed.group(2))
            if end <= start:
                continue
            text = segment[timed.end():].split("--- SCRIPT END ---")[0].strip()
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            label = tag.group(1).strip()
            kind = label.upper() if label.upper() in ("CAMERA", "ACTION", "SOUND FX", "SFX", "MUSIC") else "DIALOGUE"
            speaker = label if kind == "DIALOGUE" else ""
            events.append(Event(id=f"E{number:03d}-{len(events):04d}", scene=scene_no,
                                kind=kind, speaker=speaker, start=start, end=end, text=text))

    if not events:
        raise ValueError(f"No timed entries found in {filename}")
    duration = max(max(e.end for e in events), max((s["end"] for s in scenes), default=0))
    return Episode(number=number, title=metadata.get('EPISODE NUMBER', f'Episode {number}'),
                   logline=metadata.get("EPISODE LOGLINE", ""),
                   continuity=metadata.get("CONTINUITY NOTES", ""),
                   duration=duration, scenes=scenes, events=sorted(events, key=lambda e: (e.start, e.end)),
                   filename=filename)


def read_episodes(source: bytes | str | Path, name: str = "") -> list[Episode]:
    """Read an uploaded ZIP, a local ZIP, or a folder. Does not extract the ZIP."""
    if isinstance(source, bytes):
        zf = zipfile.ZipFile(io.BytesIO(source))
    else:
        path = Path(source)
        if path.is_dir():
            files = sorted(path.rglob("*.txt"))
            episodes = [parse_script(p.read_text(encoding="utf-8-sig"), str(p.name)) for p in files]
            return _verify_episodes(episodes)
        if path.suffix.lower() == '.txt':
            return [parse_script(path.read_text(encoding='utf-8-sig'), path.name)]
        zf = zipfile.ZipFile(path)
    with zf:
        texts = []
        for info in zf.infolist():
            # ZIP filenames from unknown users are not trusted; only read their bytes.
            if info.is_dir() or not info.filename.lower().endswith('.txt'):
                continue
            if info.file_size > 3_000_000:
                raise ValueError(f"Script too large: {info.filename}")
            texts.append((info.filename, zf.read(info).decode('utf-8-sig')))
    return _verify_episodes([parse_script(content, n) for n, content in texts])


def _verify_episodes(episodes: list[Episode]) -> list[Episode]:
    if not episodes:
        raise ValueError("No screenplay .txt files found")
    numbers = [e.number for e in episodes]
    if len(numbers) != len(set(numbers)):
        raise ValueError("Duplicate episode numbers found")
    return sorted(episodes, key=lambda ep: ep.number)


def _score(evs: list[Event], start: float, end: float) -> tuple[float, dict]:
    """Heuristic prefilter only; its score is not evidence of audience appeal."""
    spoken = [e for e in evs if e.kind in ("DIALOGUE", "ACTION")]
    opening = [e for e in spoken if e.start < start + 3.0 and e.end > start]
    closing = [e for e in spoken if e.end > end - 7 and e.start < end]
    middle = [e for e in spoken if e.start < end and e.end > start]
    opening_text = ' '.join(e.text for e in opening).lower()
    closing_text = ' '.join(e.text for e in closing).lower()
    whole_text = ' '.join(e.text for e in middle).lower()
    hook_term = sum(1 for word in HOOK_TERMS if word in opening_text)
    cliff_term = sum(1 for word in CLIFF_TERMS if word in closing_text)
    if not middle:
        return -100, {}
    hook = min(1, 0.18 + 0.19 * hook_term + 0.14 * bool(opening))
    cliff = min(1, 0.10 + 0.18 * cliff_term + 0.10 * bool(closing))
    if any(r in closing_text for r in RESOLUTION_TERMS):
        cliff *= 0.6
    dia_count = sum(e.kind == 'DIALOGUE' for e in middle)
    action_count = sum(e.kind == 'ACTION' for e in middle)
    clarity = max(.25, 0.8 - 0.04 * max(0, len(set(e.speaker for e in middle if e.speaker)) - 3))
    pacing = min(1., 0.16 + 0.10 * min(dia_count, 6) + 0.045 * min(action_count, 5))
    score = 100 * (0.35 * hook + 0.35 * cliff + 0.20 * clarity + 0.10 * pacing)
    return round(score, 2), {"prefilter_hook": round(hook*5, 1),
                              "prefilter_cliffhanger": round(cliff*5, 1),
                              "dialogue_events": dia_count, "action_events": action_count,
                              "initial_evidence_id": opening[0].id if opening else '',
                              "ending_evidence_id": closing[-1].id if closing else ''}


def candidate_text(events: list[Event], start: float, end: float, max_chars: int = 7000) -> str:
    lines = []
    for e in events:
        if e.end <= start or e.start >= end or e.kind not in ("DIALOGUE", "ACTION", "SOUND FX"):
            continue
        who = (e.speaker + ': ') if e.speaker else (e.kind + ': ')
        lines.append(f"[{stamp(e.start)}–{stamp(e.end)}] {who}{e.text}")
    return '\n'.join(lines)[:max_chars]


def generate_candidates(episodes: list[Episode], per_episode: int = 4) -> tuple[list[dict], dict]:
    """Covers all episodes, keeps strongest nonduplicate windows per episode."""
    all_candidates = []
    diagnostics = {"total_generated": 0, "episodes_processed": len(episodes), "per_episode_generated": {}}
    for ep in episodes:
        spoken = [e for e in ep.events if e.kind in ('DIALOGUE', 'ACTION')]
        opens = sorted(set([0.0] + [e.start for e in spoken]))
        ends = sorted(set([ep.duration] + [e.end for e in ep.events if e.kind in ('DIALOGUE', 'ACTION', 'CAMERA')]))
        rows = []
        seen = set()
        for start in opens:
            if ep.duration-start < 20:
                continue
            for target in (25, 33, 42, 50, 59):
                desired = start + target
                valid = [t for t in ends if 20 <= t-start <= 60]
                if not valid:
                    continue
                end = min(valid, key=lambda t: abs(t-desired))
                key = (start, end)
                if key in seen:
                    continue
                seen.add(key)
                score, diag = _score(ep.events, start, end)
                if score < 0:
                    continue
                # Only timed entries from the selected interval appear in evidence.
                first = next((e for e in ep.events if e.id == diag['initial_evidence_id']), None)
                last = next((e for e in ep.events if e.id == diag['ending_evidence_id']), None)
                rows.append({"id": f"EP{ep.number:03d}-{int(round(start*100)):05d}-{int(round(end*100)):05d}",
                             "episode": ep.number, "start_seconds": start, "end_seconds": end,
                             "start": stamp(start), "end": stamp(end), "duration_seconds": round(end-start, 2),
                             "heuristic_score": score, "score": score, "method": "HEURISTIC_ONLY",
                             "hook_evidence": first.text if first else '', "cliffhanger_evidence": last.text if last else '',
                             "hook_evidence_id": first.id if first else '', "cliffhanger_evidence_id": last.id if last else '',
                             "explanation": "Candidate selected by rule-based filtering; semantic quality not yet checked.",
                             "promo_angle": "unclassified", "diagnostics": diag})
        diagnostics["per_episode_generated"][str(ep.number)] = len(rows)
        diagnostics["total_generated"] += len(rows)
        rows.sort(key=lambda c: (-c['heuristic_score'], c['start_seconds']))
        kept = []
        for c in rows:
            if any(overlap_ratio(c, old) > .50 for old in kept):
                continue
            kept.append(c)
            if len(kept) >= per_episode:
                break
        all_candidates.extend(kept)
    all_candidates.sort(key=lambda c: (-c['score'], c['episode']))
    return all_candidates, diagnostics


def overlap_ratio(a: dict, b: dict) -> float:
    if a['episode'] != b['episode']:
        return 0.0
    intersection = max(0, min(a['end_seconds'], b['end_seconds']) - max(a['start_seconds'], b['start_seconds']))
    union = max(a['end_seconds'], b['end_seconds']) - min(a['start_seconds'], b['start_seconds'])
    return intersection / union if union else 0.0


def shortlist(candidates: list[dict], count: int = 12, max_per_episode: int = 2) -> list[dict]:
    selected = []
    epcounts = defaultdict(int)
    for c in sorted(candidates, key=lambda r: (-r['score'], -r.get('heuristic_score',0))):
        if epcounts[c['episode']] >= max_per_episode:
            continue
        if any(overlap_ratio(c, x) > .35 for x in selected):
            continue
        selected.append(dict(c))
        epcounts[c['episode']] += 1
        if len(selected) >= count:
            break
    for ix, c in enumerate(selected, 1):
        c['rank'] = ix
    return selected


def export_result(episodes: list[Episode], candidates: list[dict], final: list[dict], diagnostics: dict,
                  method: str) -> dict:
    return {"show": "Uploaded screenplays", "method": method,
            "warning": ("Heuristic baseline only: not AI-evaluated" if method == "HEURISTIC_ONLY" else
                        "AI evaluated script text; actual footage still requires verification"),
            "episode_count": len(episodes), "scripted_duration_seconds": round(sum(e.duration for e in episodes), 2),
            "entry_count": sum(len(e.events) for e in episodes),
            "episodes": [e.to_json() for e in episodes],
            "diagnostics": diagnostics, "evaluated_candidates": candidates, "ranked_promos": final}
