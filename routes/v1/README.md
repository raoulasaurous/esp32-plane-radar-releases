# Backup route data (routes/v1)

Route data: Virtual Radar Server standing data, https://github.com/vradarserver/standing-data, CC0. Thank you.

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
