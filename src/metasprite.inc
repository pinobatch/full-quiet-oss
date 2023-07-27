; metasprite.inc
; Plots an actor as objects
;
; Copyright 2023 Retrotainment Games LLC
;
; This software is provided 'as-is', without any express or implied
; warranty.  In no event will the authors be held liable for any
; damages arising from the use of this software.
; 
; Permission is granted to anyone to use this software for any
; purpose, including commercial applications, and to alter it and
; redistribute it freely, subject to the following restrictions:
; 
; 1. The origin of this software must not be misrepresented; you
;    must not claim that you wrote the original software. If you use
;    this software in a product, an acknowledgment in the product
;    documentation would be appreciated but is not required.
; 2. Altered source versions must be plainly marked as such, and
;    must not be misrepresented as being the original software.
; 3. This notice may not be removed or altered from any source
;    distribution.

OAM = $0200

; configuration flags
PROFILE_DRAW_ACTOR = 0
MSPR_WRITE_EXTENTS = 1
MSPR_CLIP_RECT = 1
MSPR_REQUEST_SHEET = 1

; In games using 32K CHR RAM, one of the four windows may be
; configured for a runtime combination of small sprite sheets that
; total less than 1 KiB
SMALL_WINDOW = 1
SMALL_SLOT = 26
.import small_sheet_tiles_used

VRAM_SIZE = 32
NUM_ACTORS = 12

; this sheet ID is always drawn to a specific window
.globalzp SHEET_Utility_sprites
UTILITY_WINDOW = 3

; map actor classes to sprite sheet IDs
.global class_to_spritesheet

; size of a sprite sheet in 1K pages
; (negative means 1 and may signify a small sheet)
.global sheet_num_pages

; map sprite sheets to 1K banks of video memory
; (usually 16-31; small 64-126; >=128: not loaded)
.global sheet_slot_base

; addresses within MSPRDATA of pointers to each sheet's frame list
.global sheet_msprtables_lo, sheet_msprtables_hi

; addresses within MSPRDATA of tables for each sheet
.global sheet_frametobank_lo, sheet_frametobank_hi

; Camera position
.global camera_x, camera_y

; Index into OAM of next address into which to draw objects
.globalzp oam_used

; Arguments passed here
mspr_xlo = $02
mspr_xhi = $03
mspr_ylo = $04
mspr_yhi = $05
mspr_window = $06
mspr_attr = $07

.if MSPR_WRITE_EXTENTS || MSPR_CLIP_RECT
  .importzp decodetmp
  mspr_clipleft   = decodetmp+0
  mspr_clipright  = decodetmp+1
  mspr_cliptop    = decodetmp+2
  mspr_clipbottom = decodetmp+3
  mspr_leftmost   = decodetmp+4
  mspr_rightmost  = decodetmp+5
  mspr_topmost    = decodetmp+6
  mspr_bottommost = decodetmp+7
.endif

.if MSPR_REQUEST_SHEET
  .global sprload_left, sprload_sheetid
  .global sprload_request_sheet
.endif

; .globalzp choices per tools/actor_vars.py
.globalzp actor_frame, actor_facing
.globalzp actor_x, actor_xscr, actor_y, actor_yscr

ACTORF_IN_FRONT = $10      ; Draw in front of hero if close to hero
ACTORF_HIDE = $02          ; Do not draw
.global actor_flags
.global actor_xsub, actor_ysub, actor_class, actor_window
.global obj_windows, front_prio_closest

; Methods
.global set_obj_windows, find_front_prio_closest
.global draw_actor, set_mspr_xy_actor_x, draw_metasprite
.global find_window_for_class, find_window_for_sheet
