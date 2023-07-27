#!/usr/bin/env python3
"""
strips.py
Sprite sheet extractor for use with metasprite.s

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
import re
import textwrap
from collections import Counter, defaultdict, namedtuple
import os
import sys
import argparse
from PIL import Image, ImageDraw
from pilbmp2nes import pilbmp2chr
import solve_overload

colorRE = re.compile('#([0-9a-fA-F]+)$')
Cel = namedtuple("Cel", "strips linenum l t w h hotx hoty hflip insubset")
CelStrip = namedtuple("CelStrip", "palette l t w h padw padh dstx dsty")

def parse_color(s):
    m = colorRE.match(s)
    if m:
        hexdigits = m.group(1)
        if len(hexdigits) == 3:
            return tuple(int(c, 16) * 17 for c in hexdigits)
        elif len(hexdigits) == 6:
            return tuple(int(hexdigits[i:i + 2], 16) for i in range(0, 6, 2))
        else:
            return None
    return None

def parseintorhex(s):
    if s.startswith('$'):
        return int(s[1:], 16)
    elif s.startswith(('0x', '0X')):
        return int(s[2:], 16)
    else:
        return int(s)

def find_related_sets(allnames, pairs):
    """Partition a graph into its connected sets.

allnames -- iterable of hashable node identifiers (such as strings)
pairs -- iterable of 2-sequences of connected node identifiers

Return a dict from node names to sets of connected nodes.
Values in the same set will have object identity (a is b).

