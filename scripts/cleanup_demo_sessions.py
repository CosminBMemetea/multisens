#!/usr/bin/env python3
"""Phase 1 of the RideSafe bring-up: wipes every Session (and its
cascaded ground_truth/predictions/evaluation_results/
resource_observations), Scenario, and EvaluationProfile from the
MultiSens SQLite database - the "clean development data" step before
building the RideSafe front/rear demo from scratch.

Goes through `app.persistence.repository`'s own delete functions, not
raw SQL - the same code path a future DELETE API route would use. See
repository.py's "cleanup (RideSafe bring-up, Phase 1)" section for why
each child table has to be deleted before its parent (no ON DELETE
CASCADE exists in the schema).

BACK UP FIRST. This is destructive and has no undo beyond a DB backup:

    docker run --rm -v multisense_backend-data:/data:ro \\
      -v "$(pwd)/backups:/backup" alpine \\
      cp /data/multisens.db /backup/multisens.pre-ridesafe-reset.db

Dry-run by default - lists what's present and would be deleted, deletes
nothing. Pass --yes to actually delete.

Run inside the backend image so `app`/`multisens_sdk` are importable and
MULTISENS_DB_PATH points at the real volume-backed file (the host has
neither installed):

    docker run --rm \\
      -v multisense_backend-data:/data \\
      -e MULTISENS_DB_PATH=/data/multisens.db \\
      -v "$(pwd)/scripts:/scripts:ro" \\
      --entrypoint python3 multisense-backend \\
      /scripts/cleanup_demo_sessions.py --yes
"""
from __future__ import annotations

import argparse

from app.persistence import db, repository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--yes', action='store_true', help='actually delete (default: dry run, deletes nothing)')
    args = parser.parse_args()

    conn = db.connect(db.get_db_path())

    sessions = repository.list_sessions(conn)
    scenarios = repository.list_scenarios(conn)
    profiles = repository.list_profiles(conn)

    print(f'{len(sessions)} sessions, {len(scenarios)} scenarios, {len(profiles)} profiles found:')
    for s in sessions:
        print(f'  session  {s.id!r:45} {s.name!r} (status={s.status})')
    for sc in scenarios:
        print(f'  scenario {sc.id!r:45} {sc.name!r}')
    for p in profiles:
        print(f'  profile  {p.id!r:45} {p.name!r}')

    if not args.yes:
        print('\nDry run only - nothing deleted. Re-run with --yes to actually delete all of the above.')
        return

    for s in sessions:
        repository.delete_session(conn, s.id)
    for sc in scenarios:
        repository.delete_scenario(conn, sc.id)
    for p in profiles:
        repository.delete_profile(conn, p.id)

    remaining_sessions = repository.list_sessions(conn)
    remaining_scenarios = repository.list_scenarios(conn)
    remaining_profiles = repository.list_profiles(conn)
    print(
        f'\nDeleted. Remaining: {len(remaining_sessions)} sessions, '
        f'{len(remaining_scenarios)} scenarios, {len(remaining_profiles)} profiles.'
    )


if __name__ == '__main__':
    main()
