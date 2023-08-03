#!/usr/bin/env python3
"""
Hot BSS Variables
Finds variables in BSS frequently accessed from CODE

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

Changelog:

2023-08-03 [Pino]
    separate ld65dbg to its own module
2023-08-02 [Pino]
    document dbg format; add ref, type, mod, and importcount
"""
import sys, os, argparse
from collections import defaultdict
import ld65dbg

helpText="Finds frequently accessed BSS variables in an ld65 debug symbol file."
helpEnd= ""

def parse_argv(argv):
    p = argparse.ArgumentParser(description=helpText, epilog=helpEnd)
    p.add_argument("dbgfile", help="path of debug symbol file")
    p.add_argument("-o", "--output", default='-',
                   help="path of debug symbol file to write")
    return p.parse_args(argv[1:])

def fmt_ref(line, symfile):
    # given a (file id, line number
    fileid, linenum = linenums[line]
    return "%s line %d in %s" % (filenames[fileid], linenum)

def main(argv=None):
    args = parse_argv(argv or sys.argv)
    with open(args.dbgfile, "r") as infp:
        symfile = ld65dbg.parse_symfile(infp)

    code_segid = bss_segid = None
    for segid, seg in symfile.segs.items():
        if seg.name == 'CODE': code_segid = segid
        if seg.name == 'BSS': bss_segid = segid

    bss_symid_to_code_lines = {}
    bss_val_to_symids = defaultdict(list)
    sym_refs_desc = sorted(symfile.sym_refs.items(),
                           key=lambda x: len(x[1]), reverse=True)
    dupes = defaultdict(set)
    for symid, refs in sym_refs_desc:
        sym = symfile.syms[symid]
        is_bss = sym.seg is not None and symfile.segs[sym.seg].name == 'BSS'
        if sym.seg == bss_segid:
            lineids = [
                lineid for lineid in refs
                if any(symfile.span_segs[spanid] == code_segid
                       for spanid in symfile.linenums[lineid].spans)
            ]
            if lineids:
                bss_symid_to_code_lines[symid] = lineids
                if symid not in bss_val_to_symids[sym.val]:
                    bss_val_to_symids[sym.val].append(symid)

    val_to_linecount = sorted(
        ((val, sum(len(bss_symid_to_code_lines[symid]) for symid in symids))
         for val, symids in bss_val_to_symids.items()),
        key=lambda x: x[1], reverse=True
    )
    out = []
    for val, linecount in val_to_linecount:
        refs_pl = "references" if linecount > 1 else "reference"
        out.append("$%04X: %d %s\n" % (val, linecount, refs_pl))
        for symid in bss_val_to_symids[val]:
            symlines = bss_symid_to_code_lines[symid]
            refs_pl = "references" if len(symlines) > 1 else "reference"
            symname = symfile.syms[symid].name
            out.append("    %s: %d %s\n" % (symname, len(symlines), refs_pl))
            filelines = [symfile.linenums[i] for i in symlines]
            filelines = sorted(
                (symfile.filenames[fl.fileid], fl.linenum)
                for fl in filelines
            )
            out.extend("        %s:%d\n" % row for row in filelines)

    if args.output == '-':
        sys.stdout.writelines(out)
    else:
        with open(args.output, "w") as outfp:
            outfp.writelines(out)

if __name__=='__main__':
    if 'idlelib' in sys.modules:
        main(["hotbssvars.py", "../mygame.dbg"])
    else:
        main()