"""
    allnames = {s: {s} for s in allnames}
    for a, b in pairs:
        if a == b: continue
        aset, bset = allnames[a], allnames[b]
        if not aset.isdisjoint(bset):
            raise ValueError(
                "related cycle involving %s and %s"
                % (repr(sorted(aset)), repr(sorted(bset)))
            )
        if len(aset) < len(bset):
            aset, bset = bset, aset
        aset.update(bset)
        for s in bset:
            allnames[s] = aset
    return allnames

class StripsFileReader(object):

    def __init__(self, iterable=None, verbose=False):
        self.framenames = []
        self.frames = {}
        self.cur_frame = self.cur_framename = 0
        self.backdrop = self.backdrop_linenum = None
        self.palettes = {}
        self.relatedframes = []
        self.lookuptables = {}
        self.flags = {}
        self.actionpoints = {}
        self.lutaliases = {}
        self.cur_frame_flags = {}
        self.linenum = 0
        self.verbose = verbose
        self.framenumaliases = []
        self.hflipped = False
        if iterable is not None:
            self.extend(iterable)

    def append(self, line):
        if isinstance(line, str):
            line = line.split()
        linenum = self.linenum = self.linenum + 1

        # Ignore blank lines and comments
        if not line or line[0].startswith('#'):
            return

        # Handle predefined keywords
        try:
            handler = self.appendhandlers[line[0]]
        except KeyError:
            pass
        else:
            return handler(self, line)

        # Handle attributes
        try:
            tablename = self.lutaliases[line[0]]
        except KeyError:
            pass
        else:
            tablevalue = parseintorhex(line[1])
            self.lookuptables[tablename][0][-1] = tablevalue
            self.apply_flags_to_current_frame()
            return

        # Handle flags, more than one of which to a line
        try:
            self.flags[line[0]]
        except KeyError:
            pass
        else:
            for flagname in line:
                tablename, flagvalue = self.flags[flagname]
                self.cur_frame_flags[tablename] |= flagvalue
                self.apply_flags_to_current_frame()
            return

        # Handle action point
        try:
            apvalue = self.actionpoints[line[0]]
        except KeyError:
            pass
        else:
            apvalue[0][-1] = (int(line[1]), int(line[2]))
            return
        
        print("warning: ignoring unknown keyword %s" % line[0], file=sys.stderr)

    def extend(self, lines):
        for line in lines:
            self.append(line)

    def guess_bounding_boxes(self):
        for name, f in list(self.frames.items()):
            strips = f[0]
            l, t, w, h = f[2:6]
            if (len(strips) == 0
                and (l is None or t is None or w is None or h is None)):
                raise ValueError("frame %s without strips needs explicit bounding box (try 0 0 8 8)"
                                 % name)

            # Guess based on union of bounding boxes
            if l is None:
                l = min(row.dstx for row in strips)
            if t is None:
                t = min(row.dsty for row in strips)
            if w is None:
                w = max(row.dstx + row.w for row in strips) - l
            if h is None:
                h = max(row.dsty + row.h for row in strips) - t
            f = f._replace(l=l, t=t, w=w, h=h)
            hotx, hoty = self.guess_hotspot(f)
            self.frames[name] = f._replace(hotx=hotx, hoty=hoty)

    def calc_actionpoints(self):
        # Action points are specified relative to sprite sheet
        # but should be stored relative to the hotspot.
        for apoints, xtablename, ytablename in self.actionpoints.values():
            xtable, ytable = [], []
            frames = (self.frames[i] for i in self.framenames)
            for f, ap in zip(frames, apoints):
                hx, hy = f[6:8]
                if ap is not None:
                    apx, apy = ap[0] - hx, ap[1] - hy
                    if self.hflipped:
                        apx = -apx
                else:
                    apx, apy = -128, -128
                xtable.append(apx)
                ytable.append(apy)
            if xtablename:
                self.lookuptables[xtablename][0][:] = xtable
            if ytablename:
                self.lookuptables[ytablename][0][:] = ytable

    # Below are not public APIs

    def append_hflip(self, line):
        self.hflipped = True

    def append_backdrop(self, line):
        if self.backdrop_linenum is not None:
            raise ValueError("backdrop color already defined on line %d"
                             % (self.cur_framename, self.backdrop_linenum))
        backdrop = parse_color(line[1])
        if backdrop is None:
            raise ValueError("%s is not a color" % line[1])
        self.backdrop, self.backdrop_linenum = backdrop, self.linenum

    def append_palette(self, line):
        curpalnum = int(line[1])
        paldata = []
        for palspec in line[2:]:
            palspec = palspec.split('=', 1)
            colornum = (int(palspec[1])
                        if len(palspec) > 1
                        else len(paldata) + 1)
            rgb = parse_color(palspec[0])
            if rgb is None:
                raise ValueError("%s is not a color" % palspec[0])
            paldata.append((rgb, colornum))
        self.palettes[curpalnum] = paldata

    @staticmethod
    def parse_repeats(line):
        # repeats otherframename
        # repeats otherframename dl dt
        other_framename = line[1]
        offset = line[2:4]
        if len(offset) not in (0, 2):
            raise ValueError("repeats with offset takes 2 arguments")
        if offset:
            offset = tuple(int(x) for x in offset)
        else:
            offset = (0, 0)
        return other_framename, offset

    def add_frame_strips(self, other_framename, offset):
        other_frame = self.frames[other_framename]
        for strip in other_frame[0]:
            newstrip = strip._replace(
                l=strip.l + offset[0], t=strip.t + offset[1],
                dstx=strip.dstx + offset[0], dsty=strip.dsty + offset[1]
            )
            self.cur_frame[0].append(newstrip)
        if not any(offset):
            self.relatedframes.append((other_framename, self.cur_framename))

    def append_repeats(self, line):
        other_framename, offset = self.parse_repeats(line)
        self.add_frame_strips(other_framename, offset)

    @staticmethod
    def guess_hotspot(frame):
        """Move the hotspot to bottom center if it isn't already specified."""
        l, t, w, h, hotx, hoty = frame[2:8]
        if hotx is None and l is not None and w is not None:
            hotx = l + w // 2
        if hoty is None and t is not None and h is not None:
            hoty = t + h
        return hotx, hoty

    def append_frame(self, line):
        # frame framename repeats otherframename
        # frame framename repeats otherframename dl dt
        # frame framename l t w h
        # The of a frame is
        # 0. striplist 1. source line number; 2-5. l t w h;
        # 6-7. hotspot; 8. hflipped; 9. subset
        self.cur_framename = line[1]

        try:
            oldframe = self.frames[self.cur_framename]
        except KeyError:
            pass
        else:
            raise ValueError("frame %s already defined on line %d"
                             % (self.cur_framename, oldframe[1]))

        # A frame can repeat the cel in another frame
        if len(line) > 2 and line[2] == 'repeats':
            other_framename, offset = self.parse_repeats(line[2:])
            other_frame = self.frames[other_framename]
            newclipl = (
                other_frame.l + offset[0]
                if other_frame.l is not None
                else None
            )
            newclipt = (
                other_frame.t + offset[1]
                if other_frame.t is not None
                else None
            )
            newhotx = (
                other_frame.hotx + offset[0]
                if other_frame.hotx is not None
                else None
            )
            newhoty = (
                other_frame.hoty + offset[1]
                if other_frame.hoty is not None
                else None
            )
            self.cur_frame = other_frame._replace(
                strips=[], linenum=self.linenum,
                l=newclipl, t=newclipt, hotx=newhotx, hoty=newhoty
            )
            self.add_frame_strips(other_framename, offset)

        else:
            if len(line) >= 6:
                l, t, w, h = (int(x) for x in line[2:6])
            else:
                l = t = w = h = None
            self.cur_frame = Cel(
                [], self.linenum,
                l, t, w, h,
                None, None, self.hflipped, False
            )

        self.framenames.append(self.cur_framename)
        self.frames[self.cur_framename] = self.cur_frame
        for tname, v in self.lookuptables.items():
            self.cur_frame_flags[tname] = 0
            v[0].append(0)
        for v in self.actionpoints.values():
            v[0].append(None)

    def append_aka(self, line):
        self.framenumaliases.append((line[1], len(self.framenames) - 1))

    def append_strip(self, line):
        # strip pal(,pal)*
        # strip pal(,pal)* l t w h
        # strip pal(,pal)* l t w h at dstx dsty
        line = list(line)
        palettes = [int(x) for x in line[1].split(",")]
        cliprect = self.cur_frame[2:6]
        ltwh = line[2:6] if len(line) >= 6 else cliprect
        if any(x is None for x in ltwh):
            raise ValueError("%s: no cliprect nor strip rect"
                             % (self.framenames[-1],))

        # If "at x y", then copy pixels from a source rectangle
        # and put it at the destination rectangle, ignoring
        # the cel's clipping rectangle if any.
        if len(line) >= 9 and line[6] == 'at':
            dstx, dsty = (int(x) for x in line[7:9])
            cliprect = None, None, None, None
        else:
            dstx = dsty = None

        # Clip strip to cel cliprect if applicable
        sl, st, sw, sh = ltwh = tuple(int(x) for x in ltwh)
        if sw <= 0:
            raise ValueError("%s: strip %s width is not positive"
                             % (self.framenames[-1], ltwh))
        if sh <= 0:
            raise ValueError("%s: strip %s height is not positive"
                             % (self.framenames[-1], ltwh))
        cl, ct, cw, ch = cliprect

        padw = padh = 0
        if cl is not None and sl < cl:  # Clip on left
            if sl + sw <= cl:
                raise ValueError("%s: strip %s entirely to left of clip rect %s"
                                 % (self.framenames[-1], ltwh, cliprect))
            padw = cl - sl
            sw -= padw
            sl = cl
        if ct is not None and st < ct:  # Clip on top
            if st + sh <= ct:
                raise ValueError("%s: strip %s entirely above clip rect %s"
                                 % (self.framenames[-1], ltwh, cliprect))
            padh = ct - st
            sh -= padh
            st = ct
        if cw is not None:  # Clip on right
            if cl + cw <= sl:
                raise ValueError("%s: strip %s entirely to right of clip rect %s"
                                 % (self.framenames[-1], ltwh, cliprect))
            sw = min(sw, cl + cw - sl)
        if ch is not None:  # Clip on bottom
            if ct + ch <= st:
                raise ValueError("%s: strip %s entirely below clip rect %s"
                                 % (self.framenames[-1], ltwh, cliprect))
            sh = min(sh, ct + ch - st)
        padh = padh % 16
        padw = padw % 8

        # Move the strip if necessary
        if dstx is None:
            dstx = sl - padw
        if dsty is None:
            dsty = st - padh

        assert sh >= 0 and sw >= 0
        self.cur_frame[0].extend(
            CelStrip(
                palette, sl, st, sw, sh, padw, padh, dstx, dsty
            ) for palette in palettes
        )

    def append_related(self, line):
        # related otherframename
        # Related frames are kept in the same CHR bank.
        # These can be frames known to share many tiles, or
        # particles used with a particular frame.
        self.relatedframes.extend((other_framename, self.cur_framename)
                                  for other_framename in line[1:])

    def replace_hotspot(self, hotx, hoty):
        self.cur_frame = self.cur_frame._replace(hotx=hotx, hoty=hoty)
        self.frames[self.cur_framename] = self.cur_frame

    def append_hotspot(self, line):
        # hotspot xxx yyy
        # Hotspot defaults to bottom center but can be overridden
        hotx, hoty = (int(x) for x in line[1:3])
        self.replace_hotspot(hotx, hoty)

    def append_subset(self, line):
        # subset
        # Frames with subset are added to banks before frames
        # without.
        self.cur_frame = self.cur_frame._replace(subset=True)
        self.frames[self.cur_framename] = self.cur_frame
        self.cur_frame[9] = True

    def append_table(self, line):
        # table nameoftable
        # table nameoftable in MOVEDATA
        # Declare a lookup table and fill it with zeroes for existing frames
        tablename = line[1]
        try:
            oldvalue = self.lookuptables[tablename]
        except KeyError:
            pass
        else:
            raise ValueError("table %s already declared on line %d"
                             % (tablename, oldvalue[1]))

        segment = line[3] if len(line) > 3 else None
        defaultvalue = 0  # TODO: implement prepositions

        # add values for already seen frames
        zeroes = [defaultvalue] * len(self.frames)
        self.lookuptables[tablename] = (zeroes, self.linenum, segment, 0)
        self.cur_frame_flags[tablename] = 0

    def append_flag(self, line):
        # flag nameofflag 0x80 in nameoftable
        # If nameofflag is used in a frame, the value for that frame
        # in the given table is OR'd with the given value.
        flagname = line[1]
        flagvalue = line[2]
        tablename = line[4]
        self.flags[flagname] = (tablename, parseintorhex(flagvalue))

    def append_actionpoint(self, line):
        # actionpoint fist in xtablename ytablename
        # actionpoint fist in - ytablename
        # actionpoint fist in xtablename -
        # Sets an action point, a point specified on the sprite sheet
        # stored in tables as an (x, y) offset from the frame's
        # hotspot.  A hyphen means this coordinate doesn't go in
        # a table.
        apname = line[1]
        xname = line[3]
        yname = line[4]
        self.actionpoints[apname] = (
            [None] * len(self.frames),
            xname if xname != '-' else None,
            yname if yname != '-' else None
        )

    def append_attribute(self, line):
        # attribute attrname in tablename
        atname = line[1]
        tablename = line[3]
        self.lutaliases[atname] = tablename

    def apply_flags_to_current_frame(self):
        for tablename, flagvalue in self.cur_frame_flags.items():
            self.lookuptables[tablename][0][-1] |= flagvalue

    def append_align(self, line):
        num, den = len(self.frames), int(line[1])
        remainder = num % den
        if remainder:
            raise ValueError("%d does not divide frame count %d after %s (remainder %d)"
                             % (den, num, self.cur_framename, remainder))

    appendhandlers = {
        'backdrop': append_backdrop,
        'palette': append_palette,
        'table': append_table,
        'hflip': append_hflip,
        'frame': append_frame,
        'repeats': append_repeats,
        'strip': append_strip,
        'related': append_related,
        'hotspot': append_hotspot,
        'flag': append_flag,
        'attribute': append_attribute,
        'actionpoint': append_actionpoint,
        'aka': append_aka,
        'subset': append_subset,
        'align': append_align,
    }


