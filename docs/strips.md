strips.py
=========

`strips.py` is a tool to extract a sprite sheet from an image file
for use in an NES game.  It was originally created for the game
*Haunted: Halloween '86* by Retrotainment Games.  After further use
in *Full Quiet* and *Garbage Pail Kids*, it was agreed to release it
to the public.

The tool reads a cel position file that gives locations of
cels in the image file, grabs 8×16-pixel tiles from those cels,
packs the cels into 32-tile banks using an
[implementation of the overload-and-remove algorithm][Grange_github]
for overlapping bin packing described in a 2017
[article by Aristide Grange et al.][Grange_arxiv], and writes tables
describing the shape of each cel as well as other user-specified data
pertaining to each cel.

Invoking
--------

Usage:

    strips.py [-h] [--flip FLIPCELIMAGE]
              [--write-frame-numbers FRAMENUMFILE] [--prefix PREFIX]
              [--segment SEGMENT] [--bank-size NUM] [-d]
              STRIPSFILE CELIMAGE [CHRFILE] [ASMFILE]


Positional arguments:

- `STRIPSFILE`: name of cel position file
- `CELIMAGE`: image containing all cels
- `CHRFILE` (optional): filename to which CHR data is written
- `ASMFILE` (optional): filename to which metasprite maps are written

Options:

- `-h`, `--help`: show this help message and exit
- `--flip FLIPCELIMAGE`: image containing all cels with emblems flipped, used for left-facing cels
- `--write-frame-numbers FRAMENUMFILE`: filename to write frame numbers as `FRAME_xxx=nn`, `FRAMEBANK_xxx=nn`, and `FRAMETILENUM_xxx=nn`
- `--prefix PREFIX` prefix of `frametobank`, `mspraddrs`, `NUMFRAMES`, and `NUMTILES` symbols in `ASMFILE`
- `--segment SEGMENT` ld65 segment in which to put metasprite maps (default: `RODATA`)
- `--bank-size NUM`: size of bank in tiles (default: 32)
- `-d`, `--intermediate`: print more debugging info and write `-boxing`, `-tiles`, and `-utiles` images to current directory

Giving `-d` and omitting `CHRFILE` and `ASMFILE` is useful when
checking a sheet for errors before adding it to your project.

The default `--bank-size 32` is tuned for MMC3, which has 1024-byte
CHR banks that each hold 32 8×16-pixel tiles.  Other `--bank-size`
values are useful:

- `--bank-size 29` combined with further processing on `CHRFILE` lets
  you repeat a particular set of 3 sprite tiles in all banks.
- `--bank-size 16` uses the smaller 512-byte banks found in some
  modern mappers.
- `--bank-size 128` mostly disables splitting a sheet into banks.
  This is useful in projects using NROM, UNROM, or other discrete
  logic mappers.

Basic structure
---------------

The cel position (.strips) file used by `strips.py` is a source code
file that describes where the cels are located on a sprite sheet and
where the non-transparent rectangles of sprite tiles lie within each
cel.

Leading and trailing whitespace on each line are ignored.  Unlike
a Python script, a cel position file is not indentation-sensitive.

A line beginning with zero or more whitespace followed by a `#` sign
is a comment and ignored.

The file begins with file-wide things like palette declarations:

    backdrop <#rgb>
    palette <palid> <#rgb> <#rgb> <#rgb> <#rgb>=2 <#rgb>=3
    hflip

(In this and other examples in this document, the angle brackets `<`
and `>` are not part of the cel position file syntax.  Instead, they
act as a placeholder for a value with a particular type.)

Keywords and types used in global declarations:

- `backdrop` tells what color is used for pixels that are always
  transparent.
- `palette` associates a palette ID with one or more colors in the
  image.  On NES, palette IDs range from 0 to 3.
  The first three `<#rgb>` values are associated with indices 1-3
  unless overridden with a following `=1`, `=2`, or `=3` to force a
  color to be converted to a particular index.
