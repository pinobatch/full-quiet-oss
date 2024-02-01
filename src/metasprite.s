; metasprite.s
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

.include "metasprite.inc"

.zeropage
; These are the most used according to tools/actor_vars.py
actor_frame:     .res NUM_ACTORS
actor_x:         .res NUM_ACTORS  ; whole pixels
actor_xscr:      .res NUM_ACTORS  ; "screens" (256 pixels)
actor_y:         .res NUM_ACTORS
actor_yscr:      .res NUM_ACTORS
actor_facing:    .res NUM_ACTORS

.bss
; Slot numbers used this frame
obj_windows:        .res 4
front_prio_closest: .res 1

; Variables for subpixel movement
actor_xsub:      .res NUM_ACTORS  ; sub: 1/256 pixels
actor_ysub:      .res NUM_ACTORS

; index into enemy vtables
actor_class:     .res NUM_ACTORS
; if the sprite sheet associated with an actor class has only one 1K
; page, actors using that sheet share a window
actor_window:    .res NUM_ACTORS  ; 0-3
; Used to hide an actor or have an actor request to be drawn
; in front of the player (among other game-specific things)
actor_flags:     .res NUM_ACTORS

.segment "CODE"
; WINDOW SEARCH ;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;
; Finds a free window for the given actor class's sprite sheet.
; If the sheet is 1 page, tries to share the window with another
; sprite with the same sheet.
; @param A the desired actor class
; @return A = window ID (0-3 normal, 4-7 small) in A or negative
;     for none available; N flag set appropriately
.proc find_window_for_class
  tay
  lda class_to_spritesheet,y
.endproc
.proc find_window_for_sheet
usedwindows = $0C
desiredsheet = $09
thisactorwindow = $0A
thisactorsheet = $0B

  ; Obj window 3 (MMC3 window 5, $1C00-$1FFF)
  ; is hardcoded to utility sprites
  cmp #SHEET_Utility_sprites
  bne not_utility
    lda #UTILITY_WINDOW
    rts
  not_utility:

  ; Ensure this sheet is even loaded
  tax
  lda sheet_slot_base,x
  bpl is_loaded

.if ::MSPR_REQUEST_SHEET
    ; If not, and no load is in progress, request that it be loaded
    lda sprload_left
    bne :+
      stx sprload_sheetid
      jsr sprload_request_sheet
    :
.endif
    lda #$FF
    rts
  is_loaded:
  cmp #VRAM_SIZE
  bcc not_small
    lda #SMALL_WINDOW|$04
    rts
  not_small:
  stx desiredsheet
  lda #$FF
  sta usedwindows+3
  sta usedwindows+2
  sta usedwindows+1
  lda small_sheet_tiles_used
  beq :+
    lda #63
    sta usedwindows+SMALL_WINDOW
  :
  ldx #NUM_ACTORS-1
  actorloop:
    lda actor_frame,x
    ora actor_xscr,x
    bmi inactive_actor

    ; Look up this actor's window and sheet
    ldy actor_class,x
    lda class_to_spritesheet,y
    sta thisactorsheet

    ; Mark this window as taken
    ldy actor_window,x
    cpy #4
    bcs inactive_actor
    sty thisactorwindow
    sta usedwindows,y

    ; If the window's sheet matches and isn't multi-page, use it
    cmp desiredsheet
    bne not_sharing
    tay
    lda sheet_num_pages,y
    bpl :+
      lda #1
    :
    lsr a  ; at least 2?
    bne not_sharing
      lda thisactorwindow
      rts
    not_sharing:
    inactive_actor:
    dex
    bne actorloop

  ; Cannot share a sheet with any window.  Find an unused window.
  ldx #2  ; hardcode window 3 to utility sprites
  windowloop:
    lda usedwindows,x
    bpl window_not_free
      txa
      rts
    window_not_free:
    dex
    bne windowloop
  lda #$FF
  rts
.endproc

;;
; Writes obj_windows to the MMC3 registers
.proc set_obj_windows
  ldx #2
  stx $8000
  lda obj_windows+0
  sta $8001
  inx
  stx $8000
  lda obj_windows+1
  sta $8001
  inx
  stx $8000
  lda obj_windows+2
  sta $8001
  inx
  stx $8000
  lda obj_windows+3
  sta $8001
  rts
.endproc

.code
; FRONT PRIORITY SPRITE SEARCH ;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.proc find_front_prio_closest
best_dist = $00

  lda #$FF
  sta front_prio_closest
  lda #16  ; half hero's maximum width
  sta best_dist
  ldx #NUM_ACTORS-1
  actorloop:

    ; Is this sprite front prio?
    lda actor_flags,x
    and #ACTORF_IN_FRONT
    beq toofar

    ; Calculate the distance
    sec
    lda actor_x,x
    sbc actor_x+0
    tay  ; Y = low byte of X distance
    lda actor_xscr,x
    sbc actor_xscr+0
    bcs :+
      eor #$FF
    :
    bne toofar  ; If the absolute distance exceeds 256 pixels, it's too far
    tya
    bcs :+
      eor #$FF
      adc #1
    :
    cmp best_dist
    bcs toofar
      sta best_dist
      stx front_prio_closest
    toofar:
    dex
    bne actorloop
  rts
