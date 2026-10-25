#!/usr/bin/env python3
"""Build the radar's backup route files from Virtual Radar Server standing data.

    python3 -I tools/route_build/build_routes.py <standing-data checkout> <out_dir>
            [--prev <old_out_dir>] [--date YYYYMMDD] [--codes EZY,RYR,...]
    python3 -I tools/route_build/build_routes.py --check <out_dir>
    python3 -I tools/route_build/build_routes.py --normalise <callsign>...

WHY (1.1.94): the radar's two route sources, adsbdb and hexdb, share one
upstream database, so they are wrong together - about a third of live routes
fail the plausibility tests and are hidden. VRS standing data
(github.com/vradarserver/standing-data, routes/schema-01, CC0) is an
independent source. The firmware asks it ONLY when adsbdb/hexdb have no route
or a route the tests reject (src/services/route_vrs.cpp), so it can fill a gap
but never replaces a route the radar would show anyway.

The checkout is ~620k rows in ~1,500 CSV files, 25+ MB. A radar needs one
callsign at a time, so the rows are cut into small text shards it can fetch
from the PUBLIC releases repo through raw.githubusercontent.com:

    <out>/<CODE>/<k>.txt     k = first char of the normalised flight number
    line 1:  #vrs1 <yyyymmdd> <rowcount>
    then:    <number>,<AAAA-BBBB[-...]>      sorted, one per line, '\\n' ended

A shard over SPLIT_BYTES is split by the first TWO chars of the number into
<CODE>/<k><c>.txt files; <CODE>/<k>.txt then becomes a stub whose header says
"split" instead of a count, and keeps only the one-char numbers (EZY1 stays in
EZY/1.txt). The radar reads the one-char file first and follows a split to the
two-char file. No index: a 404 means "no routes there". Every file is at most
MAX_BYTES, which must equal config::kVrsShardMaxBytes (the radar refuses a
bigger body; tools/route_vrs_test checks the two agree).

Callsign normalisation is the VRS rule (routes/schema-01/README.md) narrowed
to ICAO codes: 3 letters, then a number of n, nn, nnn, nnnn, nA, nnA, nnnA, nAA
or nnAA after the leading zeros are stripped. route_vrs.cpp's
normaliseCallsign() must give the same answer for every input; the shared
cases are tools/route_vrs_test/norm_cases.txt.

DETERMINISTIC: the same input gives byte-identical files. The date in a shard
header is the date its CONTENT last changed: with --prev (the previous build,
e.g. the releases repo's current routes/v1) a shard whose rows did not change
keeps its old header, so a weekly rebuild only rewrites the shards that moved.
Without --prev every header gets the dataset date. The dataset date defaults to
the checkout's HEAD commit date.

--codes builds only those airlines (the tests use it on the corpus airlines).
Nothing here touches the network; publishing is publish_routes.sh, a separate
and deliberate step (the files land in the PUBLIC releases repo).
"""
import argparse
import collections
import csv
import glob
import os
import re
import subprocess
import sys

SPLIT_BYTES = 24 * 1024       # a one-char shard bigger than this is split
MAX_BYTES = 32 * 1024         # == config::kVrsShardMaxBytes, every file
MIN_AIRPORTS, MAX_AIRPORTS = 2, 10
FORMAT = "#vrs1"
SOURCE = "https://github.com/vradarserver/standing-data"
CREDIT = ("Route data: Virtual Radar Server standing data, "
          "https://github.com/vradarserver/standing-data, CC0. Thank you.")

CODE_RE = re.compile(r"[A-Z]{3}")
REST_RE = re.compile(r"[0-9][A-Z0-9]*")
NUM_RE = re.compile(r"[0-9]{1,4}|[0-9]{1,3}[A-Z]|[0-9]{1,2}[A-Z]{2}")
AIRPORT_RE = re.compile(r"[A-Z0-9]{4}")
HEADER_RE = re.compile(r"#vrs1 ([0-9]{8}) ([0-9]+|split)")
DATE_RE = re.compile(r"[0-9]{8}")


