#!/usr/bin/env python3
"""
rmcomments.py
Removes comments from ca65 assembly language files

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

Removes comments from a set of ca65 assembly language files in the
./src folder.  This may be desired when counting source lines of code
or before giving the files to a third party to review.

Related recipes:

cat srcnocomments/MUSIC/famitone4.s src/*.* | sed '/^$/d' | wc -l
cat tools/*.py | sed '/^[[:space:]]*$/d' > all_py.txt
"""
import re, os, sys, errno, shutil

srcdir = "../src"
dstdir = "../srcnocomments"
subdirs = [".", "SFX", "MUSIC"]

# line comments in these files begin at any ; outside of a string
asm_suffixes = ('.s', '.inc')
# line comments in these files begin at a # that is the first
# non-whitespace character
hash_suffixes = (
    'actorclasses.txt', 'levelsections.txt', 'athlete_cards.txt',
    'transmissiondata.txt', '.strips',
)

already_public_files = set([
#    'init.s', 'nes.inc', 'pads.s', 'ppuclear.s', 'unrom.s',
])

precmtRE = re.compile(r"""
^(?:            # From start of line
[^;"'\n]+       # Match what does not begin a string or comment
|'[^']*'        # or a single quoted string
|"[^"]*"        # or a double quoted string
)*
""", re.VERBOSE)

def strip_asm_file(srcfilename, dstfilename):
    print("strip %s to %s" % (srcfilename, dstfilename))
    with open(srcfilename, 'r') as infp:
        lines = list(infp)
    out = []
    for line in lines:
        m = precmtRE.match(line)
        if m: line = m.group(0)
        out.append(line.rstrip() + "\n")
    with open(dstfilename, 'w') as outfp:
        outfp.writelines(out)

def strip_hash_file(srcfilename, dstfilename):
    print("strip %s to %s" % (srcfilename, dstfilename))
    with open(srcfilename, 'r') as infp:
        lines = list(infp)
    with open(dstfilename, 'w') as outfp:
        outfp.writelines(
            "\n" if line.lstrip().startswith('#') else line
            for line in lines
        )

def mkdir_p(dstdir):
    """Create a directory if it does not exist."""
    try:
        os.makedirs(dstdir)
    except OSError as e:
        if e.errno != errno.EEXIST or not os.path.isdir(dstdir):
            raise

def main():
    for subdir in subdirs:
        mkdir_p(os.path.join(dstdir, subdir))
        for filename in os.listdir(os.path.join(srcdir, subdir)):
            ext = filename.rsplit('.', 1)[-1]
            if ext.endswith('~'): continue
            srcpath = os.path.join(srcdir, subdir, filename)
            if not os.path.isfile(srcpath): continue
            dstpath = os.path.join(dstdir, subdir, filename)
            if filename in already_public_files:
                shutil.copyfile(srcpath, dstpath)
            elif filename.endswith(asm_suffixes):
                strip_asm_file(srcpath, dstpath)
            elif filename.endswith(hash_suffixes):
                strip_hash_file(srcpath, dstpath)
            else:
                shutil.copyfile(srcpath, dstpath)

if __name__=='__main__':
    main()
