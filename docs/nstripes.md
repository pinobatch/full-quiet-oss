Stripe Image extractor
======================

This tool extracts parts from an image file and converts them to
a combination of 8x8-pixel tiles and tilemap fragments in the
[Stripe Image] format used in some NES games.

[Stripe Image]: https://www.nesdev.org/wiki/Tile_compression#NES_Stripe_Image_RLE

Invoking
--------

Usage:

    nstripes.py [-h] [--segment SEGMENT] [-b TILEID]
                [--fix-tiles FILENAME] [--extra-tiles [HEX:FILENAME ...]]
                STRIPEFILE CELIMAGE [CHRFILE] [ASMFILE]

Positional arguments:

- `STRIPEFILE`  
  Filename of coordinate spec
- `CELIMAGE`  
  4-color indexed image containing all tiles
- `CHRFILE` (optional)  
  Filename to which tile data is written in NES CHR format
- `ASMFILE` (optional)
  Filename to which assembly language stripe map data is written

Options:

- `-h`, `--help`  
  Show usage message and exit
- `--segment SEGMENT`  
  ca65 segment in which to put stripe maps
- `-b TILEID`, `--base-tiles TILEID`  
  Start captured tiles (and fixed tiles) at a particular tile ID
  (default: `0`)
- `--fix-tiles FILENAME`  
  Force the first pattern table indices to the first tiles in
  `FILENAME` (a CHR file or 4-color image), and include them at
  the start of `CHRFILE`
- `--extra-tiles HH:FILENAME [HH:FILENAME ...]`  
  Use extra tiles from `FILENAME` (a CHR file or 4-color image) at
  tile IDs starting at `0xHH`, and do not include them in `CHRFILE`

Each image specified as `CELIMAGE`, `--fix-tiles`, or `--extra-tiles`
must be in a format readable by Pillow (Python Image Library), such
as BMP, GIF, or PNG.  It must use indexed mode without transparency.
Its colormap should have the same order as the palette loaded into
CRAM at video memory address `$3F00`.  If an image has more than 4
colors, each pixel's color index is reduced mod 4.

Coordinate file syntax
----------------------

- `#`  
  Lines beginning with the pound sign are ignored as comments.
- `stripe nameofstripe`  
  Sets up a new stripe image.  A label is created for each stripe
  image, named `NSTRIPE_` followed by the name of the stripe image.
  This name can contain ASCII letters, digits, and underscores (`_`).
- `dest left top`  
  Sets the destination address in nametable memory to which the
  stripe image should be drawn, if not (0, 0).
- `hrect left top width height`  
  Adds a row-major rectangle, one made of horizontal stripes,
  to the latest stripe image.
- `vrect left top width height`  
  Adds a column-major rectangle, one made of vertical stripes,
  to the latest stripe image.
- `rect left top width height`  
  Adds a column-major rectangle if its height is greater than its
  width, or a row-major rectangle otherwise.
- `fallthrough`  
  Omits the `$FF` terminator at the end of this stripe image.
  Instead, `nstripe_append` and the like fall through into the
  following stripe image.

All coordinates and lengths in `dest`, `hrect`, `vrect`, and `rect`
must be nonnegative multiples of 8 pixels.

Coordinate file example
-----------------------

    stripe practice_mascot
    dest 184 40
    vrect 0 24 16 40
    vrect 16 0 24 64
    vrect 40 32 8 32
    
    stripe radio_tower
    dest 112 16
    vrect 72 0 16 144
    rect 64 8 8 8
    rect 88 8 8 8
    
    stripe trading_nodeal
    dest 168 40
    rect 80 0 48 24
    
    stripe trading_deal
    dest 168 40
    rect 128 0 48 24

Stripe Image format
-------------------

Each stripe image in the assembly language output consists of a
sequence of packets of length 4 to 35 bytes.

- Each packet's first two bytes are a starting address in video
  memory, most significant byte first.  Stripe images generated with
  this tool use addresses in the first nametable: `$2000` to `$23BF`.
- The third byte is a flags byte.  Bit 7 is true (`$80`) if the
  stripe is "vertical," meaning destination bytes are 32 addresses
  apart in video memory.  Bit 6 is true (`$40`) if the stripe is a
  "run," meaning all bytes in the stripe have the same value.
  Bits 5-0 hold the length of the packet minus 1: `$00` means 1 byte,
  `$03` means 4 bytes, and `$1F` means 32 bytes.
- For a run, the fourth and final byte is the value of all bytes in
  the stripe.  For other stripes (called "literal"), as many bytes
  follow as the length of the stripe.
- A byte with value `$FF` terminates the list of stripes in an image.
