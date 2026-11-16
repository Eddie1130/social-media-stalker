#!/usr/bin/env python3
"""Bounded Linux I/O sampler; reports metadata/counters, never file contents.

Use disk deltas as physical device totals. Process counters include reaped children
and must NOT be summed. New/reused PIDs are omitted until the next sample.
"""
import argparse
import json
import math
from pathlib import Path
import time


def log_files(logs):
    files = {}
    unreadable = 0
    try:
        directories = list(logs.iterdir())
    except OSError:
        return files, 1
    for directory in directories:
        try:
            if not directory.is_dir():
                continue
            paths = list(directory.iterdir())
        except OSError:
            unreadable += 1
            continue
        for path in paths:
            if not (path.name.startswith('log.db') or '-json.log' in path.name
                    or path.name in ('config.v2.json', 'hostconfig.json')):
                continue
            try:
                st = path.stat()
                files[str(path.relative_to(logs))] = (st.st_ino, st.st_size, st.st_mtime_ns)
            except OSError:
                pass
    return files, unreadable


def snapshot(proc, logs):
    disks = {}
    for line in (proc / 'diskstats').read_text().splitlines():
        row = line.split()
        if row[2].startswith(('sata', 'sd', 'md', 'dm-')):
            disks[row[2]] = [int(x) for x in row[3:14]]
    vm = dict(line.split() for line in (proc / 'vmstat').read_text().splitlines())
    processes = {}
    denied = 0
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            io = dict(line.split(':', 1) for line in (entry / 'io').read_text().splitlines())
            name = (entry / 'comm').read_text().strip()
            current_stat = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if current_stat[19] != stat[19]:
                continue
            processes[(entry.name, stat[19])] = {
                'name': name,
                'write': int(io['write_bytes']), 'read': int(io['read_bytes']),
            }
        except (OSError, ValueError, IndexError):
            denied += 1
    files, unreadable_logs = log_files(logs)
    return {'at': time.monotonic(), 'disks': disks, 'vm': vm,
            'processes': processes, 'files': files, 'unreadableProcesses': denied, 'unreadableLogDirectories': unreadable_logs}


def difference(before, after):
    elapsed = after['at'] - before['at']
    disks = {}
    for name, current in after['disks'].items():
        if name not in before['disks']:
            continue
        d = [a-b for a, b in zip(current, before['disks'][name])]
        disks[name] = {'readKiBps': round(d[2]*.5/elapsed, 2),
                       'writeKiBps': round(d[6]*.5/elapsed, 2),
                       'writeIOPS': round(d[4]/elapsed, 2),
                       'writeAwaitMs': round(d[7]/d[4], 2) if d[4] else 0,
                       'utilPct': round(d[9]/(elapsed*10), 2)}
    processes = []
    for key, row in after['processes'].items():
        old = before['processes'].get(key)
        if old is None:
            continue
        w, r = row['write']-old['write'], row['read']-old['read']
        if w > 0 or r > 0:
            processes.append({'pid': key[0], 'name': row['name'],
                              'writeKiBps': round(max(0,w)/1024/elapsed, 2),
                              'readKiBps': round(max(0,r)/1024/elapsed, 2)})
    files = []
    for name, st in after['files'].items():
        old = before['files'].get(name)
        if old and st != old:
            files.append({'path': name, 'size': st[1],
                          'growthBytes': st[1]-old[1] if st[0] == old[0] else None})
    return {'elapsedSeconds': round(elapsed, 3), 'disks': disks,
            'swapInPages': int(after['vm']['pswpin'])-int(before['vm']['pswpin']),
            'swapOutPages': int(after['vm']['pswpout'])-int(before['vm']['pswpout']),
            'processCountersNotAdditive': sorted(processes, key=lambda r:r['writeKiBps'], reverse=True)[:20],
            'changedLogFiles': [f for f in files if Path(f['path']).name not in ('config.v2.json', 'hostconfig.json')],
            'changedMetadataFiles': [f for f in files if Path(f['path']).name in ('config.v2.json', 'hostconfig.json')],
            'unreadableProcesses': after['unreadableProcesses'],
            'unreadableLogDirectories': after.get('unreadableLogDirectories', 0)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proc', type=Path, default=Path('/proc'))
    p.add_argument('--logs', type=Path, default=Path('/volume1/@docker/containers'))
    p.add_argument('--interval', type=float, default=10)
    p.add_argument('--samples', type=int, default=6)
    a = p.parse_args()
    if not math.isfinite(a.interval) or a.interval < 1 or a.samples < 1:
        p.error('interval and samples must be >= 1')
    previous = snapshot(a.proc, a.logs)
    for _ in range(a.samples):
        time.sleep(a.interval)
        current = snapshot(a.proc, a.logs)
        print(json.dumps(difference(previous, current)), flush=True)
        previous = current


if __name__ == '__main__':
    main()
