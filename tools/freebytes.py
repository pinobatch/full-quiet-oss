#!/usr/bin/env python3
"""
This program counts how many free bytes are in the whole ROM.

Some data has to be in named memory areas, such as code and small
lookup tables used by code.  The last 16K of the ROM is an especially
important memory area called HOME, as it is always visible no matter
which banks are switched in.  Bulk data can be in a large contiguous
area that the HH86 and FQ linker scripts call LINEAR.  Creating a
named memory area takes 8 to 16 KiB away from LINEAR, but anything in
LINEAR can be redistributed to free space in a named memory area.
Near the end of HH86 development, for example, sprite cels were moved
to other memory area.

The ROM's level select screen shows estimates of free space in LINEAR
and HOME.  This program uses the linker script and the linker's map
output to estimate the free space in the whole ROM, even if things
were to be moved in or out of LINEAR or HOME.

1. Read memory area and segment assignments from linker script
2. Read segment sizes from map.txt
3. Calculate how much of each memory area is occupied

"""
import os, sys, argparse, re

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

def parse_argv(argv):
    p = argparse.ArgumentParser(description="Calculates free space by bank in a cc65 project.")
    p.add_argument("-C", "--config",
                   help="path to ld65 config file")
    p.add_argument("-m", "--mapfile",
                   help="path to map file written by ld65")
    return p.parse_args(argv[1:])

def main(argv=None):
    args = parse_argv(argv or sys.argv)
    lscontents, memstartsize, segtomem = ld65_load_linker_script(args.config)
    mapsections = ld65_map_get_sections(args.mapfile)
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
    if "idlelib" in sys.modules:
        main("""
./freebytes.py -C ../bnrom1mbit.cfg -m ../map.txt
""".split())
    else:
        main()