def quantizetopalette(src, palette, dither=False):
    """Convert an RGB or L mode image to use a given P image's palette.

Pillow 9 broke the original implementation based on `quantize()`
from `PIL/Image.py`, which relied on internal interfaces.
Replaced with a wrapper around a Pillow 6 addition.
Reference: https://stackoverflow.com/a/29438149/2738262
"""
    return src.quantize(palette=palette, dither=1 if dither else 0)

def makestrippaletteimg(backdrop, dstpalettes):
    """Make an image with the RGB values in the strips file's palette command."""
    sz = (max(len(x) for x in dstpalettes.values()) + 1,
          max(dstpalettes.keys()) + 1)
    im = Image.new('RGB', sz, backdrop)
    for y, colors in dstpalettes.items():
        for x, (rgb, mapto) in enumerate(colors):
            im.putpixel((x, y), rgb)
    return im

def makecelpalettemap(backdrop, dstpalettes, celim):
    """Make a map from cel image colors to palette indices."""

    # Fill all colors past the last used one with backdrop, so that
    # quantizetopalette can't just fill the rest with a gray ramp
    # and then quantize existing colors to that gray ramp
    maxpx = max(celim.tobytes())
    p = celim.getpalette()[:3 * (maxpx + 1)]
    p.extend(backdrop * (255 - maxpx))
    celimcopy = celim.copy()
    celimcopy.putpalette(p)

    # Find the closest color in the input image's palette
    # to each image in the strip's palette
    palim = makestrippaletteimg(backdrop, dstpalettes)
    px = quantizetopalette(palim, celimcopy).load()
    backdropindex = px[palim.size[0] - 1, 0]
    del celimcopy, palim

    # And arrange this as a set of mapping functions for
    # celim.point()
    outmaps = {}
    for y, colors in dstpalettes.items():
        mapping = [0]*256
        for x, (rgb, mapto) in enumerate(colors):
            mapping[px[x, y]] = mapto
        outmaps[y] = mapping
    return outmaps

