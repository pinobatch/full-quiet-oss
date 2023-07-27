#!/usr/bin/env python3
import os, sys, argparse
from PIL import Image
from pilbmp2nes import pilbmp2chr, formatTilePlanar

def format_1bpp(tile):
    return formatTilePlanar(tile, "0")

def parseintorhex(s):
    """Parse an integer that uses $ or 0x for base sixteen or none for base ten"""
    neg = s.startswith("-")
    if neg: s = s[1:]
    if s.startswith('$'):
        n = int(s[1:], 16)
    elif s.startswith(('0x', '0X')):
        n = int(s[2:], 16)
    else:
        n = int(s)
    if neg: n = -n
    return n

helpText = """
Adds an image of a serial number to a ROM.
"""
def parse_argv(argv):
    p = argparse.ArgumentParser(description=helpText)
    p.add_argument("romfile", type=argparse.FileType('rb'),
                   help="iNES ROM image")
    p.add_argument("template", type=Image.open,
                   help="128x16-pixel PNG file with background at y=0 "
                   "and digits at y=8")
    p.add_argument("number", type=int,
                   help="decimal number to write on the template")
    # we do not use argparse.FileType('wb') so as not to clobber
    # output in case of an error
    p.add_argument("outfile",
                   help="output ROM image")
    p.add_argument("-b", "--bank", type=parseintorhex, default=0,
                   help="8 KiB bank to contain the image (default: 0)")
    p.add_argument("-a", "--address", type=parseintorhex, default=0,
                   help="offset within bank, reduced modulo 8192 (default: 0)")
    p.add_argument("-x", type=parseintorhex, default=0,
                   help="horizontal position of digits (0-128; default: 0)")
    p.add_argument("--right", action="store_true",
                   help="interpret -x as the right side (default left)")
    p.add_argument("-w", "--digit-width", type=parseintorhex, default=8,
                   help="width in pixels of each digit (1-12; default: 8)")
    p.add_argument("--through", "--thru", type=int,
                   help="last number to write on the template")
    return p.parse_args(argv[1:])

def main(argv=None):
    args = parse_argv(argv or sys.argv)
    if args.template.size != (128, 16):
        print("prototype.py: expected 128x16 pixel template; got %dx%d"
              % args.template.size, file=sys.stderr)
    number, last_number = args.number, args.through
    if last_number is None: last_number = number
    romdata = bytearray(args.romfile.read())
    args.romfile.close()
    BANKSIZE = 0x2000
    HEADERSIZE = 0x10
    destaddr = (args.address % BANKSIZE) + (args.bank * BANKSIZE) + HEADERSIZE

    while number <= last_number:
        im = args.template.convert("1")
        digits = [ord(x) - ord('0') for x in str(number)]
        left = args.x
        if args.right: left -= len(digits) * args.digit_width
        for d in digits:
            srcleft = d * args.digit_width
            digit = im.crop((srcleft, 8, srcleft + args.digit_width, 16))
            im.paste(digit, (left, 0))
            left += args.digit_width
        chrdata = pilbmp2chr(im.crop((0, 0, 128, 8)), formatTile=format_1bpp)
        chrdata = b''.join(chrdata)
        # write it out
        romdata[destaddr:destaddr + len(chrdata)] = chrdata
        if args.through is not None:
            outfile = args.outfile.replace("%d", str(number))
        else:
            outfile = args.outfile
        with open(outfile, "wb") as outfp:
            outfp.write(romdata)
        number += 1

if __name__=='__main__':
    if 'idlelib' in sys.modules:
        main("""
./prototype.py -b 60 -a $8000 -x 104 --right -w 8 --through 50
../gpk.nes prototype-template.png 1 ../prototypes/gpk-proto%d.nes
""".split())
    else:
        main()

