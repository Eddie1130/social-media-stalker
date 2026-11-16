"""Repair identical archive copies without removing either public pathname.

Run maintenance with the catalog writer stopped. A dry run is the default.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid


class ArchiveLinkError(RuntimeError):
    pass


def checked_path(root, file):
    root = Path(root).resolve()
    file = Path(os.path.abspath(file))
    try:
        relative = file.relative_to(root)
    except ValueError:
        raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_PATH_INVALID") from None
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_SYMLINK")
    return file


def signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def fingerprint(file):
    with open(file, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_NOT_FILE")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
        if signature(before) != signature(os.fstat(stream.fileno())):
            raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_CHANGED")
    if signature(before) != signature(file.lstat()):
        raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_CHANGED")
    return digest.hexdigest(), before


def ensure_archive_link(root, source, target, apply=True, expected_digest=None):
    """Link missing aliases; replace existing aliases only after exact verification.

    Different contents and different filesystems are preserved for caller reporting.
    Writers must serialize changes to these paths during this operation.
    """
    source, target = checked_path(root, source), checked_path(root, target)
    source_info = source.lstat()
    if not stat.S_ISREG(source_info.st_mode):
        raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_NOT_FILE")
    if not target.exists():
        if apply:
            os.link(source, target)
        return "linked" if apply else "would_link"
    target_info = target.lstat()
    if not stat.S_ISREG(target_info.st_mode):
        raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_NOT_FILE")
    if (source_info.st_dev, source_info.st_ino) == (target_info.st_dev, target_info.st_ino):
        return "shared"
    if source_info.st_dev != target_info.st_dev:
        return "cross_device"
    if source_info.st_size != target_info.st_size:
        return "different"
    source_hash, source_info = fingerprint(source)
    target_hash, target_info = fingerprint(target)
    if expected_digest is not None and source_hash != expected_digest:
        raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_CHANGED")
    if source_hash != target_hash:
        return "different"
    for file, info in ((source, source_info), (target, target_info)):
        checked_path(root, file)
        if signature(file.lstat()) != signature(info):
            raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_CHANGED")
    if not apply:
        return "would_repair"
    temporary = target.with_name(".hardlink-" + uuid.uuid4().hex)
    try:
        os.link(source, temporary)
        # Creating our link changes source ctime, but must not change its contents.
        if signature(source.lstat())[:4] != signature(source_info)[:4]:
            raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_CHANGED")
        if not os.path.samefile(source, temporary):
            raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_CHANGED")
        if signature(target.lstat()) != signature(target_info):
            raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_CHANGED")
        os.replace(temporary, target)
        if not os.path.samefile(source, target):
            raise ArchiveLinkError("TIKTOK_ARCHIVE_LINK_VERIFY_FAILED")
    finally:
        temporary.unlink(missing_ok=True)
    return "repaired"


def repair_archive(root, apply, report):
    """Compare only media/post files; prefer an already shared media inode."""
    root = Path(root).resolve()
    sizes = defaultdict(list)
    for directory, folders, files in os.walk(root / "tiktok", followlinks=False):
        folders[:] = sorted(name for name in folders if not (Path(directory) / name).is_symlink())
        for name in sorted(files):
            file = Path(directory) / name
            parts = file.relative_to(root / "tiktok").parts
            if not ({"media", "posts"} & set(parts[:-1])):
                continue
            if file.suffix.lower() not in (".mp4", ".jpg", ".jpeg", ".png", ".webp"):
                continue
            info = file.lstat()
            if stat.S_ISREG(info.st_mode) and info.st_size:
                checked_path(root, file)
                sizes[info.st_size].append(file)
    totals = Counter()
    for size, files in sorted(sizes.items()):
        if archive_kinds(root, files) != {"media", "posts"}:
            continue
        hashes, cached = defaultdict(list), {}
        for file in files:
            info = file.lstat()
            key = signature(info)
            if key not in cached:
                cached[key] = fingerprint(file)[0]
            hashes[cached[key]].append(file)
            totals["hashed_files"] += 1
        for digest, copies in hashes.items():
            if archive_kinds(root, copies) != {"media", "posts"}:
                continue
            totals["duplicate_groups"] += 1
            copies.sort(key=lambda f: (-f.stat().st_nlink, "media" not in f.relative_to(root).parts[:-1], str(f)))
            source = copies[0]
            for target in copies[1:]:
                before = target.lstat()
                event = {"source": str(source.relative_to(root)), "target": str(target.relative_to(root)), "sha256": digest, "bytes": size}
                # Flush intent for live auditing; sync the completed report once.
                if apply:
                    report.write(json.dumps(dict(event, status="intent")) + "\n")
                    report.flush()
                status = ensure_archive_link(root, source, target, apply=apply, expected_digest=digest)
                totals[status] += 1
                if status == "repaired" and before.st_nlink == 1:
                    totals["unlinked_copy_bytes"] += size
                report.write(json.dumps(dict(event, status=status)) + "\n")
                report.flush()
        if totals["hashed_files"] % 25 == 0:
            print(json.dumps(dict(totals)), flush=True)
    return dict(totals)


def archive_kinds(root, files):
    return {"media" if "media" in file.relative_to(root).parts[:-1] else "posts" for file in files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="Stop the catalog writer before applying")
    args = parser.parse_args()
    with args.report.open("x", encoding="utf-8") as report:
        totals = repair_archive(args.root, args.apply, report)
        report.write(json.dumps({"summary": totals}) + "\n")
        report.flush()
        os.fsync(report.fileno())
    print(json.dumps({"summary": totals}), flush=True)


if __name__ == "__main__":
    main()