def draw_strips_on(im, frames, actionpoints, strip_colors):
    imrgb = im.convert("RGB")
    dc = ImageDraw.Draw(imrgb)
    totaltiles = 0
    scpopularity = {i: 0 for i in range(len(strip_colors))}
    for frame in frames:
        strips = frame[0]
        for s in reversed(strips):
            spal, sl, st, sw, sh, padw, padh, dstx, dsty = s
            if spal >= len(strip_colors):
                raise ValueError("invalid strip palette %d" % spal)
            totaltiles += (-(sw + padw) // 8) * (-(sh + padh) // 16)
            scpopularity[spal] += 1
            sc = strip_colors[spal]
            dc.rectangle((sl, st, sl+sw-1, st+sh-1), outline=sc)

    # Try to find a hotspot color that contrasts with the box colors
    # in order to draw the hotspots
    spal = min(scpopularity.items(), key=lambda item: item[1])[0]
    sc = strip_colors[spal]
    for frame in frames:
        hx, hy = frame[6:8]
        dc.ellipse([(hx-1, hy-1), (hx+1, hy+1)], outline=sc)

    for apoints in actionpoints.values():
        # each apoints value is a 3-tuple:
        # list of 2-tuples, one for each frame
        # X coordinate table
        # Y coordinate table
        for f, ap in zip(frames, apoints[0]):
            if ap is None:
                continue
            # Draw X on action points and a line to the hotspot
            hx, hy = f[6:8]
            apx, apy = ap
            dc.line([(apx-1, apy-1), (apx+1, apy+1)], fill=sc)
            dc.line([(apx+1, apy-1), (apx-1, apy+1)], fill=sc)
            dc.line([(apx, apy), (hx, hy)], fill=sc)

    return imrgb, totaltiles

def make_fake_palette(backdrop):
    testpal = list(backdrop)
    testpal.extend([0, 0, 0, 170, 170, 170, 255, 255, 255])
    return testpal * 64

def collect_strip_tiles(frames, srcims):
    """

srcims is the image remapped to each palette

Return a 4-tuple (out, stripmap, hstripmap, totaltiles).
out is an image containing tile data
stripmap is a list of how many tiles are seen by the time of each strip
hstripmap is a list of (x, y, color, width) of each horizontal strip
totaltiles is the total number of tiles in out that contain data

"""

    expectedtiles = [
        sum((-strip[3] // 8) * (-strip[4] // 16) for strip in frame[0])
        for frame in frames
    ]
##    print("frame strip lists:", [frame[0] for frame in frames])
##    print("expected tiles:", expectedtiles)
    totaltiles = sum(expectedtiles)
    w = 128
    h = -(-totaltiles // 16) * 16
    out = Image.new('P', (w, h), 0)
    out.putpalette(make_fake_palette((0, 204, 255)))
    tilessofar = 0
    stripmap = []
    hstripmap = []
    
    for frame in frames:
        stripmap.append(tilessofar)
        framestrips = []
##        print("Appending frame", frame)
        l, t, w, h, hotx, hoty = frame[2:8]

        for strip in frame[0]:
            spal, sl, st, sw, sh, padw, padh, dstx, dsty = strip
            assert sw > 0 and sh > 0
            try:
                srcim = srcims[spal]
            except KeyError:
                raise ValueError("palette %d not defined" % spal)
            # (prx, pry) is tile location relative to the strip+padding
            for pry in range(0, sh + padh, 16):
                # The top of the output strip is srcboxtop
                # it contains pixels from srctop to srcbottom
                srcboxtop = pry + st - padh
                dstboxtop = dsty + pry
                srctop = max(st, srcboxtop)
                srcbottom = min(srcboxtop + 16, st + sh + padh)

                for prx in range(0, sw + padw, 8):
                    srcboxleft = prx + sl - padw
                    srcleft = max(sl, srcboxleft)
                    srcright = min(srcboxleft + 8, sl + sw + padw)
                    srcrect = (srcleft, srctop, srcright, srcbottom)
##                    print("  with srcrect", srcrect)

                    tdstx = (tilessofar % 16) * 8 + (srcleft - srcboxleft)
                    tdsty = (tilessofar // 16) * 16 + (srctop - srcboxtop)
                    out.paste(srcim.crop(srcrect), (tdstx, tdsty))
                    tilessofar += 1

                # Sprite cels are centered about the bottom center
                tiles_in_strip = -(-(sw + padw) // 8)
                assert tiles_in_strip > 0
                framestrips.append((
                    dstx - hotx, dstboxtop - hoty, spal, tiles_in_strip
                ))
        hstripmap.append(framestrips)
##        print("frame tiles:", tilessofar - stripmap[-1], file=sys.stderr)

    assert totaltiles == tilessofar
    return out, stripmap, hstripmap, totaltiles

def ibatch(iterable, length):
    """Collect an iterable into lists of a given length."""

    out = []
    for el in iterable:
        out.append(el)
        if len(out) >= length:
            yield out
            out = []
    if out:
        yield out

def strips_to_tiles(frames, celim, backdrop, dstpalettes, outname=None):
    """Extract strips from an image as tiledata.

frames -- frames
celim -- PIL cel image
outname -- Image of all tiles
backdrop -- backdrop color for cel palette

Returns a 2-tuple (tiledata, stripmap) where:
tiledata -- is a list of 8x16 pixel NES tiles
"""
    if celim.mode != 'P':
        celim = celim.convert('P', dither=Image.NONE, palette=Image.ADAPTIVE)
    if celim.mode != 'P':
        raise ValueError("input image must be indexed")

    # Actually map the palettes
    palmaps = makecelpalettemap(backdrop, dstpalettes, celim)
    palims = {plane: celim.point(palmap)
              for plane, palmap in palmaps.items()}
    stripdata = collect_strip_tiles(frames, palims)
    tileim, stripmap, hstripmap, totaltiles = stripdata
    if outname:
        tileim.save(outname)
    tiledata = pilbmp2chr(tileim, tileHeight=16)
    tiledata = [b''.join(s) for s in ibatch(tiledata[:2 * totaltiles], 2)]

    return tiledata, stripmap, hstripmap

def vflip(tile):
    """Vertically flips a byte string representing a column of NES tiles."""
    out1 = b''.join(bytes(tile[t + 7:t - 1 if t > 0 else None:-1])
                    + bytes(tile[t + 15:t + 7:-1])
                    for t in range(len(tile) - 16, -16, -16))
    return out1

hflipsliver = bytearray([0])
for shamt in range(8):
    px = 0x80 >> shamt
    hflipsliver.extend(c | px for c in hflipsliver)
def hflip(tile):
    """Horizontally flips a byte string representing planar tiles."""
    return bytes(hflipsliver[sliver] for sliver in tile)

def dedupe_seq(data):
    """Find unique items and a map for expansion.

Return a 2-tuple (uniqueitems, order), where uniqueitems is a list of
items from data and order is a list of indices in uniqueitems, such
that data[i] == uniqueitems[uses[i]].
"""
    uniqueindices = {}
    uses = []
    for item in data:
        uniqueindices.setdefault(item, len(uniqueindices))
        uses.append(uniqueindices[item])
    uniqueitems = [None] * len(uniqueindices)
    while uniqueindices:
        item, i = uniqueindices.popitem()
        uniqueitems[i] = item
    return uniqueitems, uses

def dedupe_tiles_with_flip(data):
    """Find unique NES tiles up to flipping and a map for expansion.

Return a 2-tuple (uniqueitems, order), where uniqueitems is a list of
items from data and order is a list of (index, flipvalue) tuples in
uniqueitems, such that data[i] == uniqueitems[uses[i][0]] flipped by
uses[i][1] where bit 7 means vertical flipping and bit 6 horizontal.
"""
    uniqueindices = {}
    uses = []
    for item in data:
        if item in uniqueindices:
            uses.append((uniqueindices[item], 0x00))
            continue
        fitem = hflip(item)
        if fitem in uniqueindices:
            uses.append((uniqueindices[fitem], 0x40))
            continue
        fitem = vflip(item)
        if fitem in uniqueindices:
            uses.append((uniqueindices[fitem], 0x80))
            continue
        fitem = hflip(fitem)
        if fitem in uniqueindices:
            uses.append((uniqueindices[fitem], 0xC0))
            continue
        uses.append((len(uniqueindices), 0x00))
        uniqueindices[item] = len(uniqueindices)

    uniqueitems = [None] * len(uniqueindices)
    while uniqueindices:
        item, i = uniqueindices.popitem()
        uniqueitems[i] = item
    return uniqueitems, uses


def sliver_to_texels(lo, hi):
    return bytes(((lo >> i) & 1) | (((hi >> i) & 1) << 1)
                 for i in range(7, -1, -1))

def tile_to_texels(chrdata):
    _stt = sliver_to_texels
    return [_stt(a, b)
            for i in range(0, len(chrdata), 16)
            for (a, b) in zip(chrdata[i:i+8], chrdata[i+8:i+16])]

def chrseq_to_texels(chrdata):
    _ttt = tile_to_texels
    return [_ttt(chrdata[i:i + 16]) for i in range(0, len(chrdata), 16)]

def texels_to_pil(texels, tile_width=16):
    texels = [b''.join(row) 
              for i in range(0, len(texels), tile_width)
              for row in zip(*texels[i:i + tile_width])]
    maxlen = max(len(row) for row in texels)
    minlen = min(len(row) for row in texels)
    if maxlen > minlen:
        texels = [row + bytes(maxlen - len(row)) for row in texels]
    out = Image.frombytes('P', (maxlen, len(texels)), b''.join(texels))
    out.putpalette(make_fake_palette((0, 204, 255)))
    return out

def setsimilarities(sets, othersets=None):
    """Find the most similar elements in an iterable of iterables.

Often used to find matches in a list of lists of items.

sets -- column 1
othersets -- column 2; if None use sets

Return a list of (sets index, othersets index, number of shared elements)
"""
    sets = [frozenset(s) for s in sets]
    othersets = ([frozenset(s) for s in othersets]
                 if othersets is not None
                 else sets)
    return sorted((
        (ai, bi, len(a.intersection(b)))
        for ai, a in enumerate(sets)
        for bi, b in enumerate(othersets)
        if bi > ai
    ), key=(lambda row: row[2]), reverse=True)

def form_framedef(idxs, hsm, hflip):
    asmlines = []
    idxi = iter(idxs)
    for xbase, y, palette, length in hsm:
        assert length>0
        tilenums = [next(idxi) for x in range(length)]
        if hflip:
            xbase = -(xbase + length * 8)
            tilenums = [t ^ 0x40 for t in reversed(tilenums)]
        hexs = [xbase + 0x80, y + 0x80, palette + (length - 1) * 4]
        hexs.extend(tilenums)
        asmlines.append("  .byte " + ','.join("$%02X" % x for x in hexs))
    asmlines.append("  .byte 0")
    return '\n'.join(asmlines)

def ca65_bytearray(s):
    s = ['  .byte ' + ','.join(str(ch) for ch in s[i:i + 16])
         for i in range(0, len(s), 16)]
    return '\n'.join(s)

def ca65_addrarray(s):
    s = ['  .addr ' + ','.join(str(ch) for ch in s[i:i + 4])
         for i in range(0, len(s), 4)]
    return '\n'.join(s)

def form_table(tablename, tablevalues, segment):
    strtablevalues = [
        ('<%d' % v if -128 <= v < 0 else '%d' % v) for v in tablevalues
    ]
    lines = [
        '.segment "%s"' % segment,
        '.export %s' % tablename,
        '%s:' % tablename,
        ca65_bytearray(strtablevalues)
    ]
    return "\n".join(lines)

def parse_argv(argv):
    # strips.py Donny.strips Donny.png Donny.chr --flip DonnyL.png
    # -d: write intermediate files to current directory
    parser = argparse.ArgumentParser()
    parser.add_argument('STRIPSFILE',
                        help="filename of strips specification")
    parser.add_argument('CELIMAGE',
                        help="image containing all cels")
    parser.add_argument('--flip',
                        help="image containing all cels with emblems flipped")
    parser.add_argument('CHRFILE', nargs="?",
                        help="filename to which CHR data is written")
    parser.add_argument('ASMFILE', nargs="?",
                        help="filename to which ASM data is written")
    parser.add_argument('--write-frame-numbers', metavar="FRAMENUMFILE",
                        help="write frame numbers in FRAME_xxx=nnn format")
    parser.add_argument('--prefix', default='',
                        help="prefix of frametobank, mspraddrs, NUMFRAMES, and NUMTILES symbols")
    parser.add_argument('--segment', default='RODATA',
                        help="ca65 segment in which to put metasprite maps")
    parser.add_argument('-d', "--intermediate", action="store_true",
                        help="write intermediate image files")
    args = parser.parse_args(argv[1:])
    return (args.STRIPSFILE, args.CELIMAGE, args.flip,
            args.CHRFILE, args.ASMFILE, args.write_frame_numbers,
            args.prefix, args.segment, args.intermediate)

def load_strips_from(stripsfilename, celimfilename, celimfilename_flip=None,
                     verbose=False):
    """Load tile and strip data 

Return a tuple:
frames -- dict from frame name to frame data, where frame data is ?
framenames -- list of frame names in the order in which they were specified
alltiles -- all tiles encountered, with normal and L variants interleaved
stripmap -- list of how many tiles are seen by the time of each strip
hstripmap -- list of (x, y, color, width) of each horizontal strip

"""
    # Load cel images
    celimbasename = os.path.splitext(os.path.basename(celimfilename))[0]
    celim = Image.open(celimfilename)

    # Load list of frames on this sprite sheet
    with open(stripsfilename, "r", encoding="utf-8") as infp:
        stripsfile = StripsFileReader(infp)
    frames = stripsfile.frames
    framenames = stripsfile.framenames
    backdrop = stripsfile.backdrop
    dstpalettes = stripsfile.palettes
    relatedsets = find_related_sets(framenames, stripsfile.relatedframes)
    stripsfile.guess_bounding_boxes()
    framesinorder = [frames[framename] for framename in framenames]

    # Debug: make sure everything is boxed off
    if verbose:
        strip_colors = [(0, 0, 0), (255, 191, 0), (0, 191, 255), (255, 255, 255)]
        imrgb, totaltiles = draw_strips_on(celim, framesinorder, stripsfile.actionpoints, strip_colors)
        imrgb.save(celimbasename + "-boxing.png")

    # Extract tiles from cel sheets
    alltiles_name = (celimbasename + "-tiles.png" if verbose else None)
    sttnormal = strips_to_tiles(framesinorder, celim, backdrop, dstpalettes,
                                alltiles_name)
    tiledata, stripmap, hstripmap = sttnormal
    assert len(stripmap) == len(framesinorder)
    if celimfilename_flip:
        celimbasename_flip = os.path.splitext(os.path.basename(celimfilename_flip))[0]
        celimq = Image.open(celimfilename_flip) if celimfilename_flip else celim
        alltiles_name_flip = (celimbasename_flip + "-tiles.png"
                              if verbose
                              else None)
        sttflip = strips_to_tiles(framesinorder, celimq, backdrop, dstpalettes,
                                  alltiles_name_flip)
        tiledataq = sttflip[0]
        assert len(tiledataq) == len(tiledata)
    else:
        tiledataq = tiledata

    # Each tile normally appears twice in alltiles: once for the
    # unflipped version and once for the flipped version.  In HH86,
    # these correspond to 'p' and 'q' on Donny's shirt and cap.
    alltiles = [tile for lr in zip(tiledata, tiledataq) for tile in lr]

    if stripsfile.lookuptables:
        stripsfile.calc_actionpoints()
    return (frames, framenames, alltiles, stripmap, hstripmap,
            relatedsets, stripsfile.lookuptables, stripsfile.framenumaliases)

def main(argv=None):
    args = parse_argv(argv or sys.argv)
    (stripsfilename, celimfilename, celimfilename_flip,
     chrfilename, asmfilename, framenumfilename,
     symbolprefix, outsegment, write_intermediate) = args
    
    rv = load_strips_from(stripsfilename, celimfilename, celimfilename_flip,
                          write_intermediate)
    (frames, framenames, alltiles, stripmap, hstripmap,
     relatedsets, luts, framenumaliases) = rv
    stripmap.append(len(alltiles) // 2)

    iframenames = {n: i for i, n in enumerate(framenames)}
    framesinorder = [frames[framename] for framename in framenames]
    blanktile, solidtile = b'\x00'*32, b'\xFF'*32
    uniquetiles, uses = dedupe_tiles_with_flip(alltiles)
    try:
        blanktileindex = uniquetiles.index(blanktile)
    except ValueError:
        blanktileindex = None
    frameuses = [uses[stripmap[f] * 2:stripmap[f + 1] * 2]
                 for f in range(len(framesinorder))]
    frameswithflip = set(i for i, u in enumerate(frameuses)
                         if any(x[1] for x in u))
    if write_intermediate:
        print("%d frames, %d 8x16 tiles per side, %d unique tiles"
              % (len(framesinorder), len(alltiles) // 2, len(uniquetiles)))
        simis = [row for row in setsimilarities(frameuses) if row[2] > 0]
        if simis:
            print("Frames sharing most tiles:")
            print("\n".join("%s and %s: %s"
                            % (framenames[a], framenames[b], n)
                            for a, b, n in simis[:50]
                            if n * 3 >= simis[0][2] * 2))
            simis.clear()
        else:
            print("No two frames share a tile")
        if frameswithflip:
            print("%d containing flipped tiles:" % len(frameswithflip))
            simis = [framenames[i] for i in sorted(frameswithflip)]
            print(textwrap.fill(", ".join(simis)))
        else:
            print("No frames use flipped tiles")

        if blanktileindex is not None:
            print("Blank tile is unique tile %d" % blanktileindex)
            frameswithblank = [i for i, u in enumerate(frameuses)
                               if any(x[0] == blanktileindex for x in u)]
            assert frameswithblank
            if frameswithblank:
                print("Frames with a blank tile (which increases flicker):")
                print(textwrap.fill(", ".join(framenames[i]
                                              for i in frameswithblank)))
        else:
            print("Blank tile not present")

    # Put the frames designated for the subset first
    # (Not sure if this applies with solve_overload)
    framesbysubset = [(i, f[9]) for i, f in enumerate(framesinorder)]
    framesbysubset.sort(key=lambda row: (0 if row[1] else 1, row[0]))

    sizeof_bank = 32
    use_related = True

    # Find all cel IDs connected through a "related" chain
    # "tiles" in Pagination refers to frames, not individual 8x16-pixel tiles
    job = {"capacity": sizeof_bank, "tiles": []}
    seen_related = {}  # map element to first in related set
    for f, _ in framesbysubset:
        if f in seen_related: continue
        fname = framenames[f]
        if use_related:
            rel = {iframenames[n] for n in relatedsets[fname]}
        else:
            rel = {f}
        seen_related.update((f2, f) for f2 in rel)
        # Find all individual tiles across these cels
        tilesneeded = {x[0] for relf in rel for x in frameuses[relf]}
        if tilesneeded: job["tiles"].append(sorted(tilesneeded))

    # Place tiles in banks
    nbanks = -(-len(uniquetiles) // sizeof_bank)
    use_solve_overload = True  # nbanks > 1
    if use_solve_overload:
        # Pagination problem solver
        pages = solve_overload.run(job)
        pages.decant()
        tilesinbank = [
            sorted(set(t for relset in page for t in relset))
            for page in pages
        ]
        tilesinbank.sort()

        # Move (may need to be revised if we ever use subset again)
        shortest_bank = min(enumerate(tilesinbank), key=lambda x: len(x[1]))[0]
        tilesinbank[-1], tilesinbank[shortest_bank] = \
                         tilesinbank[shortest_bank], tilesinbank[-1]
    else:
        # Previous greedy first fit approach to packing
        tilesinbank = [set() for i in range(nbanks)]
        for tilesneeded in job["tiles"]:
            for b in range(len(tilesinbank)):
                candidate = tilesinbank[b].union(tilesneeded)
                if len(candidate) <= sizeof_bank:
                    tilesinbank[b] = candidate
                    break
            else:  # no tilesinbank was assigned
                print("%s: allocating new bank %d; suboptimal packing?"
                      % (stripsfilename, len(tilesinbank)), file=sys.stderr)
                tilesinbank.append(set(tilesneeded))

    num_tiles = len(tilesinbank[-1]) + sizeof_bank * (len(tilesinbank) - 1)

    # Find which frames use each tile
    framesinbank = [set() for i in tilesinbank]
    for f, ftiles in enumerate(frameuses):
        ftiles = set(row[0] for row in ftiles)
        for b, btiles in enumerate(tilesinbank):
            if not ftiles.difference(btiles):
                framesinbank[b].add(f)
                break
        else:
            print("%s: internal error: cannot place frame %s in any bank"
                  % (stripsfilename, framenames[f]), file=sys.stderr)
            sys.exit(1)

    if write_intermediate:
        print("Tile count: %d; in each bank:" % num_tiles)
        print("\n".join(textwrap.fill("%d: %s" % (b, ', '.join(str(tn) for tn in sorted(ts))))
                        for b, ts in enumerate(tilesinbank)))
        print("Frames in each bank:")
        print("\n".join(textwrap.fill("%d: %s" % (b, ', '.join(framenames[f] for f in sorted(ts))))
                        for b, ts in enumerate(framesinbank)))
        print("Subset frames in each bank:")
        print("\n".join(textwrap.fill("%d: %s" % (b, ', '.join(framenames[f] for f in sorted(ts) if framesinorder[f][9])))
                        for b, ts in enumerate(framesinbank)))
        simis = [row for row in setsimilarities(tilesinbank) if row[2] > 0]
        if simis:
            print("Banks sharing most tiles:")
            print("\n".join("%d and %d: %s" % (a, b, n)
                            for a, b, n in simis
                            if n * 2 >= simis[0][2]))
        else:
            print("No banks share a tile")
        simis.clear()

    # Write tiles
    tilesinbank = [sorted(ts) for ts in tilesinbank]  # Convert sets to lists
    banktilesheets = [[uniquetiles[x] for x in ts] for ts in tilesinbank]
    if write_intermediate:
        print("Bank tile sheets length is", [len(x) for x in banktilesheets])
    # Experimental: Don't pad the last bank
    for ts in banktilesheets[:-1]:
        ts.extend([solidtile] * (32 - len(ts)))
    if chrfilename:
        with open(chrfilename, 'wb') as outfp:
            for ts in banktilesheets:
                outfp.writelines(ts)
    if write_intermediate:
        print("Bank tile sheets padded to", [len(x) for x in banktilesheets])
        texels1 = [tile_to_texels(x) for ts in banktilesheets for x in ts]
        im = texels_to_pil(texels1, 32)
        celimbasename = os.path.splitext(os.path.basename(celimfilename))[0]
        im.save(celimbasename + "-uniquetiles.png")

    # Find which bank to use for each frame
    frametobank = {}
    for banknum, ts in enumerate(framesinbank):
        frametobank.update((framenum, banknum) for framenum in ts)

    if max(frametobank) + 1 > len(frametobank):
        missingframes = [i for i in range(max(frametobank) + 1)
                         if i not in frametobank]
        print("Internal error: some frames are missing", file=sys.stderr)
        print("\n".join("%d: %s" % (i, framenames[i]) for i in missingframes),
              file=sys.stderr)
    assert max(frametobank) + 1 == len(frametobank)

    frametobank = [frametobank[i] for i in range(len(frametobank))]
    if write_intermediate:
        print("frametobank:", frametobank)

    # Find the counterpart within the bank to each tile
    # TODO: Don't allow flipping between normal and L versions of same tile
    tilesinframebybank = []
    for f, (u, bank) in enumerate(zip(frameuses, frametobank)):
        t = tilesinbank[bank]
        unormalflip = [[(t.index(tn[0]), tn[1]) for tn in tns]
                       for tns in zip(u[0::2], u[1::2])]
        found_bad_lr = 0
        for l, r in unormalflip:
            if r[0] - l[0] not in (0, 1) or r[1] != l[1]:
                print("frame %d (%s) in bank %d has l=%d flip=%02X, r=%d flip=%02X"
                      % (f, framenames[f], bank, l[0], l[1], r[0], r[1]),
                      file=sys.stderr)
                found_bad_lr += 1
        t = [(l[0] + r[0]) | l[1] for l, r in unormalflip]
        tilesinframebybank.append(t)
    if found_bad_lr > 0:
        raise ValueError("%d tiles with discontiguous left and right variants"
                         % found_bad_lr)

    # Form actual tile strips and find identical ones
    framedefs = []
    framedefsinv = {}
    for i, (idxs, hsm, frame) \
        in enumerate(zip(tilesinframebybank, hstripmap, framesinorder)):
        hflipped = frame[8]
        fd = form_framedef(idxs, hsm, hflipped)
        if fd not in framedefsinv:
            framedefsinv[fd] = []
            framedefs.append(fd)
        framedefsinv[fd].append(i)

    # Each frame has 4 bytes of overhead:
    # frametobank (1), mspraddrs (2), NUL terminator (1)
    # each row has 3 byte header and 1 byte per 8x16
    msprsize = sum(
        4 + 3 * len(hsm) + sum(x[3] for x in hsm)
        for hsm in hstripmap
    )

    if write_intermediate:
        print("Metasprite total: %d bytes" % msprsize)
        print("Actual tile indices follow")
        thingies = zip(framenames, frametobank, tilesinframebybank, hstripmap)
        print("\n".join(
            "%s: %d[%s]\n  hstripmap: %s"
            % (fn, bank, " ".join("%02x" % x for x in idxs), hsm)
            for (fn, bank, idxs, hsm) in thingies
        ))

    # Separate them out by horizontal strips
    asmlines = [
        '; metasprite map generated by strips.py',
        '; strips file: %s' % stripsfilename,
        '; sprite sheet: %s' % celimfilename,
        '; left-facing sprite sheet: %s' % celimfilename_flip,
        '; metasprite total: %d bytes' % msprsize,
        '; %d unique tiles in %d pages' % (len(uniquetiles), len(banktilesheets)),
        '.segment "%s"' % outsegment,
        ".exportzp %sNUMFRAMES = %d" % (symbolprefix, len(frametobank)),
        ".exportzp %sNUMTILES = %d" % (symbolprefix, num_tiles),
        symbolprefix + "frametobank:",
        ca65_bytearray(frametobank),
        symbolprefix + "mspraddrs:",
        ca65_addrarray(["mspr_%s" % fn for fn in framenames])
    ]

    for fd in framedefs:
        asmlines.extend('mspr_%s:' % framenames[i]
                        for i in framedefsinv[fd])
        asmlines.append(fd)

    # Add lookup tables
    if luts:
        asmlines.append("; lookup tables "+'-'*30)
        asmlines.extend(
            form_table(tn, values, seg)
            for tn, (values, _, seg, _) in luts.items()
        )

    if asmfilename:
        asmlines.append('')
        asmlines = '\n'.join(asmlines)
        if asmfilename == '-':
            sys.stdout.write(asmlines)
        else:
            with open(asmfilename, 'w', encoding="utf-8") as outfp:
                outfp.write(asmlines)

    # Write frame number, bank, and first tile number for each frame
    if framenumfilename:
        names = list(enumerate(framenames))
        names.extend((i, name) for (name, i) in framenumaliases)
        names.sort(key=lambda x: x[0])
        framenumlines = [
            "FRAME_%s=%d\nFRAMEBANK_%s=%d\nFRAMETILENUM_%s=$%02X\n"
            % (name, i,
               name, frametobank[i],
               name, tilesinframebybank[i][0] if tilesinframebybank[i] else 0xFF)
            for i, name in names
        ]
        with open(framenumfilename, 'w', encoding="utf-8") as outfp:
            outfp.writelines(framenumlines)
    
if __name__=='__main__':
    in_IDLE = 'idlelib.__main__' in sys.modules or 'idlelib.run' in sys.modules
    if in_IDLE:
        main([
            'strips.py', '-d',
            "../src/Hero.strips",
            "../tilesets/sprites/Hero.png",
        ])
##        main([
##            'strips.py', '-d',
##            "../src/Breakwalls.strips",
##            "../tilesets/sprites/Breakwalls.png",
##        ])
    else:
        main()

