# Background map data

Map data for the radar's optional background map: Natural Earth 10m
(public domain, naturalearthdata.com) and OurAirports runways (public domain,
ourairports.com), cut into 4x4 degree cells. Format:
docs/map-format.md in the firmware source. Radars read maps/v1/index.bin, then
only the cells around them.
