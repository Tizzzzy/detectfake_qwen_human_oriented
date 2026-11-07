"""
Social-media text AI-vs-Human detection task.

A participant reads a short social-media text plus an explanation hint and decides
whether it was written by an **AI** or a **Human**.

Stimuli come from `inference_raw_qwen_human_oriented.json` at the repo root: a flat list of
`{text_id, label, text, text_path, explanation}` records. A record's **position in that
list** is its stable id (`stimulus_index`) -- `text_id` repeats in the file (a Reddit
original and its AI rewrite share an id, with different text and different labels), and
every one of those rows is shown as its own trial.

Each participant answers up to TRIALS_PER_USER distinct records, always served
fewest-decisions-first so coverage stays even, and no record is served more than
MAX_DECISIONS times overall. Progress is stored in the database (QwenHumanOrientedGuess, table
`qwen_human_oriented_guess`), so closing the tab and returning resumes where they left off. Users are
identified only by the `political_vsave` cookie -- no username prompt.
"""

import json
import os
import random
from collections import Counter

from flask import render_template, request, jsonify, make_response, url_for, redirect
from sqlalchemy import func as sqlfunc

from . import app, db
from .models import QwenHumanOrientedGuess
from .helpers import get_user_id, set_user_cookie, get_ip_details


# --- Configuration ---
# Number of trials each participant completes. None => the entire stimulus pool.
TRIALS_PER_USER = 50

# Stop serving a record once this many participants have judged it.
MAX_DECISIONS = 5

# Max hint bullets shown per text. None => show every bullet in the explanation.
MAX_EXPLANATION_BULLETS = None


# --- Data loading (once at import) ---

# The JSON lives at the repo root (CWD when run.py launches), with a fallback to the
# path relative to this file.
_JSON_REL = 'inference_raw_qwen_human_oriented.json'
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JSON_PATH = _JSON_REL if os.path.isfile(_JSON_REL) else os.path.join(_repo_root, _JSON_REL)


def clean_stimulus_text(raw):
    """Clean a Reddit-style text. Lines may have a leading 'N\\t' index; strip it for
    clean rendering. Preserve paragraph breaks otherwise. (Ported from detectfakesv2.)"""
    cleaned_lines = []
    for line in raw.splitlines():
        stripped = line
        if "\t" in line:
            head, _, tail = line.partition("\t")
            if head.strip().isdigit():
                stripped = tail
        cleaned_lines.append(stripped.rstrip())
    return "\n".join(cleaned_lines).strip()


def parse_explanation_bullets(raw):
    """Parse an explanation string into a list of bullet strings (sans markers and
    indentation). Capped at MAX_EXPLANATION_BULLETS when that is set."""
    bullets = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        for marker in ("- ", "• ", "* "):
            if s.startswith(marker):
                s = s[len(marker):]
                break
        bullets.append(s)
        if MAX_EXPLANATION_BULLETS is not None and len(bullets) >= MAX_EXPLANATION_BULLETS:
            break
    return bullets


def _load_stimuli():
    """Load inference_raw_qwen_human_oriented.json into a list of render-ready stimulus dicts, one per
    record. Duplicate text_ids are kept as separate stimuli and numbered by occurrence."""
    with open(_JSON_PATH, 'r', encoding='utf-8') as f:
        records = json.load(f)

    seen = Counter()
    stimuli = []
    for i, rec in enumerate(records):
        text_id = str(rec.get('text_id', ''))
        seen[text_id] += 1
        stimuli.append({
            'index': i,
            'text_id': text_id,
            'occurrence': seen[text_id],
            'label': str(rec.get('label', '')),
            'text_path': str(rec.get('text_path', '')),
            'text_body': clean_stimulus_text(str(rec.get('text', ''))),
            'hint_bullets': parse_explanation_bullets(str(rec.get('explanation', ''))),
        })
    return stimuli


STIMULI = _load_stimuli()
N_STIMULI = len(STIMULI)
_n_repeated = sum(1 for _, c in Counter(s['text_id'] for s in STIMULI).items() if c > 1)
print(f"[TEXT] Loaded {N_STIMULI} stimuli from {_JSON_PATH} "
      f"({_n_repeated} text_ids appear more than once; all rows are served)")


def total_trials():
    """How many trials a participant completes."""
    if TRIALS_PER_USER is None:
        return N_STIMULI
    return min(TRIALS_PER_USER, N_STIMULI)


def user_seed(user_id):
    """Deterministic per-user seed (user_id is normally an md5 hex string)."""
    try:
        return int(str(user_id)[:8], 16)
    except (ValueError, TypeError):
        return abs(hash(str(user_id))) % (2 ** 31)


def _completed_count(user_id):
    return QwenHumanOrientedGuess.query.filter_by(user_id=user_id).count()


def _decision_counts():
    """stimulus_index -> number of decisions recorded so far."""
    rows = (db.session.query(QwenHumanOrientedGuess.stimulus_index, sqlfunc.count(QwenHumanOrientedGuess.id))
            .group_by(QwenHumanOrientedGuess.stimulus_index).all())
    return {int(idx): int(c) for idx, c in rows}


def _answered_indices(user_id):
    rows = db.session.query(QwenHumanOrientedGuess.stimulus_index).filter_by(user_id=user_id).all()
    return {int(r[0]) for r in rows}


def eligible_candidates(user_id):
    """(count, idx) for every stimulus this user may still answer: below the cap
    (< MAX_DECISIONS) and not yet answered by this user. Empty once the user has done
    their TRIALS_PER_USER trials. Fewest-decisions-first."""
    if _completed_count(user_id) >= total_trials():
        return []
    counts = _decision_counts()
    answered = _answered_indices(user_id)
    cands = []
    for stim in STIMULI:
        idx = stim['index']
        c = counts.get(idx, 0)
        if c < MAX_DECISIONS and idx not in answered:
            cands.append((c, idx))
    cands.sort(key=lambda t: t[0])
    return cands


