"""
db/ingest/trials.py

Extracts trial-level data and populates the trials table.
One row per trial per paradigm per session.

Sources:
  - EEG parquet   → trial number, start/end timestamps, cue, phan_frame range
  - E-Prime txt   → random_time_ms, onset_delay_ms, duration_error
  - session_alertness table → missed flag (from experimenter notes)

How trials are identified:
  The EEG parquet has a `trig` column (int16). Non-zero values are trial numbers
  (1–40 or 1–50 for P3005L). We group rows by trig value to get:
    start_ts  — first timestamp where trig == N
    end_ts    — last timestamp where trig == N
    cue       — the paradigm-specific stimulus cue (see _extract_cue())
    phan_frame_start/end — Phantom frame range for this trial

The E-Prime txt file is matched by TrialCount field, which corresponds to the
trig value in the EEG.

Run directly to ingest all trials:
    python -m db.ingest.trials
"""

from pathlib import Path
import pandas as pd
from rich.console import Console
console = Console()
from db.database import get_db, load_parquet
from db.config import DATA_ROOT, PARADIGM_MAP, IGNORE_CUES
from db.models import EEGRecording, SessionAlertness, Trial


# ---------------------------------------------------------------------------
# _extract_cue()
# ---------------------------------------------------------------------------
# Given all the cue values seen within a trial, return the one that
# identifies what the trial IS (Left/Right, frequency, target letter).
#
# ME/MI:   ['Fixation', 'Left', 'Random']           → 'Left'
# SSVEP:   ['Stimulus', 'Break', '12 Hz', 'Random'] → '12 Hz'
# P3004L:  ['Letter 2 in 2345', 'Break', 'Seq29:...', 'Random']
#                                                    → 'Letter 2 in 2345'

def _extract_cue(cue_values: list[str]) -> str:
    specific = [
        c for c in cue_values
        if c not in IGNORE_CUES and not c.startswith('Seq')
    ]
    return specific[0] if specific else ''


# ---------------------------------------------------------------------------
# _parse_eprime()
# ---------------------------------------------------------------------------
# Reads the E-Prime txt file and returns a dict:
#   { trial_count (int): { 'random_time_ms': int, 'onset_delay_ms': int,
#                          'duration_error': int } }
#
# E-Prime files are UTF-16 LE encoded. We split on LogFrame markers and
# extract key-value pairs per trial block.

def _parse_eprime(txt_path: Path) -> dict[int, dict]:
    with open(txt_path, 'rb') as f:
        text = f.read().decode('utf-16')

    result = {}
    frames = text.split('*** LogFrame Start ***')

    for frame in frames[1:]:
        end = frame.find('*** LogFrame End ***')
        block = frame[:end].strip()

        kv = {}
        for line in block.splitlines():
            line = line.strip()
            if ': ' in line:
                k, v = line.split(': ', 1)
                kv[k.strip()] = v.strip()

        trial_count = kv.get('TrialCount')
        if trial_count is None:
            continue

        try:
            tc = int(trial_count)
        except ValueError:
            continue

        result[tc] = {
            'random_time_ms': int(kv['randomTime'])           if 'randomTime'               in kv else None,
            'onset_delay_ms': int(kv['Stimulus.OnsetDelay'])  if 'Stimulus.OnsetDelay'       in kv else None,
            'duration_error': int(kv['Stimulus.DurationError']) if 'Stimulus.DurationError'  in kv else None,
        }

    return result


# ---------------------------------------------------------------------------
# _get_missed_trials()
# ---------------------------------------------------------------------------
# Parses session_alertness.missed_which text to extract a set of trial numbers.
# The field is free-text like "T in WHAT, F and O in FROM" (P300) or
# "1: middle start grasping with wrong hand" (ME/MI).
# We extract any leading integers as trial numbers.

def _get_missed_trials(missed_which: str) -> set[int]:
    if not missed_which:
        return set()
    missed = set()
    # try to extract leading trial numbers like "1: description"
    for part in missed_which.split(','):
        part = part.strip()
        token = part.split(':')[0].strip()
        try:
            # handle "~10" style entries
            num = int(token.lstrip('~'))
            missed.add(num)
        except ValueError:
            pass
    return missed


# ---------------------------------------------------------------------------
# process_session_paradigm()
# ---------------------------------------------------------------------------
# Extracts all trials for one (session, paradigm) pair.

