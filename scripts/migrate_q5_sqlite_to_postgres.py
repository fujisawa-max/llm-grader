"""Copy a closed legacy pilot database, retaining IDs and immutable history.

Default is read-only planning. DATABASE_URL is read from the environment.
Operational file columns are relocated explicitly; JSON/snapshots are never rewritten.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.pool import NullPool


def canonical(value):
    if isinstance(value, (dt.datetime, dt.date)):
        if isinstance(value, dt.datetime):
            value = value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)
        return value.isoformat()
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(v) for v in value]
    return value


def manifest(root):
    return [{"path": str(p.relative_to(root)), "size": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(root.rglob('*')) if p.is_file()]


def migrate(source, destination, source_root, target_root, expected_test, apply=False):
    src = create_engine(f'sqlite:///file:{source.resolve()}?mode=ro&uri=true', poolclass=NullPool)
    dst = create_engine(destination, poolclass=NullPool)
    sm, dm = MetaData(), MetaData()
    sm.reflect(src)
    dm.reflect(dst)
    report = {'mode': 'apply' if apply else 'dry-run', 'tables': {}, 'conflicts': [],
              'artifact_mapping': [], 'user_mapping': [], 'ownership_mapping': [], 'unresolved': []}
    original = manifest(source_root)
    report['artifact_count'] = len(original)
    if not original or manifest(target_root) != original:
        raise ValueError('source/destination artifact manifest mismatch')
    with src.connect() as sc, dst.begin() as dc:
        tests = list(sc.execute(select(sm.tables['tests'].c.id)).scalars())
        if tests != [expected_test]:
            raise ValueError('source must be a closed single-test pilot database')
        loaded = {t.name: [dict(r) for r in sc.execute(select(t)).mappings()] for t in sm.sorted_tables}
        existing = {t: {tuple(r[k.name] for k in dm.tables[t].primary_key): dict(r)
                        for r in dc.execute(select(dm.tables[t])).mappings()}
                    for t in loaded if t in dm.tables}
        pending = []
        for table in dm.sorted_tables:
            if table.name not in loaded:
                continue
            rows = loaded[table.name]
            stats = report['tables'][table.name] = {'source': len(rows), 'insert': 0, 'already_present': 0}
            for row in rows:
                unknown = set(row)-set(table.c.keys())
                if unknown:
                    raise ValueError(f'unsupported source columns {table.name}: {unknown}')
                if table.name == 'users':
                    report['user_mapping'].append({'source_id': row['id'], 'destination_id': row['id'], 'email': row.get('email'), 'strategy': 'preserve legacy identity; no merge'})
                if table.name == 'courses':
                    report['ownership_mapping'].append({'course_id': row['id'], 'owner_user_id': row['owner_user_id']})
                relocatable = {'test_materials': ['storage_ref'], 'grading_job_items': ['raw_response_path', 'normalized_result_path']}.get(table.name, [])
                for key in relocatable:
                    value = row.get(key)
                    if value and Path(value).is_absolute() and Path(value).is_relative_to(source_root):
                        new = str(target_root / Path(value).relative_to(source_root))
                        if not Path(new).is_file():
                            raise ValueError(f'missing relocated file: {new}')
                        report['artifact_mapping'].append({'table': table.name, 'id': row['id'], 'column': key, 'from': value, 'to': new})
                        row[key] = new
                pk = tuple(row[k.name] for k in table.primary_key)
                old = existing[table.name].get(pk)
                if old:
                    if any(canonical(old[k]) != canonical(v) for k, v in row.items()):
                        report['conflicts'].append({'table': table.name, 'pk': pk})
                    else:
                        stats['already_present'] += 1
                else:
                    # Check all natural uniqueness constraints, not just UUIDs.
                    for constraint in table.constraints:
                        if constraint.__class__.__name__ != 'UniqueConstraint':
                            continue
                        keys = [c.name for c in constraint.columns]
                        if any(row.get(k) is None for k in keys):
                            continue
                        if any(all(canonical(e[k]) == canonical(row[k]) for k in keys) for e in existing[table.name].values()):
                            report['conflicts'].append({'table': table.name, 'pk': pk, 'unique_columns': keys})
                    pending.append((table, row))
                    stats['insert'] += 1
        if report['conflicts']:
            report['status'] = 'CONFLICT'
            return report
        # Validate every FK and self-referencing parent before any mutation.
        future = {name: list(rows.values()) for name, rows in existing.items()}
        for table, row in pending:
            future[table.name].append(row)
        for table, row in pending:
            for fk in table.foreign_key_constraints:
                values = [row.get(e.parent.name) for e in fk.elements]
                if any(v is None for v in values):
                    continue
                target = fk.referred_table.name
                if not any(all(canonical(r[e.column.name]) == canonical(row[e.parent.name]) for e in fk.elements) for r in future[target]):
                    report['unresolved'].append({'table': table.name, 'id': row.get('id'), 'foreign_table': target})
        if report['unresolved']:
            report['status'] = 'UNRESOLVED'
            return report
        if apply:
            # Tables are dependency ordered; self-parent rows need their own ordering.
            while pending:
                progressed = False
                for table, row in list(pending):
                    waiting = False
                    for fk in table.foreign_key_constraints:
                        if fk.referred_table.name != table.name:
                            continue
                        values = [row.get(e.parent.name) for e in fk.elements]
                        if any(v is None for v in values):
                            continue
                        if any(t.name == table.name and all(r.get(e.column.name) == row[e.parent.name] for e in fk.elements) for t, r in pending):
                            waiting = True
                    if waiting:
                        continue
                    dc.execute(table.insert().values(**row))
                    pending.remove((table, row))
                    progressed = True
                if not progressed:
                    raise ValueError('cyclic self-reference; transaction rolled back')
        report['status'] = 'PASS'
    src.dispose()
    dst.dispose()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--source-root', type=Path, required=True)
    p.add_argument('--target-root', type=Path, required=True)
    p.add_argument('--test-id', required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    result = migrate(args.source, os.environ['DATABASE_URL'], args.source_root.resolve(),
                     args.target_root.resolve(), args.test_id, args.apply)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=canonical))
    print(json.dumps({'status': result['status'], 'mode': result['mode'], 'insert': sum(x['insert'] for x in result['tables'].values()), 'already_present': sum(x['already_present'] for x in result['tables'].values()), 'conflicts': len(result['conflicts'])}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