def pick_candidate(cands, seed):
    """Choose the eligible stimulus with the fewest decisions. Ties are broken with a
    per-user RNG so concurrent participants spread across different stimuli rather than
    all landing on the same one."""
    if not cands:
        return None
    min_c = cands[0][0]
    least = [idx for c, idx in cands if c == min_c]
    return random.Random(f"{seed}-{min_c}-{len(least)}").choice(least)


# Cookie that records a first-time visitor has read the welcome + consent page.
CONSENT_COOKIE = 'qwen_human_oriented_consent'
CONSENT_MAX_AGE = 60 * 60 * 24 * 365  # one year


@app.errorhandler(404)
def not_found(_e):
    return render_template('404.html'), 404


# --- Static informational pages (mirrors political_decision routes.py) ---

@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/informed-consent')
def informed_consent():
    return render_template('informed-consent.html')


@app.route('/instructions')
def instructions():
    return render_template('instructions.html')


@app.route('/', methods=['GET'])
def text_home():
    user_id = get_user_id()

    # First-time visitors must read the welcome + consent page before starting. We
    # remember their agreement with a cookie so they skip it when they return.
    if request.cookies.get(CONSENT_COOKIE) != '1':
        resp = make_response(render_template('welcome-text.html'))
        set_user_cookie(resp, user_id)  # preserve id until they consent
        return resp

    completed = _completed_count(user_id)
    cands = eligible_candidates(user_id)

    # Finished when the user hit their trial cap, or nothing is left to serve them
    # (every remaining stimulus is already answered by them or fully covered).
    if not cands:
        score = QwenHumanOrientedGuess.query.filter_by(user_id=user_id, correct=True).count()
        resp = make_response(render_template(
            'finish-text.html',
            n_seen=completed,
            max_stimuli=completed,
            score=score,
        ))
        set_user_cookie(resp, user_id)
        return resp

    idx = pick_candidate(cands, user_seed(user_id))
    # Progress denominator: what this user has done plus what still remains for them,
    # never more than their trial cap.
    total = min(total_trials(), completed + len(cands))
    stim = STIMULI[idx]

    resp = make_response(render_template(
        'text-version.html',
        text_body=stim['text_body'],
        hint_bullets=stim['hint_bullets'],
        current_trial=completed + 1,
        total=total,
        stimulus_index=idx,
    ))
    set_user_cookie(resp, user_id)
    return resp


@app.route('/text-consent', methods=['POST'])
def text_consent():
    """Record the welcome-page agreement and send the user into the task."""
    user_id = get_user_id()
    resp = make_response(redirect(url_for('text_home')))
    set_user_cookie(resp, user_id)
    resp.set_cookie(CONSENT_COOKIE, '1', max_age=CONSENT_MAX_AGE)
    return resp


@app.route('/text-guess', methods=['POST'])
def text_guess():
    try:
        data = request.get_json(force=True)
        guess_raw = (data.get('guess') or '').strip().lower()
        guess_map = {'human': 'Human', 'ai': 'AI'}
        if guess_raw not in guess_map:
            return jsonify({'success': False, 'error': 'Invalid guess'}), 400
        guess = guess_map[guess_raw]

        try:
            stimulus_index = int(data.get('stimulus_index'))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid stimulus_index'}), 400

        user_id = get_user_id()

        # Idempotency: if this stimulus was already answered by this user, return the
        # stored result instead of creating a duplicate.
        existing = QwenHumanOrientedGuess.query.filter_by(
            user_id=user_id, stimulus_index=stimulus_index).first()
        if existing:
            score = QwenHumanOrientedGuess.query.filter_by(user_id=user_id, correct=True).count()
            current = QwenHumanOrientedGuess.query.filter_by(user_id=user_id).count()
            done = not eligible_candidates(user_id)
            return jsonify({
                'success': True,
                'correct': bool(existing.correct),
                'truth': str(existing.label_truth),
                'score_correct': score,
                'score_total': current,
                'redirect': url_for('text_home') if done else None,
            })

        # We trust the displayed index -- it is what the participant actually judged, even
        # if concurrent answers have since nudged its decision count. Only a malformed or
        # tampered index is rejected; silently recording it against some other stimulus
        # would attribute the decision to a text the participant never saw.
        if not 0 <= stimulus_index < N_STIMULI:
            return jsonify({'success': False, 'error': 'Unknown stimulus_index'}), 400

        completed = _completed_count(user_id)
        stim = STIMULI[stimulus_index]
        truth = stim['label']
        is_correct = (guess == truth)

        ua = request.user_agent
        new_guess = QwenHumanOrientedGuess(
            user_id=user_id,
            trial_num=completed + 1,
            stimulus_index=stimulus_index,
            text_id=stim['text_id'],
            occurrence=stim['occurrence'],
            text_path=stim['text_path'],
            label_truth=truth,
            guess=guess,
            correct=is_correct,
            ip=get_ip_details(),
            user_platform=str(ua.platform),
            user_browser=str(ua.browser),
            user_version=str(ua.version),
            user_language=str(ua.language),
        )
        db.session.add(new_guess)
        db.session.commit()

        score = QwenHumanOrientedGuess.query.filter_by(user_id=user_id, correct=True).count()
        current = completed + 1
        done = not eligible_candidates(user_id)
        redirect_url = url_for('text_home') if done else None

        return jsonify({
            'success': True,
            'correct': is_correct,
            'truth': truth,
            'score_correct': score,
            'score_total': current,
            'redirect': redirect_url,
        })
    except Exception:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Server error'}), 500
