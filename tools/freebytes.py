#!/usr/bin/env python3
"""
freebytes.py
Counts free bytes in a ROM produced by ld65

Copyright 2023 Retrotainment Games LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

----

A program for Nintendo Entertainment System (NES) is divided into
memory areas, also called banks.  A support circuit called a mapper
causes some of these memory areas to be visible to the CPU at any
moment.  Some data has to be in named memory areas, such as code and
small lookup tables used by code.  The last 16 KiB of the ROM is an
especially important memory area called HOME, as it is always visible
no matter which banks are switched in.  Bulk data can be in a large
contiguous area that Retrotainment's linker scripts call LINEAR.
Creating a named memory area takes 8 to 16 KiB away from LINEAR, but
most data in LINEAR can be redistributed to free space in a named
memory area.  Late in a game's development, for example, sprite cels
are often moved back and forth between LINEAR and other areas.

This program uses the linker script and the linker's map output to
estimate the free space in the whole ROM, even if things were to be
moved in or out of LINEAR or HOME.

1. Read memory area and segment assignments from linker script
2. Read segment sizes from map.txt
3. Calculate how much of each memory area is occupied

"""
import os, sys, re

PROGDIR = os.path.dirname(sys.argv[0])
linkscriptname = os.path.join(PROGDIR, "..", "mmc3_4mbit_packed.cfg")
mapoutputname = os.path.join(PROGDIR, "..", "map.txt")

# Loading linker script #############################################

lsmajorblocksRE = re.compile(r"""([a-zA-Z]+)\s*\{(.*?)\}""")

def ld65parseint(intval):
    if intval.startswith("$"): return int(intval[1:], 16)
    return int(intval, 10)

def parse_nvpset(nvpset):
    nvpset = [nv.split("=", 1) for nv in nvpset.split(",")]
    nvpset = {k.strip().lower(): v.strip() for k, v in nvpset}
    return nvpset

def parse_lsstatements(contents):
    segs = [line.strip() for line in contents.split(";")]
    segs = [line.split(":", 1) for line in segs if line]
    segs = [(k.strip(), parse_nvpset(v)) for k, v in segs]
    return segs

def ld65_load_linker_script(linkscriptname):
    with open(linkscriptname, "r", encoding="utf-8") as infp:
        lscontents = [line.split("#", 1)[0].split() for line in infp]
    lscontents = " ".join(word for line in lscontents for word in line)
    lscontents = {
        k.upper(): parse_lsstatements(v)
        for k, v in lsmajorblocksRE.findall(lscontents)
    }

    memstartsize = {
        k: (ld65parseint(v["start"]), ld65parseint(v["size"]))
        for k, v in lscontents["MEMORY"]
    }
    segtomem = {k: v["load"] for k, v in lscontents["SEGMENTS"]}
    return lscontents, memstartsize, segtomem

# Loading map.txt ###################################################

def ld65_map_get_sections(filename):
    with open(filename, "r", encoding="utf-8") as infp:
        lines = [line.rstrip() for line in infp]
    sectbreaks = [
        i - 1 for i, line in enumerate(lines)
        if len(line) >= 4 and not line.rstrip('-')
    ]
    sections = [lines[i:j] for i, j in zip(sectbreaks, sectbreaks[1:])]
    sections.append(lines[sectbreaks[-1]:])
    return {
        " ".join(s[0].rstrip(':').lower().split()): s[2:]
        for s in sections
    }

def main():
    lscontents, memstartsize, segtomem = ld65_load_linker_script(linkscriptname)
    mapsections = ld65_map_get_sections(mapoutputname)
    seglist = [
        line.split() for line in mapsections["name start end size align"] if line
    ]
    segsizes = [(line[0], int(line[3], 16)) for line in seglist]
    memtosegs = {k: [] for k in memstartsize}
    memcounts = dict.fromkeys(memstartsize, 0)
    for segment, size in segsizes:
        memname = segtomem[segment]
        memcounts[memname] += size
        memtosegs[memname].append(segment)

    ramsize = ramused = romsize = romused = poolsize = poolused = 0
    for m in lscontents["MEMORY"]:
        memname = m[0]
        if memname == 'HEADER': continue
        memstart, memsize = memstartsize[memname]
        memused = memcounts[memname]
        ispool = memname.startswith(("LINEAR", "TILEPOOL"))
        if ispool:
            poolsize += memsize
            poolused += memused
        isram = memstart < 0x8000 and not ispool
        if isram:
            ramsize += memsize
            ramused += memused
        else:
            romsize += memsize
            romused += memused
        print("%-16s %s at $%04X %6d/%6d (%4.1f%%), %6d free"
              % (memname, "RAM" if isram else "ROM", memstart,
                 memused, memsize, memused * 100.0 / memsize, memsize - memused))
        print("    " + ", ".join(memtosegs[memname]))
    print("Total RAM: %6d/%6d (%4.1f%%),%6d free"
          % (ramused, ramsize, ramused * 100.0 / ramsize, ramsize - ramused))
    print("Total ROM: %6d/%6d (%4.1f%%),%6d free"
          % (romused, romsize, romused * 100.0 / romsize, romsize - romused))
    print("BG pools (LINEAR, tile sharing): %6d free"
          % (poolsize - poolused))

if __name__=='__main__':
    main()
