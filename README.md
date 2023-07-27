Full Quiet OSS
==============

This is a collection of Python 3 scripts originally developed while
building *[Full Quiet]* by Retrotainment Games.  We are releasing
them as [free software] to give back to the community of developers
who use the [cc65] toolchain to develop software for 6502 processors
in assembly language.

These programs benefit all ca65 users:

- `freebytes.py`  
  Given an ld65 map file, reads the segment list and totals the used
  and free space in each memory area.
- `hotbssvars.py`  
  Given an ld65 debug file, finds which variables are most frequently
  accessed from code in the fixed bank.  Moving these variables from
  BSS to zero page may make the code smaller.
- `ld65ramuse.py`  
  Given a map file produced by ld65, finds the fraction of each
  ROM and RAM segment occupied by each object file.  Useful for
  finding parts of a program to study for size optimization.
- `rmcomments.py`  
  Removes comments from a ca65 project's source code.  Useful for
  counting source lines of code.
- `symdealias.py`  
  Given an ld65 debug file, finds one canonical name for each label
  and removes all others.  Useful to work around quirks in some
  versions of Mesen and other emulators that load ld65 debug files.
- `tracemake.py`  
  Wraps `strace` on Linux to find all files read or written
  while building a program.

These are more specific to projects targeting the
Nintendo Entertainment System (NES):

- `strips.py`, `metasprite.s`, and `metasprite.inc`  
  Given a sprite sheet image and a file specifying what rectangles
  in the image belong to each cel, converts each cel to a set of
  8×16-pixel objects, packs them into 1 KiB CHR banks, and emits
  data tables of what objects make up each cel.  Comes with sample
  code to draw a cel.
- `nstripes.py`  
  Given a 4-color image and a file specifying what rectangles in the
  image belong to each background object, extracts a tile set and
  nametable fragments in [Stripe Image] format.  Useful for making
  background objects to draw with the [Popslide] library.
- `pack8k.py`  
  Given a set of object files and an ld65 configuration script
  template containing a list of 8 KiB memory areas, pack these object
  files' segments into unused spaces in these memory areas.
- `prototype.py`  
  Adds a small graphic to a ROM representing a serial number.
  Useful for customizing numbered copies of a game.
- `romusage.py`  
  Converts an NES CHR file to an image.  Useful for converting an
  entire ROM to an image to visualize used and free portions or to
  visualize patterns that may be compressible.  Optionally sanitizes
  the image for publication on a developer blog by reducing its pixel
  size by half, so that viewers cannot recover the ROM data, and
  labeling it with names of memory areas from an ld65 config file.

Licensing
---------

This uses a mix of permissive licenses.

- Most files are under the Apache License 2.0.
- A few files, such as the metasprite sample code, are under the
  zlib License.
- The [pagination solver] used by strips.py is under the MIT (Expat)
  license.

[Full Quiet]: https://www.retrotainmentgames.com/collections/video-games/products/copy-of-full-quiet-regular-edition-nes-game-green-glow-cartridge-complete-in-box-cib
[free software]: https://www.gnu.org/philosophy/free-sw.en.html
[cc65]: https://cc65.github.io/
[Stripe Image]: https://www.nesdev.org/wiki/Tile_compression#NES_Stripe_Image_RLE
[Popslide]: https://forums.nesdev.org/viewtopic.php?t=15440
[pagination solver]: https://github.com/pagination-problem/pagination
