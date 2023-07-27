#!/usr/bin/env python3
"""
romusage.py
Visualize NES ROM as an image

Copyright 2023 Retrotainment Games LLC
Copyright 20xx Damian Yerrick

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
import sys
import os
import argparse
from collections import defaultdict
from PIL import Image

def sliver_to_texels(lo, hi):
    return [((lo >> i) & 1) | (((hi >> i) & 1) << 1)
            for i in range(7, -1, -1)]

def tile_to_texels(chrdata):
    if len(chrdata) < 16:
        chrdata = chrdata + bytes(16 - len(chrdata))
    _stt = sliver_to_texels
    return [_stt(a, b) for (a, b) in zip(chrdata[0:8], chrdata[8:16])]

def chrbank_to_texels(chrdata, planes=2):
    _ttt = tile_to_texels
    tilelen = 8 * planes
    return [_ttt(chrdata[i:i + tilelen])
            for i in range(0, len(chrdata), tilelen)]

def texels_to_pil(texels, tile_width=16, row_height=1):
    row_length = tile_width * row_height
    tilerows = [
        texels[j:j + row_length:row_height]
        for i in range(0, len(texels), row_length)
        for j in range(i, i + row_height)
    ]
    emptytile = [bytes(8)] * 8
    for row in tilerows:
        if len(row) < tile_width:
            row.extend([emptytile] * (tile_width - len(tilerows[-1])))
    texels = [bytes(c for tile in row for c in tile[y])
              for row in tilerows for y in range(8)]
    im = Image.frombytes('P', (8 * tile_width, len(texels)), b''.join(texels))
    im.putpalette(b'\x00\x00\x00\x66\x66\x66\xb2\xb2\xb2\xff\xff\xff'*64)
    return im

def render_usage(tilewidth=32):
    tiles = texels_to_pil(chrbank_to_texels(chrdata, tilewidth))
    return tiles

def quantizetopalette(src, palette, dither=False):
    """Convert an RGB or L mode image to use a given P image's palette.

Pillow 6+
Reference: https://stackoverflow.com/a/29438149/2738262
"""
    return src.quantize(palette=palette, dither=1 if dither else 0)

def parse_skip_arg(s):
    s = s.lower()
    if s == 'prg': return s
    if s.startswith("0x"): return int(s[2:], 16)
    if s.startswith("$"): return int(s[1:], 15)
    return int(s)

def parse_argv(argv):
    p = argparse.ArgumentParser()
    p.add_argument("ROMNAME",
                   help="name of NES ROM or CHR file")
    p.add_argument("OUTPUT", nargs='?',
                   help="name of PNG output file; if not given, "
                   "display in new window")
    p.add_argument("--skip", type=parse_skip_arg,
                   help="bytes to skip (e.g. 4096, $1000, 0x1000), "
                        "or prg to skip entire .nes PRG ROM "
                        "(default: 16 for .nes or 0 for other extensions)")
    p.add_argument("-w", "--width", type=int,
                   help="number of tiles per row "
                        "(default: 128 for .nes or 16 for other extensions)")
    p.add_argument("--row-height", type=int, default=1,
                   help="height of each row in column-major tiles "
                   "(default: 1; 2 may help for 8x16 sprites)")
    p.add_argument("-o", "--output",
                   help="name of PNG output file")
    p.add_argument("-C", "--config",
                   help="name of ld65 configuration file")
    parsed = p.parse_args(argv[1:])
    if parsed.output and parsed.OUTPUT:
        p.error("cannot have positional and -o output")
    parsed.output = parsed.output or parsed.OUTPUT
    return parsed

def load_config(configname):
    """
