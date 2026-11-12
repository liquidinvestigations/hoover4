#!/usr/bin/env python3
"""The backup schedule of a site: eligibility, the weekly limit, future slots, retention and the destination checks.

This module holds the rules only. It reads no cluster and runs no copy, so the backup suite tests it with controlled
time (../../tests/test_backup.py). backups.py runs the jobs that it selects.

Jobs. A job key names its subject: `hoover:<zone>:<collection>`, `opendesk:<zone>` or `platform`.
- A Hoover collection becomes eligible when its first ingestion completed, and again after each complete
  reprocessing. A receipt names that event: {'kind': 'ingest' | 'reprocess', 'generation': <id>, 'settled': <time>}.
  A partial processing update and an additional ingestion give no receipt (backups.py reads the receipts).
  An eligible generation waits until the job may make a copy. A generation that has a copy is not copied again, so an
  unchanged collection gets no weekly copy. Several pending generations become one copy of the newest.
- openDesk and the platform recovery set are copied once in each week.
- The weekly limit: a job makes at most one automatic copy in any period of 7 days.
Slots. Each job gets a stable offset in the week from a hash of its key, so the jobs of a site spread over the week.
The jobs of one destination run one at a time. A job whose slot passed while the runner was stopped gets the next
free future slot, with the estimated durations of the jobs before it, so a restart does not start every missed job.
Retention. A job keeps its newest `copies` verified copies. A copy is removed only after a newer copy is verified.
A failed or unverified copy never replaces the last valid copy.
Space. A job runs only when the destination has its estimated size, with a fifth more for temporary files. Otherwise
the job is blocked, and the report names the job and proposes to keep one copy fewer. The rules delete no copy for room.
Destination. The destination folder must hold the marker file .hoover4-backup-destination, which backups.py writes
when an operator enables backups. A remote mount that disappeared shows the folder below it without the marker, so the
jobs pause instead of filling the local disk.
"""
import hashlib
import os
from dataclasses import dataclass, field

WEEK = 7 * 24 * 3600
MARKER = '.hoover4-backup-destination'
# The default duration of a job without a measured duration, for the spacing of slots.
DEFAULT_DURATION = 3600


@dataclass
class Job:
    key: str
    copies: int
    receipts: list = field(default_factory=list)
    estimated_bytes: int = 0
    duration: int = DEFAULT_DURATION

    @property
    def weekly(self):
        return not self.key.startswith('hoover:')


def week_offset(key):
    """The stable offset of a job in the week, in seconds."""
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % WEEK


def slot_after(key, after):
    """The first weekly slot of a job at or after a time."""
    week_start = after - after % WEEK
    slot = week_start + week_offset(key)
    return slot if slot >= after else slot + WEEK


def destination_problem(path):
    if not os.path.isdir(path):
        return f'the backup destination {path} does not exist.'
    if not os.path.exists(os.path.join(path, MARKER)):
        return (f'the backup destination {path} has no {MARKER}. A mount may be missing. The jobs pause until the '
                f'destination is mounted again.')
    return ''


def last_copy(record):
    verified = [c for c in record.get('copies', []) if c.get('verified')]
    return max(verified, key=lambda c: c['finished']) if verified else None


def next_generation(job, record):
    """The generation that the job would copy now, or None."""
    if job.weekly:
        return None if record.get('running') else 'weekly'
    copied = {c['generation'] for c in record.get('copies', []) if c.get('verified')}
    eligible = [r for r in job.receipts if r['kind'] in ('ingest', 'reprocess') and r['generation'] not in copied]
    if not eligible:
        return None
    # A collection gets its first automatic copy after its first completed ingestion. Later ingestion gives no new copy.
    if copied and all(r['kind'] == 'ingest' for r in eligible):
        return None
    newest = max(eligible, key=lambda r: r['settled'])
    return newest['generation']


def due(job, record, now):
    """(ready, reason, generation). ready is True when the job may start a copy at now."""
    generation = next_generation(job, record)
    last = last_copy(record)
    if job.weekly:
        if last and now - last['finished'] < WEEK:
            return False, 'a copy of the last 7 days exists', None
        # A new job waits for its first slot. The runner saves the slot of each job (backups.py), so a later call
        # keeps it.
        slot = record.get('slot') or slot_after(job.key, last['finished'] if last else now)
        if now < slot:
            return False, 'waits for its slot', None
        return True, 'the weekly slot', f'week-{slot}'
    if generation is None:
        return False, 'no eligible generation without a copy', None
    if last and now - last['finished'] < WEEK:
        return False, 'the weekly limit: the last copy is less than 7 days old', generation
    slot = record.get('slot')
    if slot and now < slot:
        return False, 'waits for its slot', generation
    return True, 'an eligible generation', generation


def plan(jobs, records, now, free_bytes):
    """The order of the due jobs and the slots of the late ones. Returns (start, blocked, slots).

    start holds at most one job: the jobs of one destination run one at a time. A due job whose slot is more than one
    hour old was missed while the runner was stopped. Each missed job after the first gets a future slot, spaced by
    the durations of the jobs before it.
    """
    due_jobs, blocked, slots = [], [], {}
    for job in jobs:
        record = records.get(job.key, {})
        ready, reason, generation = due(job, record, now)
        if not ready:
            continue
        needed = int(job.estimated_bytes * 1.2)
        if needed > free_bytes:
            blocked.append({'job': job.key, 'needed_bytes': needed, 'free_bytes': free_bytes,
                            'proposal': f'keep {max(1, job.copies - 1)} copies of {job.key}, or add space to the destination'})
            continue
        due_jobs.append((record.get('slot') or now, job, generation))
    due_jobs.sort(key=lambda item: (item[0], item[1].key))
    start = []
    at = now
    for index, (slot, job, generation) in enumerate(due_jobs):
        if index == 0:
            start.append((job, generation))
            at = now + job.duration
            continue
        # The later jobs wait for the earlier ones, so the runner starts one job at a time.
        slots[job.key] = max(at, slot)
        at = slots[job.key] + job.duration
    return start, blocked, slots


def retention(record, copies):
    """The copies to remove after a new verified copy: the oldest verified copies beyond the count, and the failed ones."""
    verified = sorted((c for c in record.get('copies', []) if c.get('verified')), key=lambda c: c['finished'], reverse=True)
    if not verified:
        return []
    keep = verified[:max(1, copies)]
    return [c for c in record.get('copies', []) if c not in keep]


def recommend(sizes, free_bytes):
    """The recommended retained copies of each kind from the measured sizes: two Hoover copies and three openDesk and
    platform copies when they fit, else fewer. Returns {kind: copies} and the space that the recommendation needs."""
    plan_copies = {'hoover': 2, 'opendesk': 3, 'platform': 3}
    minimum = {'hoover': 1, 'opendesk': 2, 'platform': 1}

    def needed(copies):
        return sum(sizes.get(kind, 0) * (count + 1) for kind, count in copies.items())
    for kind in ('platform', 'opendesk', 'hoover'):
        while needed(plan_copies) > free_bytes and plan_copies[kind] > minimum[kind]:
            plan_copies[kind] -= 1
    return plan_copies, needed(plan_copies)