def process_session_paradigm(
    session_id: str,
    paradigm: str,
    eeg_rec: EEGRecording,
    eprime_path: Path,
    missed_which: str,
) -> list[Trial]:

    # --- load only the columns we need from the EEG parquet ---
    df = load_parquet(
        eeg_rec.file_path,
        eeg_rec.hmac,
        columns=['timestamp_s', 'trig', 'cue', 'phan_frame'],
    )

    # --- parse E-Prime ---
    eprime = _parse_eprime(eprime_path) if eprime_path.exists() else {}

    # --- get missed trial numbers ---
    missed_set = _get_missed_trials(missed_which)

    # --- extract one Trial per unique trig value ---
    trial_rows = df[df['trig'] > 0]
    trials = []

    for trig_val, group in trial_rows.groupby('trig'):
        trial_num = int(trig_val)

        start_ts  = float(group['timestamp_s'].iloc[0])
        end_ts    = float(group['timestamp_s'].iloc[-1])
        duration  = round(end_ts - start_ts, 3)
        cue       = _extract_cue(group['cue'].unique().tolist())

        # phan_frame range — only where phan_frame != -1
        valid_frames = group['phan_frame'][group['phan_frame'] != -1]
        phan_start = int(valid_frames.iloc[0])  if len(valid_frames) else None
        phan_end   = int(valid_frames.iloc[-1]) if len(valid_frames) else None

        # E-Prime fields for this trial
        ep = eprime.get(trial_num, {})

        trial = Trial(
            id               = f"{session_id}_{paradigm}_{trial_num:03d}",
            session_id       = session_id,
            paradigm         = paradigm,
            trial_number     = trial_num,
            cue              = cue,
            start_ts         = start_ts,
            end_ts           = end_ts,
            duration_s       = duration,
            phan_frame_start = phan_start,
            phan_frame_end   = phan_end,
            random_time_ms   = ep.get('random_time_ms'),
            onset_delay_ms   = ep.get('onset_delay_ms'),
            duration_error   = ep.get('duration_error'),
            missed           = 1 if trial_num in missed_set else 0,
        )
        trials.append(trial)

    return trials


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------

def run():
    Session = get_db()

    with Session() as db:
        for subj_dir in sorted(DATA_ROOT.glob('S*')):
            subject_id = subj_dir.name
            for sess_dir in sorted(subj_dir.glob('Sess*')):
                sess_num   = int(sess_dir.name.replace('Sess', ''))
                session_id = f"{subject_id}_Sess{sess_num:02d}"

                # skip if trials already exist for this session
                existing = db.query(Trial).filter_by(session_id=session_id).count()
                if existing > 0:
                    console.print(f"  [dim]↷ {session_id} ({existing} trials already exist)[/dim]")
                    continue

                console.print(f"  [bold]{session_id}[/bold]")

                for prefix, paradigm in PARADIGM_MAP.items():
                    # find the EEG recording row
                    rec_id  = f"{session_id}_{paradigm}"
                    eeg_rec = db.get(EEGRecording, rec_id)
                    if eeg_rec is None:
                        console.print(f"    [yellow]⚠[/yellow]  {paradigm}: no EEG recording — skipping")
                        continue

                    # find the E-Prime txt file
                    eprime_dir  = sess_dir / 'E-Prime'
                    eprime_path = next(
                        (f for f in eprime_dir.glob('*.txt') if f.stem.startswith(prefix)),
                        Path('nonexistent'),
                    ) if eprime_dir.exists() else Path('nonexistent')

                    # get missed trial info from session_alertness
                    alertness = db.query(SessionAlertness).filter_by(
                        session_id=session_id, paradigm=paradigm
                    ).first()
                    missed_which = alertness.missed_which if alertness else None

                    trials = process_session_paradigm(
                        session_id, paradigm, eeg_rec, eprime_path, missed_which,
                    )

                    for trial in trials:
                        db.add(trial)

                    missed_count = sum(1 for t in trials if t.missed)
                    missed_str = f"  [yellow]{missed_count} missed[/yellow]" if missed_count else ""
                    console.print(f"    [green]✓[/green] {paradigm:<8} {len(trials):>2} trials{missed_str}")

                db.commit()

    pass


if __name__ == "__main__":
    run()
