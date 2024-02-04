#!/usr/bin/env python3
"""
nstripes.py
Stripe Image extractor

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

takes a 4-color indexed image
extracts unique tiles and Stripe Image from a file

keywords in the file (all dimensions in pixels)

stripe <name>
begins a cel

hrect <left> <top> <width> <height>
adds horizontal strips in this rectangle to this cel

vrect <left> <top> <width> <height>
adds vertical strips in this rectangle to this cel

rect <left> <top> <width> <height>
adds horizontal or vertical strips in this rectangle to this cel
(depending on the rectangle's shape)

dest <left> <top>
set the destination address on the nametable at which
the cel shall be drawn

fallthrough
don't emit $FF terminator at the end of this cel; instead,
combine this cel with the following cel

"""
import os, sys, argparse
from PIL import Image

def bytestotile(pxdata, width, x, y):
    rows = [pxdata[p:p + 8]
            for p in range(y * width + x, (y + 8) * width + x, width)]
    d1 = bytes(
        reduce(bitor, (((row[x] >> p) & 1) << (7 - x) for x in range(8)))
        for p in (0, 1)
        for row in rows
    )
    return d1

def bmptochr_colmajor(im):
    """Convert an indexed image to NES tiles, in rows top to bottom"""
    pxdata, w = im.tobytes(), im.size[0]
    return [
        bytestotile(pxdata, w, x, y)
        for x in range(0, w, 8)
        for y in range(0, im.size[1], 8)
    ]

def bmptochr_rowmajor_nonp(im):
    """Convert an indexed image to NES tiles, in rows top to bottom

(Fallback for when NumPy is not available)
"""
    pxdata, w = im.tobytes(), im.size[0]
    return [
        bytestotile(pxdata, w, x, y)
        for y in range(0, im.size[1], 8)
        for x in range(0, w, 8)
    ]