.endproc

; ACTOR DRAWING ;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

.segment "MSPRCODE"

.proc set_mspr_xy_actor_x
  lda actor_xsub,x
  asl a
  lda actor_x,x
  sbc camera_x
  sta mspr_xlo
  lda actor_xscr,x
  sbc camera_x+1
  ; removed level_flipped support, as our new bg engine is 8-way
  sta mspr_xhi

  ; The previous sets carry if the actor is in the right half of the
  ; pixel and clears it otherwise.  This causes the on-screen
  ; position to be +0 or -1.  We instead want it to be +1 or 0.
  inc mspr_xlo
  bne :+
    inc mspr_xhi
  :

  sec
  lda actor_y,x
  sbc camera_y
  sta mspr_ylo
  lda actor_yscr,x
  sbc camera_y+1
  sta mspr_yhi
  rts
.endproc

.proc draw_actor
sheetid = $0D
sheetftb = $0E
  ; 2022-03-09: add a flag to temporarily hide an actor while physics
  ; continue otherwise unaffected
  lda actor_flags,x
  and #ACTORF_HIDE
  bne draw_nothing

  ; Set sprite bank for actor X
  ldy actor_class,x
  bmi draw_nothing
  lda class_to_spritesheet,y
  sta sheetid
  tay
  lda sheet_frametobank_lo,y
  sta sheetftb
  lda sheet_frametobank_hi,y
  sta sheetftb+1
  ldy actor_frame,x
  bpl frame_exists
  draw_nothing:
    rts
  frame_exists:

  ; Position sprite relative to camera
  jsr set_mspr_xy_actor_x
  clc
  lda mspr_xlo
  adc #$80
  lda mspr_xhi
  adc #0
  cmp #2
  bcs draw_nothing

;  clc
  lda (sheetftb),y
  ldy sheetid
  adc sheet_slot_base,y
  ldy actor_window,x
  cpy #4
  bcc actor_not_loaded_small
    ; For small actor, mspr_window is stored in the sprite sheet
    sta mspr_window
    lda #SMALL_SLOT
    sta obj_windows+SMALL_WINDOW
    bpl window_set
  actor_not_loaded_small:
    sta obj_windows,y
    tya
    lsr a
    ror a
    ror a
    sta mspr_window
  window_set:
  lda actor_facing,x
  sta mspr_attr
  lda actor_frame,x
  pha
  ldy actor_class,x
  lda class_to_spritesheet,y
  tax
  pla
  ; fall through
.endproc

;;
; Draws one metasprite.
;
; The data for each cel consist of a list of horizontal rows of
; 8x16-pixel objects, ordered from front to back:
;
; - X, Y, flags, tile IDs
; - X, Y, flags, tile IDs
; - X, Y, flags, tile IDs
; - $00 terminator ends the list
;
; X and Y are the coordinates at the top left of this row of objects,
; where the cel's center is at (128, 128).  Use of excess-128
; representation makes clipping at the sides more efficient.
;
; Flags is %000LLLPP, where
;
; - P is the palette for this row
; - L is the number of objects in the row minus 1
;
; This is followed by L+1 bytes representing objects in the row.
; Each are %VHTTTTTA, where
;
; - V = 1 to flip this object vertically
; - H = 1 to flip this object horizontally
; - T is the base tile ID within the 1K page (0, 2, 4, 6, ..., 62)
; - A = 1 to use the next tile ID when the actor faces left
;
; @param X sprite sheet ID, offset into sheet_msprtables
; @param A frame number within sheet, offset into that sheet's table
; @param mspr_xlo, mspr_xhi, mspr_ylo, mspr_yhi actor's position on screen
; @param mspr_window amount to add to all tile IDs (e.g. $00, $40, $80, $C0)
; @param mspr_attr flags 0HP000CC, where H faces left, P goes behind the
;        background, and C is XOR'd with each row's color
.proc draw_metasprite
stripy = $08
stripattr = $0A
stripxlo = $0B
stripxhi = $0C
stripwidleft = $0D
stripptrlo = $0E
stripptrhi = $0F

  ; Find this metasprite's data
  asl a
  tay

  .if ::PROFILE_DRAW_ACTOR
    lda #BG_ON|OBJ_ON|LIGHTGRAY
    sta PPUMASK
  .endif

  lda sheet_msprtables_lo,x
  sta stripxlo
  lda sheet_msprtables_hi,x
  sta stripxhi
  lda (stripxlo),y
  sta stripptrlo
  iny
  lda (stripxlo),y
  sta stripptrhi
  ; N should be set or we dun goofed

  ; Subtract 128 to allow use of offset-binary coordinates
  clc
  lda #<-128
  bit mspr_attr
  bvc :+
    lda #<-135  ; Subtract 7 more if horizontally flipped
  :
  adc mspr_xlo
  sta mspr_xlo
  bcs :+
    dec mspr_xhi
    sec
  :
  lda mspr_ylo
  sbc #129  ; Subtract 1 more because of secondary OAM's 1 line delay
  sta mspr_ylo
  bcs :+
    dec mspr_yhi
  :

  ; mspr_window is $00, $40, $80, or $C0, added to each tilenum
  ; mspr_window for small sheets can be $40, $42, $44, $46, ..., $7E
  ; Bit 0 of each tilenum tells whether an 8x16 pixel tile is alone
  ; or in a flipped pair (t-1) and (t+1)
  lda mspr_attr
  and #$40
  cmp #$40
  lda mspr_window
  and #$FE
  adc #$00
  sta mspr_window

  ; Now start reading sprite strip bytecode:
  ; x, y, attrs+length, tilenums
  ldy #0
  ldx oam_used

