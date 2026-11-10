; RetroCloud TestPad - a tiny NES program written for this project (MIT).
; Purpose: deterministic video / audio / input test content with no copyright issues.
;  D-pad  : moves the white square
;  A      : plays a square-wave tone while held
;  B      : cycles the background colour
;  Start  : resets square to the centre
;  Select : toggles the scrolling noise background (on by default). It gives the
;           encoder busy, full-screen motion similar to a scrolling platformer.
.segment "HEADER"
  .byte "NES", $1A, 2, 1, $00, $00, 0,0,0,0,0,0,0,0

.segment "ZEROPAGE"
pad:     .res 1
prevpad: .res 1
px:      .res 1
py:      .res 1
bgc:     .res 1
nmi_ok:  .res 1
scrollx: .res 1
scrolly: .res 1
busy:    .res 1

.segment "CODE"
reset:
  sei
  cld
  ldx #$40
  stx $4017
  ldx #$FF
  txs
  inx
  stx $2000
  stx $2001
  stx $4010
@vb1: bit $2002
  bpl @vb1
  lda #0
  ldx #0
@clr:
  sta $0000,x
  sta $0100,x
  sta $0300,x
  sta $0400,x
  sta $0500,x
  sta $0600,x
  sta $0700,x
  lda #$FF
  sta $0200,x      ; hide all sprites
  lda #0
  inx
  bne @clr
@vb2: bit $2002
  bpl @vb2

  lda #120
  sta px
  lda #112
  sta py
  lda #$01
  sta bgc

  jsr write_palette
  jsr fill_nametables
  lda #1
  sta busy
  ; enable square 1
  lda #$01
  sta $4015

  lda #%10000000   ; NMI on
  sta $2000
  lda #%00011110   ; show bg + sprites (incl. leftmost 8px)
  sta $2001
@forever:
  jmp @forever

; fill both nametables with tiles 2..255 in a scattered order, attributes vary
fill_nametables:
  lda $2002
  lda #$20
  sta $2006
  lda #$00
  sta $2006
  ldy #8            ; 8 * 256 = 2048 bytes = $2000-$27FF (2 nametables + attrs)
  ldx #0
@nt:
  txa
  asl a
  asl a
  adc #$35
  eor scrolly
  ora #$02
  sta $2007
  inx
  bne @nt
  inc scrolly
  dey
  bne @nt
  lda #0
  sta scrolly
  rts

write_palette:
  lda $2002
  lda #$3F
  sta $2006
  lda #$00
  sta $2006
  lda bgc
  sta $2007        ; universal background colour
  lda #$12         ; bg palette 0: blue / red / green (no white: tests look for the white square)
  sta $2007
  lda #$16
  sta $2007
  lda #$1A
  sta $2007
  lda #$3F
  sta $2006
  lda #$11
  sta $2006
  lda #$30         ; sprite palette 0, colour 1 = white
  sta $2007
  lda #$16
  sta $2007
  lda #$27
  sta $2007
  rts

read_pad:
  lda pad
  sta prevpad
  lda #1
  sta $4016
  lda #0
  sta $4016
  ldx #8
@rl:
  lda $4016
  lsr a
  rol pad
  dex
  bne @rl
  rts

nmi:
  pha
  txa
  pha
  ; sprite DMA
  lda #$00
  sta $2003
  lda #$02
  sta $4014
  jsr write_palette
  lda busy
  beq :+
  inc scrollx
  lda scrolly
  clc
  adc #1
  cmp #240
  bcc @sy
  lda #0
@sy:
  sta scrolly
: lda scrollx
  sta $2005
  lda scrolly
  sta $2005
  lda #%10000000
  sta $2000

  jsr read_pad
  ; pad bits: A B Sel St U D L R (bit7..bit0)
  lda pad
  and #%00001000   ; up
  beq :+
  dec py
  dec py
: lda pad
  and #%00000100   ; down
  beq :+
  inc py
  inc py
: lda pad
  and #%00000010   ; left
  beq :+
  dec px
  dec px
: lda pad
  and #%00000001   ; right
  beq :+
  inc px
  inc px
: lda pad
  and #%00010000   ; start
  beq :+
  lda #120
  sta px
  lda #112
  sta py
: ; Select: toggle scrolling background on press edge
  lda prevpad
  and #%00100000
  bne :+
  lda pad
  and #%00100000
  beq :+
  lda busy
  eor #1
  sta busy
: ; B: cycle bg colour on press edge
  lda prevpad
  and #%01000000
  bne :+
  lda pad
  and #%01000000
  beq :+
  inc bgc
  lda bgc
  and #$0F
  cmp #$0D
  bcc :+
  lda #$01
  sta bgc
: ; A: tone
  lda pad
  and #%10000000
  beq @silent
  lda #%10111111   ; duty 50%, const vol 15
  sta $4000
  lda #$00
  sta $4001
  lda #$FD         ; ~440Hz
  sta $4002
  lda prevpad
  and #%10000000
  bne @spr
  lda #$00
  sta $4003
  jmp @spr
@silent:
  lda #%10110000
  sta $4000
@spr:
  ; 2x2 metasprite (16x16 square) at px,py using tile 1
  ldx #0
  lda py
  sta $0200
  sta $0204
  clc
  adc #8
  sta $0208
  sta $020C
  lda #1
  sta $0201
  sta $0205
  sta $0209
  sta $020D
  lda #0
  sta $0202
  sta $0206
  sta $020A
  sta $020E
  lda px
  sta $0203
  sta $020B
  clc
  adc #8
  sta $0207
  sta $020F
  pla
  tax
  pla
irq:
  rti

.segment "VECTORS"
  .word nmi, reset, irq

.segment "CHARS"
  .res 16, $00          ; tile 0: empty
  .res 8, $FF           ; tile 1: solid (plane 0)
  .res 8, $00           ;          (plane 1) -> colour 1
  .incbin "noise.chr"   ; tiles 2..255: deterministic noise (tools: gen_chr.py)
  .res 8192-4096, $00