def normalise(callsign):
    """(code, number) for a callsign VRS can hold a route for, else None.

    MUST match services::route_vrs::normaliseCallsign() exactly. Trailing
    spaces are dropped (some feeds pad to 8); anything else that is not
    3 letters + a digit-led number is a registration or an IATA-coded callsign,
    and the radar makes no request for it at all."""
    cs = callsign.rstrip(" ")
    code, rest = cs[:3], cs[3:]
    if not CODE_RE.fullmatch(code) or not REST_RE.fullmatch(rest):
        return None
    num = rest.lstrip("0")
    if num == "" or not ("0" <= num[0] <= "9"):
        num = "0" + num
    if not NUM_RE.fullmatch(num):
        return None
    return code, num


def valid_airports(s):
    parts = s.split("-")
    return (MIN_AIRPORTS <= len(parts) <= MAX_AIRPORTS and
            all(AIRPORT_RE.fullmatch(p) for p in parts))


def git_info(src):
    def git(*args):
        try:
            return subprocess.run(["git", "-C", src] + list(args), check=True,
                                  capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""
    # Only a checkout of its own: a directory INSIDE another repository (the
    # test fixture lives in the firmware repo) must not borrow that one's
    # commit.
    top = git("rev-parse", "--show-toplevel")
    if not top or os.path.realpath(top) != os.path.realpath(src):
        return "", ""
    return (git("log", "-1", "--format=%cd", "--date=format:%Y%m%d"),
            git("rev-parse", "HEAD"))


def read_rows(src, codes):
    """{(code, num): airports} plus drop counts. Files and rows are read in a
    fixed order, so a conflict is resolved the same way every time - by
    dropping BOTH answers: two routes for one callsign is no answer."""
    root = os.path.join(src, "routes", "schema-01")
    paths = sorted(glob.glob(os.path.join(root, "*", "*.csv")))
    if not paths:
        sys.exit(f"no routes/schema-01/*/*.csv under {src}")
    routes, conflicts = {}, set()
    stats = collections.Counter()
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                stats["rows"] += 1
                key = normalise((row.get("Callsign") or "").strip())
                if key is None:
                    stats["dropped_callsign"] += 1
                    continue
                if codes is not None and key[0] not in codes:
                    stats["skipped_code"] += 1
                    continue
                ap = (row.get("AirportCodes") or "").strip()
                if not valid_airports(ap):
                    stats["dropped_airports"] += 1
                    continue
                if key in routes:
                    if routes[key] != ap:
                        conflicts.add(key)
                    else:
                        stats["duplicates"] += 1
                    continue
                routes[key] = ap
    for key in conflicts:
        del routes[key]
    stats["dropped_conflicts"] = len(conflicts)
    return routes, stats


def render(date, count, rows):
    head = f"{FORMAT} {date} {count}\n"
    return (head + "".join(f"{n},{ap}\n" for n, ap in rows)).encode("ascii")


def shard_files(code, nums, date, split_bytes):
    """[(relative path, rows, header count-or-"split")] for one airline."""
    by_first = collections.defaultdict(list)
    for n in sorted(nums):
        by_first[n[0]].append((n, nums[n]))
    out = []
    for k in sorted(by_first):
        rows = by_first[k]
        # Only the one-char number itself ("1") can stay in a stub, so a shard
        # with nothing longer gains nothing from a split.
        if (len(render(date, len(rows), rows)) <= split_bytes or
                all(len(n) == 1 for n, _ in rows)):
            out.append((f"{code}/{k}.txt", rows, len(rows)))
            continue
        out.append((f"{code}/{k}.txt", [r for r in rows if len(r[0]) == 1], "split"))
        by_two = collections.defaultdict(list)
        for r in rows:
            if len(r[0]) >= 2:
                by_two[r[0][:2]].append(r)
        for kk in sorted(by_two):
            out.append((f"{code}/{kk}.txt", by_two[kk], len(by_two[kk])))
    return out


def read_prev(prev, rel):
    """(date, body-after-header) of the previous build's file, or None."""
    if prev is None:
        return None
    try:
        with open(os.path.join(prev, rel), "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    head, sep, body = data.partition(b"\n")
    m = HEADER_RE.fullmatch(head.decode("ascii", "replace"))
    return (m.group(1), m.group(2), body) if m and sep else None


def build(src, out, prev, date, codes, split_bytes):
    git_date, commit = git_info(src)
    date = date or git_date
    if not date or not DATE_RE.fullmatch(date):
        sys.exit("no dataset date: pass --date YYYYMMDD (the checkout is not a git clone)")
    if os.path.exists(out) and os.listdir(out):
        sys.exit(f"{out} is not empty - build into a fresh directory")
    routes, stats = read_rows(src, codes)
    by_code = collections.defaultdict(dict)
    for (code, num), ap in routes.items():
        by_code[code][num] = ap
    files = total = biggest = kept_dates = 0
    for code in sorted(by_code):
        for rel, rows, count in shard_files(code, by_code[code], date, split_bytes):
            data = render(date, count, rows)
            old = read_prev(prev, rel)
            if old is not None and old[1] == str(count) and old[2] == data.partition(b"\n")[2]:
                data = render(old[0], count, rows)  # unchanged: keep its date
                kept_dates += old[0] != date
            if len(data) > MAX_BYTES:
                sys.exit(f"{rel}: {len(data)} bytes > {MAX_BYTES} even after the split")
            os.makedirs(os.path.join(out, code), exist_ok=True)
            with open(os.path.join(out, rel), "wb") as fh:
                fh.write(data)
            files += 1
            total += len(data)
            biggest = max(biggest, len(data))
    meta = [f"{FORMAT} meta", f"dataset {date}", f"source {SOURCE}",
            f"commit {commit or 'unknown'}", f"routes {len(routes)}",
            f"airlines {len(by_code)}", f"files {files}", f"bytes {total}",
            f"max_file {biggest}",
            f"dropped_callsign {stats['dropped_callsign']}",
            f"dropped_airports {stats['dropped_airports']}",
            f"dropped_conflicts {stats['dropped_conflicts']}"]
    if codes is not None:
        meta.append("codes " + ",".join(sorted(codes)))
    with open(os.path.join(out, "meta.txt"), "w", newline="\n") as fh:
        fh.write("\n".join(meta) + "\n")
    with open(os.path.join(out, "README.md"), "w", newline="\n") as fh:
        fh.write(README)
    print(f"built {len(routes)} routes, {len(by_code)} airlines, {files} files, "
          f"{total} bytes (max {biggest}), dataset {date}"
          + (f", {kept_dates} files kept an older date" if prev else "")
          + f"; dropped {stats['dropped_callsign']} callsigns, "
          f"{stats['dropped_airports']} airport lists, {stats['dropped_conflicts']} conflicts")


def check(out):
    """Everything the radar relies on, file by file. Exit 1 on any problem."""
    errs = []

    def err(msg):
        if len(errs) < 50:
            print("ERROR:", msg)
        errs.append(msg)

    meta = {}
    try:
        with open(os.path.join(out, "meta.txt"), encoding="ascii") as fh:
            for line in fh.read().splitlines()[1:]:
                k, _, v = line.partition(" ")
                meta[k] = v
    except OSError:
        sys.exit(f"{out}: no meta.txt")
    if not os.path.isfile(os.path.join(out, "README.md")):
        err("no README.md")
    dataset = meta.get("dataset", "")
    if not DATE_RE.fullmatch(dataset):
        err(f"meta.txt: bad dataset '{dataset}'")
    files = total = biggest = rows_total = 0
    for code in sorted(os.listdir(out)):
        cdir = os.path.join(out, code)
        if not os.path.isdir(cdir):
            if code not in ("meta.txt", "README.md"):
                err(f"stray file {code}")
            continue
        if not CODE_RE.fullmatch(code):
            err(f"bad airline directory {code}")
            continue
        names = sorted(os.listdir(cdir))
        stubs = {}
        for name in names:
            rel = f"{code}/{name}"
            stem, ext = os.path.splitext(name)
            if ext != ".txt" or not re.fullmatch(r"[0-9][0-9A-Z]?", stem):
                err(f"{rel}: bad file name")
                continue
            data = open(os.path.join(cdir, name), "rb").read()
            files += 1
            total += len(data)
            biggest = max(biggest, len(data))
            if len(data) > MAX_BYTES:
                err(f"{rel}: {len(data)} bytes > {MAX_BYTES}")
            if not data.endswith(b"\n"):
                err(f"{rel}: last line not terminated")
            try:
                lines = data.decode("ascii").split("\n")[:-1]
            except UnicodeDecodeError:
                err(f"{rel}: not ASCII")
                continue
            m = HEADER_RE.fullmatch(lines[0]) if lines else None
            if m is None:
                err(f"{rel}: bad header")
                continue
            if m.group(1) > dataset:
                err(f"{rel}: date {m.group(1)} after the dataset {dataset}")
            split = m.group(2) == "split"
            if split and len(stem) != 1:
                err(f"{rel}: only a one-char file can be a split stub")
            if len(stem) == 1:
                stubs[stem] = split
            prev_num = None
            for line in lines[1:]:
                num, sep, ap = line.partition(",")
                if not sep or normalise(code + num) != (code, num) or not valid_airports(ap):
                    err(f"{rel}: bad line '{line}'")
                    continue
                if prev_num is not None and num <= prev_num:
                    err(f"{rel}: '{num}' out of order or repeated")
                prev_num = num
                if len(stem) == 1 and split and num != stem:
                    err(f"{rel}: split stub holds '{num}' (only '{stem}' belongs)")
                elif len(stem) == 1 and not split and num[0] != stem:
                    err(f"{rel}: '{num}' does not belong here")
                elif len(stem) == 2 and (len(num) < 2 or num[:2] != stem):
                    err(f"{rel}: '{num}' does not belong here")
            n = len(lines) - 1
            rows_total += n
            if not split and int(m.group(2)) != n:
                err(f"{rel}: header says {m.group(2)} rows, file has {n}")
        for name in names:
            stem = os.path.splitext(name)[0]
            if len(stem) == 2 and not stubs.get(stem[0], False):
                err(f"{code}/{name}: two-char file with no split stub {code}/{stem[0]}.txt")
        for k, split in stubs.items():
            if split and not any(len(os.path.splitext(n)[0]) == 2 and n[0] == k for n in names):
                err(f"{code}/{k}.txt: split stub with no two-char files")
    for k, v in (("files", files), ("bytes", total), ("routes", rows_total)):
        if meta.get(k) != str(v):
            err(f"meta.txt says {k} {meta.get(k)}, found {v}")
    print(f"check {out}: {files} files, {rows_total} routes, {total} bytes, "
          f"max file {biggest} (limit {MAX_BYTES}), dataset {dataset}: "
          + ("FAILED, %d problems" % len(errs) if errs else "ok"))
    sys.exit(1 if errs else 0)


README = f"""# Backup route data (routes/v1)

{CREDIT}

The plane radar asks these files for a flight's route only when its main
sources (adsbdb, hexdb) have none, or have one that the radar's position
tests reject. Built by tools/route_build/build_routes.py in the firmware
source; meta.txt names the dataset date and the standing-data commit.

## Format

- `<CODE>/<k>.txt`: routes for airline ICAO code CODE whose normalised flight
  number starts with k. The callsign is normalised the VRS way: 3 letters,
  then the number with its leading zeros stripped (EZY0001 -> EZY1,
  EZY00AB -> EZY0AB); valid numbers are n, nn, nnn, nnnn, nA, nnA, nnnA,
  nAA and nnAA.
- Line 1: `#vrs1 <yyyymmdd> <rowcount>` (the date the file's content last
  changed). Then one `<number>,<airports>` line per callsign, sorted, each
  ending in a newline. Airports are 4-character ICAO codes in flight order,
  joined by `-`; more than two means a multi-stop route.
- A big airline's `<k>.txt` is split: its header says `split` instead of a
  count, it keeps only the one-character number `k` (if there is one), and
  the rest live in `<CODE>/<k><c>.txt` by the first two characters.
- A missing file means no routes for those numbers. Every file is 32 KB or
  less.
"""


def main():
    a = sys.argv[1:]
    if a[:1] == ["--check"] and len(a) == 2:
        check(a[1])
    if a[:1] == ["--normalise"]:
        for cs in a[1:]:
            key = normalise(cs.replace("_", " "))
            print(cs, " ".join(key) if key else "-")
        return
    p = argparse.ArgumentParser(usage=__doc__)
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("--prev")
    p.add_argument("--date")
    p.add_argument("--codes")
    # Tests only: a tiny split threshold forces every shard through the
    # split-stub path. Real builds always use SPLIT_BYTES.
    p.add_argument("--split-bytes", type=int, default=SPLIT_BYTES, help=argparse.SUPPRESS)
    o = p.parse_args(a)
    codes = set(o.codes.split(",")) if o.codes else None
    build(o.src, o.out, o.prev, o.date, codes, o.split_bytes)


if __name__ == "__main__":
    main()