next_strip:
  lda (stripptrlo),y
  bne not_done

    .if ::PROFILE_DRAW_ACTOR
      lda #BG_ON|OBJ_ON
      sta PPUMASK
    .endif

    stx oam_used
    rts
  not_done:
  iny
  ; N should be clear or we dun goofed (>128-byte definition).  Set a breakpoint.
  bit mspr_attr
  bvc :+
    eor #$FF
  :
  clc
  adc mspr_xlo
  sta stripxlo
  lda #0
  adc mspr_xhi
  sta stripxhi
  lda (stripptrlo),y
  iny
  clc
  adc mspr_ylo
  sta stripy

  ; Clip against y=0 and y=256
  lda #0
  adc mspr_yhi
  bne is_offscreen_y

  ; Clip against this draw call's clip rectangle (for e.g. water)
  lda stripy
.if ::MSPR_CLIP_RECT
  cmp mspr_cliptop
  bcc is_offscreen_y
  cmp mspr_clipbottom
.else
  cmp #$EF
.endif
  bcc not_offscreen_y

  is_offscreen_y:
    lda (stripptrlo),y
    iny
    lsr a
    lsr a
    and #$07
    sty stripwidleft
    sec
    adc stripwidleft
    tay
    jmp next_strip
  not_offscreen_y:

.if ::MSPR_WRITE_EXTENTS
  ; Store this metasprite's bounding rect
  cmp mspr_topmost
  bcs :+
    sta mspr_topmost
  :
  cmp mspr_bottommost
  bcc :+
    sta mspr_bottommost
  :
.endif

  lda mspr_attr
  and #$40
  cmp #$40
  ; third byte of strip is
  ; 7654 3210
  ; |||| ||++- color
  ; |||+-++--- width of strip minus 1
  ; ||+------- draw behind background
  ; |+-------- draw individual tiles flipped horizontally
  ; +--------- draw strip flipped vertically
  ; Current tools emit bits 7 and 6 false, instead flipping
  ; individual sprites.
  lda (stripptrlo),y
  and #$E3
  sta stripattr
  eor (stripptrlo),y
  lsr a
  lsr a
  sta stripwidleft
  iny

next_sprite:
  lda stripxhi
  bne sprite_is_off_side
    lda stripxlo
.if ::MSPR_CLIP_RECT
    cmp mspr_clipleft
    bcc sprite_is_off_side
    cmp mspr_clipright
    bcs sprite_is_off_side
.endif
    sta OAM+3,x

.if ::MSPR_WRITE_EXTENTS
    cmp mspr_leftmost
    bcs :+
      sta mspr_leftmost
    :
    cmp mspr_rightmost
    bcc :+
      sta mspr_rightmost
      clc
    :
.endif

    lda stripy
    sta OAM+0,x

    lda (stripptrlo),y
    and #$3F         ; mask out flip bits
    ; clc  ; cleared by cmp mspr_rightmost block
    adc mspr_window  ; window low bit: use next tilepair if hflipped
    ora #$01         ; on MMC3, sprites must always use the right pattern table
    sta OAM+1,x

    lda (stripptrlo),y
    and #$C0         ; strip data bits 7-6: flip
    eor stripattr
    eor mspr_attr
    sta OAM+2,x
    inx
    inx
    inx
    inx
  sprite_is_off_side:

  iny  ; advance to next tilenum
  ; Add 8 or -8 to sprite
  lda stripxlo
  clc
  bit mspr_attr
  bvs flipped_so_left8
  adc #8
  bcc have_new_stripxlo
  inc stripxhi
  bcs have_new_stripxlo
flipped_so_left8:
  adc #<-8
  bcs have_new_stripxlo
  dec stripxhi
have_new_stripxlo:
  sta stripxlo
  dec stripwidleft
  bpl next_sprite
  jmp next_strip
.endproc