- `hflip` on a line by itself horizontally flips all cels in the
  sheet.  By default, `strips.py` assumes all cels face right.
  Use `hflip` if cels face left.
- An `<#rgb>` specifies an RGB color using 3- or 6-digit hexadecimal,
  such as `#fa9` or `#ffaa99`.  The colors need not be exact; the
  tool rounds each color to the closest color in the sprite sheet.

Then for each cel:

    frame <nameofframe> <cliprect>?
      aka `<nameofframe>`
      strip <palid> <cliprect>?
      strip <palid> <cliprect> at <loc>
      hotspot <loc>

    frame <nameofframe>
      repeats <nameofframe>
      hotspot <loc>

    frame <nameofframe> repeats <nameofframe>
      hotspot <loc>

Keywords and types used in cels:

- Each `frame` begins and names one cel and optionally specifies a
  clipping rectangle.  (If a clipping rectangle is not provided,
  it uses the union of all strips' clipping rectangles.)
- `aka` gives an additional name to a `frame` to the file specified
  in `--write-frame-numbers`.  This can be useful for marking a cel
  as the last in an animation sequence or the first in a category
  (such as the first aerial cel).
- Each `strip` marks a rectangle of non-transparent pixels within
  that cel using one palette.  A cel may have multiple strips to
  minimize wasted space or maximize tile reuse.  If the strip does
  not specify a clipping rectangle, it uses that of the `frame`.
  A strip may specify a destination location to place the pixels read
  from its clipping rectangle at a different position when drawn.
  This is useful for advanced tile reuse scenarios.
- `hotspot` gives the starting position used to calculate the offset
  of each rectangle when the cel is drawn.  It defaults to the
  bottom center of the `frame`'s clipping rectangle.
- `repeats` reuses the clipping rectangle and strips of a previously
  defined cel.  This is useful if you have different cels that look
  identical but use different cel IDs.  The hotspot is not reused.
  This keyword may appear on the same line as `frame` or the
  following line.
- `<nameofframe>` must be a valid ca65 identifier, unique across all
  sprite sheets in the project.  If `--write-frame-numbers` is given,
  `strips.py` writes a constant for each cel, with a name prefixed
  `FRAME_` and a value of the cel ID.
- A clipping rectangle `<cliprect>` is four integers of the form
  `<left> <top> <width> <height>`, specifying a region of the image.
- A `<palid>` tells what palette ID to use for this strip, as a
  cel may have multiple adjacent or overlapping strips with different
  palettes.  The ID in each `strip` must match an ID in a `palette`
  declaration.
- A location `<loc>` is two integers of the form `<left> <top>`,
  specifying either a hotspot or the top left of a strip's
  destination.

A simple example:

    backdrop #99F
    palette 0 #530 #F69 #FF6 #000=1
    palette 1 #530 #AA3 #FF6 #000=1

    frame Libbet_standE  32  52 12 12
      strip 0 34 42 8 16
      strip 1 34 58 8 6

    frame Libbet_jumpE3  80 116 12 12
      strip 0 82 112 8 8
      strip 1 82 120 8 8
      hotspot 86 130

Lookup tables
-------------

A sprite sheet may have one or more lookup tables that specify
properties of a cel.  Properties used in one game include duration
in ticks, hitbox placement, amount of damage, or whether it is the
last frame of an attack sequence.  Different sprite sheets may have
different tables.

Global things:

    table <tablename> in <segmentname>
      attribute <keyword> in <tablename>
      flag <keyword> <intorhex> in <tablename>

    table <tablename> in <segmentname>
    table <tablename> in <segmentname>
      actionpoint <keyword> in `<tablename?>` `<tablename?>`

Keywords and types used with lookup tables:

- `table` creates a lookup table with one byte per cel.  Attributes,
  flags, and action point coordinates can be packed into tables.
  If nothing is packed into the entry for a particular cel in a
  table, its value is 0 for attributes or flags or (-128, -128)
  for action points.
- `attribute` defines a keyword with 1 argument that places a value
  into a cel's entry in a table.
- `flag` defines a keyword with 0 arguments.  Values from `flag`
  keywords in a particular table get combined using bitwise `OR` with
  the value from the `attribute` in the same table.
- `actionpoint` defines a keyword with 2 arguments that places a
  signed displacement from the hotspot into two tables, the first for
  the horizontal (X) coordinate and the second for the vertical (Y)
  coordinate.  To put only the X or Y coordinate in a table, use `-`
  in place of the other table name.
- `<tablename>` must be a valid ca65 identifier, unique across all
  tables in the project.  It will be `.export`ed for use by your
  animation logic.
- `<segmentname>` must be the name of a segment defined in the
  project's linker configuration file, such as `RODATA`.
  It is recommended to use a segment in the same ROM bank as the
  code that reads the table.
- `<keyword>` is a keyword.  It can be used below a `frame` to assign
  a value for that cel's entry in the table associated with that
  keyword.
- `<intorhex>` is a value from 0 to 255, expressed in decimal (such
  as `123`), 6502 hexadecimal (such as `$7B`), or C hexadecimal
  (such as `0x7B`).
- `<tablename?>` is either a `<tablename>` or the symbol `-`.

An example with lookup tables:

    backdrop #99F
    palette 0 #530 #F69 #FF6 #000=1
    palette 1 #530 #AA3 #FF6 #000=1
    hflip

    table Libbet_celflags
      attribute duration in Libbet_celflags
      flag aerial 0x80 in Libbet_celflags

    table Libbet_eye_height
      actionpoint eye in - Libbet_eye_height

    frame Libbet_standE  32  52 12 12
      strip 0 34 42 8 16
      strip 1 34 58 8 6
      eye 39 56

    frame Libbet_jumpE3  80 116 12 12
      strip 0 82 112 8 8
      strip 1 82 120 8 8
      hotspot 86 130
      eye 87 118
      aerial
      duration 30

Advanced keywords
-----------------

    align <alignment>
    frame <nameofframe> <cliprect>?
      related <nameofframe>
      subset

- `align` asserts that the following cel ID is a multiple of a
  given number.  Useful for animations that toggle between two or
  among four cels.
- `related` forces this cel to be kept in the same CHR page as
  another cel.  This can be used to keep both an attack and its
  related projectiles paged in at once.
- `subset` (deprecated) packs the cel before packing other cels.
  This was originally intended to put a specific set of cels into a
  lower-numbered CHR page, letting an engine unpack only a basic
  subset of the tiles needed for an NPC into CHR RAM compared to the
  tiles needed when the same character is playable.  It became less
  functional in October 2019 when strips.py switched from greedy
  packing to overload-and-remove packing.
- `<alignment>` is an integer greater than 1.

Index of keywords
-----------------

- 'actionpoint': Global, [Lookup tables](#lookup-tables)
- 'aka': Global, [Lookup tables](#lookup-tables)
- 'align': Cel, [Advanced keywords](#advanced-keywords)
- 'attribute': Global, [Lookup tables](#lookup-tables)
- 'backdrop': Global, [Basic structure](#basic-structure)
- 'frame': Cel, [Basic structure](#basic-structure)
- 'flag': Global, [Lookup tables](#lookup-tables)
- 'hflip': Global, [Basic structure](#basic-structure)
- 'hotspot': Cel, [Basic structure](#basic-structure)
- 'palette': Global, [Basic structure](#basic-structure)
- 'repeats': Cel, [Basic structure](#basic-structure)
- 'related': Cel, [Advanced keywords](#advanced-keywords)
- 'strip': Cel, [Basic structure](#basic-structure)
- 'subset': Cel, [Advanced keywords](#advanced-keywords)
- 'table': Global, [Lookup tables](#lookup-tables)

[Grange_github]: https://github.com/pagination-problem/pagination
[Grange_arxiv]: https://arxiv.org/abs/1605.00558