Load an ld65 config file and find what segments are in the file.
Return a list of the form [(memname, (start, size), [segname, ...]), ...]
"""

    import textwrap
    from freebytes import ld65_load_linker_script, ld65parseint

    result = ld65_load_linker_script(configname)
    config, _, segtomem = result
    memromstarts, romelapsed = {}, 0
    for mem, attrs in config['MEMORY']:
        if attrs.get('file') != '%O': continue
        size = ld65parseint(attrs["size"])
        memromstarts[mem] = romelapsed, size
        romelapsed += size
    # memromstarts is of the form {memname: (start, size), ...}
    # segtomem is of the form {seg: mem, ...}

    memtosegs = defaultdict(list)
    for seg, mem in segtomem.items():
        if mem in memromstarts:
            memtosegs[mem].append(seg)
    segplacement = [
        (mem, memromstarts[mem], segs)
        for mem, segs in memtosegs.items()
    ]
    segplacement.sort(key=lambda row: row[1][0])
    return segplacement

def font_getsize(font, s):
    try:
        bbox = font.getbbox(s)  # available in Pillow >= 9.2
    except AttributeError:
        return font.getsize(s)  # available in Pillow < 10.0
    else:
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

def draw_config(config, cfgwidth, romperpixel):
    from PIL import ImageDraw, ImageFont
    # In mode, the image is shrunk by 2 such that each scanline
    # represents 512 bytes of ROM.
    headersize = 16
    mem_ycoord = [
        (mem[1][0] - headersize) // romperpixel
        for mem in config
    ]

    lastsz = config[-1][1]
    romsize = lastsz[0] + lastsz[1] - headersize
    im = Image.new('L', (cfgwidth, romsize // romperpixel), 0)
    dc = ImageDraw.Draw(im)
    font = dc.getfont()
    commaspacesize = font_getsize(font, ", ")

    # Join undersize rows with the previous
    for i in range(1, len(mem_ycoord) - 1):
        if mem_ycoord[i] < 0:
            mem_ycoord[i] = -commaspacesize[1]
        elif mem_ycoord[i + 1] - mem_ycoord[i] < commaspacesize[1]:
            mem_ycoord[i] = mem_ycoord[i - 1]

    # Choose one representative segment for each memory area,
    # taking into account joined areas, and lay out with word wrap
    texts, x = [], 0
    for y, mem in zip(mem_ycoord, config):
        if y < 0: continue
        repsegname = min(mem[2])
        textwidth = font_getsize(font, repsegname)[0] + commaspacesize[0]
        need_comma = need_newline = False
        nexty = texts[-1][0] + commaspacesize[1] if texts else 0
        if not texts or y >= nexty:
            need_newline = True
        elif x + textwidth > cfgwidth:
            need_newline = need_comma = True
        else:
            need_comma = True
        if need_comma:
            texts[-1][1].append(", ")
        if need_newline:
            x, y = textwidth, max(y, nexty)
            texts.append((y, [repsegname]))
        else:
            x += textwidth
            texts[-1][1].append(repsegname)

    for y, text in texts:
        text = "".join(text)
        dc.text((commaspacesize[0] // 2, y), "".join(text),
                fill=191, font=font)
    return im

def main(argv=None):
    args = parse_argv(argv or sys.argv)
    infilename = args.ROMNAME
    is_nes = os.path.splitext(infilename)[-1].lower() == '.nes'
    outfilename = args.output
    configname = args.config
    twidth = args.width
    if twidth is None: twidth = 128 if is_nes else 16
    skip, skip_prg = args.skip, False
    if skip is None:
        skip = 16 if is_nes else 0
    elif skip == 'prg':
        skip, skip_prg = 16, True

    config = None
    if configname: config = load_config(configname)
    with open(infilename, "rb") as infp:
        header = infp.read(skip)
        if skip_prg:
            prgromsize = header[4] << 14
            if (header[7] & 0x0C) == 0x08:  # NES 2.0 large PRG ROM extension
                prgromsize += (header[9] & 0x0F) << 22
            infp.read(prgromsize)
        romdata = infp.read()
    tiles = texels_to_pil(chrbank_to_texels(romdata),
                          twidth, args.row_height)

    if configname:
        cfgwidth = 128

        # If using a config file, make a sanitized public version
        # with the ROM at 1:2 scale so only 1/4 of data is available,
        # hindering reconstruction of the ROM.
        origtiles = tiles
        w, h = tiles.size
        smtiles = tiles.convert("L").resize((w//2, h//2), resample=Image.BOX)

        # In a full conversion from 2bpp, each scanline represents
        # twidth*2 ROM bytes.  In a shrunken conversion, twice that.
        cfgim = draw_config(config, cfgwidth, twidth*4)
        totalsize = (smtiles.size[0] + cfgim.size[0], smtiles.size[1])
        tiles = Image.new("RGB", totalsize, 0)
        tiles.paste(smtiles, (0, 0))
        tiles.paste(cfgim, (smtiles.size[0], 0))
        tiles = quantizetopalette(tiles, origtiles)
        origtiles = smtiles = cfgim = None
        saveargs = {'bits': 2}
    else:
        saveargs = {'bits': 2}

    if outfilename:
        tiles.save(outfilename, **saveargs)
    else:
        try:
            tiles.show()
        except Exception:
            tiles.convert("RGB").show()

if __name__=='__main__':
    if 'idlelib' in sys.modules:
        main(['romusage.py', '../game.nes', "--config", "../mmc3_4mbit.cfg"])
    else:
        main()