# For the common case
def bmptochr_rowmajor(im):
    """Convert an indexed image to NES tiles, in rows top to bottom

By Vanadium#6231 in the gbadev Discord server, 2023-01-18
License: "I consider it too short to be copyrightable; I disclaim copyright"
"""
    try:
        import numpy as np
    except ImportError:
        return bmptochr_rowmajor_nonp(im)
    # Convert to an array of 8x8 tiles of pixel data.
    pixels = np.array(im)
    height, width = pixels.shape
    tiles = (pixels.reshape(height//8, 8, width//8, 8)
             .swapaxes(1, 2)
             .reshape(-1, 8, 8))

    # Pack into NES format.
    bits = tiles[:,None] >> np.array([0, 1], np.uint8)[None,:,None,None]
    bits &= 1
    out = np.packbits(bits, axis=3).tobytes()
    return [out[x:x+16] for x in range(0, len(out), 16)]

def load_fix_tiles(filename, colmajor=False):
    """Load fix tiles from a file.

filename -- name of indexed image file or CHR file

Return a list of bytes-like objects each of length 16.
"""
    try:
        im = Image.open(filename)
    except OSError as e:
        # Assume it's raise OSError("cannot identify image file")
        # because older Pillow versions lack UnidentifiedImageError
        with open(filename, 'rb') as infp:
            data = infp.read()
        if len(data) % 16 != 0 or not 0 < len(data) <= 4096:
            raise
        data = [data[i:i + 16] for i in range(0, len(data), 16)]
    else:
        # Assume it's a 2-bit PNG
        if im.mode != 'P':
            raise ValueError("an indexed image file is required")
        data = bmptochr_colmajor(im) if colmajor else bmptochr_rowmajor(im)
    return data

NSTRIPE_RUN = 0x40
NSTRIPE_DOWN = 0x80

def ld65parseint(intval):
    if intval.startswith("$"): return int(intval[1:], 16)
    return int(intval, 0)

def parse_extra_tiles(s):
    firsttile, filename = s.split(":", 1)
    tileid = int(firsttile, 16)
    if not 0 <= tileid < 256:
        raise ValueError("firsttile %02X out of range (expected 00-FF)")
    return tileid, filename

def parse_argv(argv):
    p = argparse.ArgumentParser()
    p.add_argument("STRIPEFILE",
                   help="filename of coordinate spec")
    p.add_argument("CELIMAGE",
                   help="4-color indexed image containing all tiles")
    p.add_argument("CHRFILE", nargs="?",
                   help="filename to which CHR data is written")
    p.add_argument("ASMFILE", nargs="?",
                   help="filename to which ASM data is written")
    p.add_argument('--segment', default='RODATA',
                   help="ca65 segment in which to put stripe maps")
    p.add_argument("--base-tile", type=ld65parseint, default=0,
                   help="first tile number")
    p.add_argument("--fix-tiles", metavar="FILENAME",
                   help="force the first pattern table indices to the "
                        "first tiles in FILENAME (a .chr or 4-color PNG) "
                        " and include them in CHRFILE")
    p.add_argument("--extra-tiles", metavar="HEX:FILENAME", nargs='*',
                   type=parse_extra_tiles,
                   help="use extra tiles from FILENAME (a .chr or 4-color "
                        "PNG) at tile IDs starting at 0xHH "
                        "and do not include them in CHRFILE")
    return p.parse_args(argv[1:])

class StripeFileParser(object):
    def __init__(self, filename=None):
        # of the form
        # [[stripename, destx, desty,
        #   [(rectshape, left, top, width, height), ...]],
        #  ...]
        self.stripes = []
        self.errmsgs = []
        self.num_errs = 0
        self.linenum = 0
        if filename:
            with open(filename, "r", encoding="utf-8") as infp:
                self.extend(infp)

    def extend(self, it):
        for line in it:
            self.append(line)

    def append(self, line):
        self.linenum += 1
        line = line.strip()
        if line == '' or line.startswith('#'):
            return
        words = line.split()
        try:
            if words[0] == 'stripe':
                return self.append_stripe(words)
            if words[0] == 'dest':
                return self.append_dest(words)
            if words[0] == 'hrect':
                return self.append_hrect(words)
            if words[0] == 'vrect':
                return self.append_vrect(words)
            if words[0] == 'rect':
                return self.append_rect(words)
            if words[0] == 'fallthrough':
                return self.append_fallthrough()
        except Exception as e:
            self.errmsgs.append("%d: %s" % (self.linenum, e))
            self.num_errs += 1
            return
        self.errmsgs.append("%d: warning: unrecognized keyword %s"
                            % (self.linenum, words[0]))

    def append_stripe(self, words):
        stripename = words[1]
        self.stripes.append([stripename, 0, 0, [], False])

    @staticmethod
    def get_xywh(words):
        words = tuple(int(x) for x in words)
        if any(x % 8 for x in words):
            raise ValueError("coordinate must be multiples of 8 pixels")
        if words[0] < 0 or words[1] < 0:
            raise ValueError("top left must be non-negative")
        if words[2] < 8 or words[3] < 8:
            raise ValueError("width and height must be positive")
        return words

    def append_hrect(self, words):
        xywh = self.get_xywh(words[1:5])
        self.stripes[-1][3].append(('hrect',) + xywh)

    def append_vrect(self, words):
        xywh = self.get_xywh(words[1:5])
        self.stripes[-1][3].append(('vrect',) + xywh)

    def append_rect(self, words):
        xywh = self.get_xywh(words[1:5])
        keyword = 'vrect' if xywh[3] > xywh[2] else 'hrect'
        self.stripes[-1][3].append((keyword,) + xywh)

    def append_dest(self, words):
        xy = tuple(int(x) for x in words[1:3])
        if any(x % 8 for x in xy):
            raise ValueError("coordinate must be multiples of 8 pixels")
        self.stripes[-1][1:3] = xy

    def append_fallthrough(self):
        self.stripes[-1][4] = True

def extract_stripe(tiles, destx, desty, rects):
    """Extract a Stripe Image cel from an image.

Return a list in the form
[(x tile pos, y tile pos, NSTRIPE_DOWN, [tile, ...]), ...]
"""
    if not rects: return []
    srcleft = min(x[1] for x in rects)
    srctop = min(x[2] for x in rects)
    destx, desty = (destx - srcleft) >> 3, (desty - srctop) >> 3
    out = []
    for direction, l, t, w, h in rects:
        l, t, w, h = l >> 3, t >> 3, w >> 3, h >> 3
        if t + h > len(tiles):
            raise ValueError("%s %d %d %d %d: bottom %d exceeds height %d pixels"
                             % (direction, l * 8, t * 8, w * 8, h * 8,
                                (t + h) * 8, len(tiles) * 8))
        if l + w > len(tiles[0]):
            raise ValueError("%s %d %d %d %d: right %d exceeds width %d pixels"
                             % (direction, l * 8, t * 8, w * 8, h * 8,
                                (l + w) * 8, len(tiles[0]) * 8))
        if direction == 'hrect':
            for y in range(t, t + h):
                out.append((destx + l, desty + y, 0,
                            tiles[y][l:l + w]))
        elif direction == 'vrect':
            for x in range(l, l + w):
                out.append((destx + x, desty + t, NSTRIPE_DOWN,
                            [tiles[y][x] for y in range(t, t + h)]))
    return out
                
def ca65_bytearray(s):
    s = ['  .byte ' + ','.join(str(ch) for ch in s[i:i + 16])
         for i in range(0, len(s), 16)]
    return '\n'.join(s)

def ca65_addrarray(s):
    s = ['  .addr ' + ','.join(str(ch) for ch in s[i:i + 4])
         for i in range(0, len(s), 4)]
    return '\n'.join(s)

def main(argv=None):
    args = parse_argv(argv or sys.argv)
    if args.extra_tiles:
        print("note: extra tiles:", args.extra_tiles, file=sys.stderr)

    # Load the stripe spec
    parsed = StripeFileParser(args.STRIPEFILE)
    if parsed.errmsgs:
        print("\n".join("%s: %s" % (args.STRIPEFILE, x)
                        for x in parsed.errmsgs),
              file=sys.stderr)
        if parsed.num_errs > 0:
            exit(1)

    # Load constant tile data
    fix_tiles = []
    if args.fix_tiles: fix_tiles.extend(load_fix_tiles(args.fix_tiles))
    itiles = {t: i + args.base_tile for i, t in enumerate(fix_tiles)}
    all_extra_tiles = {}
    for extra_tile_id, filename in (args.extra_tiles or []):
        extra_tiles = load_fix_tiles(filename)
        if len(extra_tiles) + extra_tile_id > 0x100:
            raise ValueError("%s: extra tiles %02X-%02X extend past 0x100"
                             % (filename, extra_tile_id,
                                len(extra_tiles) + extra_tile_id - 1))
        all_extra_tiles.update(
            (t, i + extra_tile_id) for i, t in enumerate(extra_tiles)
        )

    # Load the image as tile data
    im = Image.open(args.CELIMAGE)
    im.load()
    if im.mode != 'P':
        print("nstripes.py: %s: mode is %s (expected indexed)"
              % (args.CELIMAGE, im.mode))
        exit(1)
    if any(x % 8 for x in im.size):
        print("nstripes.py: %s: size is %sx%s (expected multiple of 8x8)"
              % (args.CELIMAGE, *im.size))
        exit(1)
    impitch = im.size[0] // 8
    tiles = bmptochr_rowmajor(im)
    im.close()
    tiles = [tiles[i:i + impitch] for i in range(0, len(tiles), impitch)]

    # Extract stripes from the image
    stripedatas = []
    for stripename, destx, desty, rects, fallthrough in parsed.stripes:
        rawstripedata = extract_stripe(tiles, destx, desty, rects)
        stripedata = bytearray()
        for x, y, direction, stripetiles in rawstripedata:
            addr = 0x2000 + 32 * (y % 30) + (x % 32)
            direction |= len(stripetiles) - 1

            tilenums = []
            for tile in stripetiles:
                try:
                    tile = all_extra_tiles[tile]
                except KeyError:
                    tile = itiles.setdefault(tile, len(itiles) + args.base_tile)
                tilenums.append(tile)
            if (len(tilenums) > 1
                and all(x == tilenums[0] for x in tilenums)):
                direction |= NSTRIPE_RUN
                del tilenums[1:]
            row = bytearray([addr >> 8, addr & 0xFF, direction])
            row.extend(tilenums)
            stripedata.extend(row)
        if not fallthrough:
            stripedata.append(0xFF)
        stripedatas.append((stripename, stripedata))

    if args.CHRFILE:
        # Uninvert and write tile data
        tiles = list(fix_tiles)
        tiles.extend([None] * (len(itiles) - len(fix_tiles)))
        for t, i in itiles.items(): tiles[i - args.base_tile] = t
        if None in tiles:
            print("tiles has None at $%02X" % tiles.index(None),
                  file=sys.stderr)
        with open(args.CHRFILE, "wb") as outfp:
            outfp.writelines(tiles)

    sumline = ("%s: %d tiles, %d stripe maps totaling %d bytes"
               % (args.STRIPEFILE, len(itiles), len(stripedatas),
                  sum(len(x[1]) for x in stripedatas)))
    if args.ASMFILE:
        lines = [
            '; Generated by nstripes.py',
            '; '+ sumline,
            '.segment "%s"' % args.segment,
        ]
        for sn, sd in stripedatas:
            lines.append(".export NSTRIPE_%s" % sn)
        for sn, sd in stripedatas:
            lines.append("NSTRIPE_%s:" % sn)
            lines.append(ca65_bytearray(sd))
        with open(args.ASMFILE, "w", encoding="utf-8") as outfp:
            outfp.writelines(x + "\n" for x in lines)
    else:
        print(sumline)
    

if __name__=="__main__":
    if "idlelib" in sys.modules:
        main("""
tools/nstripes.py
  --segment R8_PDA --fix-tiles ../tilesets/pda/commontiles.png
  ../tilesets/pda/border.nstr ../tilesets/pda/border.png
  test.chr test.asm
""".split())
    else:
        main()
