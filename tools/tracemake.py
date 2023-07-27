#!/usr/bin/env python3
"""
freebytes.py
Uses strace on Linux to see what files are read and written

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
import os, sys, subprocess, shlex, re, time

TOOLSDIR = os.path.dirname(os.path.abspath(sys.argv[0]))
BASEDIR = os.path.normpath(os.path.join(TOOLSDIR, ".."))
LOGNAME = os.path.join(BASEDIR, "stracelog.txt")
ignore_folders = ("/lib/", "/usr/", "/etc/")

def run_program():
    # Disable parallel make, whose strace output confuses this
    # program's developer. Speed and concurrency are irrelevant to
    # the task of determining which files the build doesn't need.
    cmd = """strace -f -e 't=file' make -j1 mygame.nes"""
    ##cmd = """make fq.nes stats"""
    result = subprocess.run(
      shlex.split(cmd),
      capture_output=True, text=True, cwd=BASEDIR
    )
    print("return code was", result.returncode)
    print("stdout was")
    print(result.stdout[:2000])
    print("stderr was %d bytes including strace logs:" % len(result.stderr))
    print(result.stderr[:2000])
    with open(LOGNAME, "w", encoding="utf-8") as outfp:
        outfp.write(result.stderr)

# Need to split this into two regular expressions because of how
# Python handles recurring groups

loglineRE = re.compile(r"""
(?:\[pid\s+[0-9]+\]\s*)?  # PID (ignored)
([a-zA-Z_][a-zA-Z0-9]*)   # function name
\s*\(\s*                  # open paren
(.*?)                     # all arguments, separated by commas
(?:\s*\/\*.*?\*\/)?       # Ignore "/* 55 vars */"
\)\s*=\s*                 # Close paren
""", re.VERBOSE)
print_malformed_loglines = False

exitedRE = re.compile(r"""
(?:\[pid\s+[0-9]+\]\s*)?  # parent PID (ignored)
(?:\+\+\+|---)            # --- is start of child; +++ is end of child
""", re.VERBOSE)

argsRE = re.compile(r"""
([a-zA-Z0-9_|]+|".*?"|{.*?}|\[.*?\])
""", re.VERBOSE)

def analyze_log():
    if False:
        msg = """execve("/usr/bin/python3", ["python3", "tools/mtcv.py", "maps/DF/DF_B5_7B.maps", "obj/nes/DF_B5_7B.fqmap"], 0x5636cfc0ae50 /* 55 vars */) = 0
"""
        m = loglineRE.match(msg)
        print(m.groups())
        return
    if False:
        msg = """[pid 61484] --- SIGCHLD {si_signo=SIGCHLD, si_code=CLD_EXITED, si_pid=61485, si_uid=1000, si_status=0, si_utime=140, si_stime=3} ---
"""
        m = exitedRE.match(msg)
        print(m.groups())
        return
    with open(LOGNAME, "r", encoding="utf-8") as infp:
        stderr = [x.rstrip() for x in infp]
    readfiles, readfolders, writtenfiles = set(), set(), set()
    for line in stderr:

        if line.startswith("strace: Process"): continue
        if exitedRE.match(line): continue
        m = loglineRE.match(line)
        if not m:
            if print_malformed_loglines:
                print("MALFORMED LINE", line)
            continue

        callname, args = m.groups()
        allargs = argsRE.split(args)
        if (len(allargs) % 2 != 1
                or allargs[0].strip() or allargs[-1].strip()
                or not all(x.strip() == ',' for x in allargs[2:-2:2])):
            print("MALFORMED START/FINISH", args)
            continue
        allargs = allargs[1:-1:2]
        
        if callname == 'openat':
            if (allargs[0] != 'AT_FDCWD'):
                print("strange openat", line)
                continue
            filename = allargs[1].strip('"')
            if filename.startswith(ignore_folders): continue
            if '/__pycache__/' in filename: continue
            if filename.startswith(".."):
                print("traversal to %s" % filename, file=sys.stderr)
            filename = os.path.normpath(os.path.join(BASEDIR, filename))
            modes = allargs[2].split("|")
            if 'O_DIRECTORY' in modes and 'O_RDONLY' in modes:
                readfolders.add(filename)
                continue
            if 'O_RDWR' in modes:
                if filename not in writtenfiles:
                    readfiles.add(filename)
                    writtenfiles.add(filename)
                continue
            if 'O_RDONLY' in modes:
                readfiles.add(filename)
                continue
            if 'O_WRONLY' in modes:
                writtenfiles.add(filename)
                continue
            print("unexpected openat", allargs[1], modes, file=sys.stderr)
        elif callname == 'chdir':
            dirname = allargs[0].strip('"')
            if dirname != BASEDIR:
                print("unexpected chdir %s" % dirname, file=sys.stderr)
        elif callname in (
                'newfstatat', 'stat', 'access', 'getcwd', 'readlink',
                'execve', 'unlink', 'utimensat',
            ):
            continue  # Ignoring these syscalls
        else:
            print("unknown call", callname, args)
            time.sleep(0.05)
    del stderr[:]

    print("%d files read, %d files written"
          % (len(readfiles), len(writtenfiles)))
    print("%d files read ONLY, %d files written ONLY"
          % (len(readfiles.difference(writtenfiles)),
             len(writtenfiles.difference(readfiles))))
    print("keeping those beginning with", BASEDIR)

    with open("zip-minimal.in", "w", encoding="utf-8") as outfp:
        outfp.writelines(
            s[len(BASEDIR) + 1:] + "\n"
            for s in sorted(readfiles.difference(writtenfiles))
            if s.startswith(BASEDIR) and os.path.isfile(s)
        )

if __name__=='__main__':
    run_program()
    analyze_log()
