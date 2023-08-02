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
"""
import sys, os, argparse
from collections import defaultdict, namedtuple
import textwrap

# ld65 debug file parsing, from hotbssvars.py #######################
#
# Keys in a "file" entry
# "id": used by lines to refer to this file
# "name": name of file in quotation marks
#
# Keys in a "line" entry
# "id": used by ??? to refer to this line of code
# "file": ID of file containing this line of code
# "line": line number
# "mtime": modification date as a UNIX timestamp
# "mod": +-separated list of translation units containing this file
# "span": +-separated list of spans that contain this line if any
#     (may be multiple if macros are involved)
#
# Keys in a "seg" entry
# "id": used by syms to refer to this segment
# "name": name of segment in quotation marks
# "oname": ROM file to which segment was written
# "ooffs": starting address in the ROM file if any
# "start": starting address in address space
# "size": size in bytes
# "type": "ro" for ROM, "rw" for RAM
#
# Keys in a "span" entry (things concatenated to make a segment;
#     don't know if they can overlap)
# "id": used by ??? to refer to this span
# "seg": ID of the section containing it
# "start": offset in some sense (from start of segment?)
# "size": size in bytes
#
# Keys in a "scope" entry
# "id":
# "mod": translation unit defining this scope
# "name": scope name in quotation marks, or "" for a TU's top level
# "type": scope, struct, or (absent)
# "parent": ID of enclosing scope if not top level
# "sym": ID of symbol if this is a .proc
# "span": spans related to this scope (don't know how .pushseg is treated)
# "size": ?
#
# Keys in a "sym" entry
# "id": used by other things to refer to this symbol
# "name": name of symbol in quotation marks
# "val": value of symbol
# "addrsize": size of address (zeropage, absolute, far)
# "seg": associated segment
# "type": "equ" for an equate, "lab" for a label, or "imp" for
#     something from another TU accessed via .import or .importzp
# "exp": If type=imp, the ID of the sym being imported
#     (a type=imp with no EXP is the unused __SIZE__ label of
#     a segment with define=yes)
# "scope": ID of a scope
# "def": ID of lines where defined (if used in a macro, this is
#     a +-separated list)
# "ref": +-separated list of lines where used (may be duplicates if
#     used in .rept)
# "size": size in bytes
#
# Keys in a "type" entry
# id and val, where val appears to be some hex bitfield

def parse_nvp_line(line):
    line = line.rstrip().split("\t", 1)
    symtype = line[0]
    props = (dict(tuple(item.split("=", 1)) for item in line[1].split(","))
             if len(line) > 1
             else {})
    return symtype, props

SymFile = namedtuple("DefDicts", [
    'filenames', 'linenums', 'syms', 'sym_refs', 'span_segs', 'segs',
    'scopes', 'modules', 'importcount'
])
FileLine = namedtuple("FileLine", [
    'fileid', 'linenum', 'spans'
])
Segment = namedtuple("Segment", [
    "name", "start", "size", "ooffs"
])
Sym = namedtuple("Sym", [
    "name", "val", "scope", 'seg', 'def_lines', 'ref_lines', 'size', 'type'
])
Scope = namedtuple("Scope", [
    "name", "parent", "spans", "mod"
])
TranslationUnit = namedtuple("TranslationUnit", [
    "name", "fileid"
])

def parse_symfile(lines):
    filenames = {}  # fileid -> str
    linenums = {}  # lineid -> (fileid, line number, spanid)
    syms = {}
    sym_refs = defaultdict(set)  # symid -> lineids
    # Each .segment creates a "span" (or "section fragment" as RGBASM
    # calls it).  The linker concatenates all spans of the same name
    # to form a segment.
    span_segs = {}  # spanid to segid
    segs = {}  # segid to Segment
    scopes = {}
    mods = {}
    importcount = defaultdict(int)

    for line in lines:
        symtype, props = parse_nvp_line(line)
        if symtype == 'file':
            filenames[int(props['id'])] = props['name'].strip('"')
        elif symtype == 'line':
            linenums[int(props['id'])] = FileLine(
                int(props['file']), int(props['line']),
                [int(x) for x in props['span'].split("+")]
                if 'span' in props
                else ()
            )
        elif symtype == 'seg':
            segs[int(props['id'])] = Segment(
                props['name'].strip('"'), 
                int(props['start'], 0), int(props['size'], 0),
                int(props['ooffs'], 0) if 'ooffs' in props else None
            )
        elif symtype == 'span':
            span_segs[int(props['id'])] = int(props['seg'])
        elif symtype == 'sym':
            name = props['name'].strip('"')
            symtype = props['type']
            if symtype == 'imp':
                importcount[name] += 1
                try:
                    symid = int(props['exp'])
                except KeyError:
                    continue  # unused __SIZE__ label of define=yes segment
            else:
                symid = int(props['id'])
                value = int(props["val"], base=0) if "val" in props else None
                scope = int(props['scope']) if 'scope' in props else None
                seg = int(props['seg']) if 'seg' in props else None
                size = int(props['size']) if 'size' in props else None
                def_lines = [int(x) for x in props["def"].split("+")]
                # Multiple def lines occur when macro uses .local or .scope
                ref_lines = props.get('ref')
                ref_lines = [int(x) for x in ref_lines.split("+")] if ref_lines else ()
                syms[symid] = Sym(name, value, scope, seg,
                                  def_lines, ref_lines, size, symtype)
            refs = props.get('ref', '')
            if refs: sym_refs[symid].update(int(x) for x in refs.split("+"))
        elif symtype == 'scope':
            if props.get('type') == 'struct': continue
            scopeid = int(props['id'])
            name = props['name'].strip('"')
            parent = int(props['parent']) if 'parent' in props else None
            spans = props.get('span', '')
            # empty spans means a scope containing no bytes
            spans = [int(x) for x in spans.split('+')] if spans else ()
            mod = int(props['mod'])
            scopes[scopeid] = Scope(name, parent, spans, mod)
        elif symtype == 'mod':  # a translation unit
            modid = int(props['id'])
            name = props['name'].strip('"')
            toplevelfile = int(props['file'])
            mods[modid] = TranslationUnit(name, toplevelfile)

    return SymFile(filenames, linenums, syms, sym_refs, span_segs, segs,
                   scopes, mods, importcount)

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
        symfile = parse_symfile(infp)

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
