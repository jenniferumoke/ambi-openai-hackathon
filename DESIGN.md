---
name: Ambi Desktop Companion
description: An existing Rive companion with explicit voice controls and visible actions.
colors:
  blue: "#5b8def"
  teal: "#53cdd0"
  rose: "#ee8eb5"
  butter: "#f2ce71"
  peach: "#efa483"
  lilac: "#bda1e4"
  navy: "#0d1b2a"
  navy-panel: "#102134"
  navy-text: "#f4f7ff"
  navy-muted: "#b7c7df"
  navy-border: "#2b4058"
  voice-light: "#d9e8ff"
  white: "#fff"
  black: "#000"
  ink: "#171717"
  muted: "#606060"
  button-dark: "#202020"
  button-hover: "#393939"
  control-border: "#b8b8b8"
  divider: "#e4e4e4"
  setup: "#181818"
  setup-preview: "#252525"
  success: "#26745e"
  error: "#a52b2b"
  error-dark: "#ffb3b3"
typography:
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
  presence:
    fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "21px"
    fontWeight: 600
    letterSpacing: "-.025em"
  title:
    fontSize: "20px"
    fontWeight: 600
    letterSpacing: "-.4px"
  hint:
    fontSize: "12px"
    lineHeight: 1.6
  label:
    fontSize: "11px"
rounded:
  button: "7px"
  field: "8px"
  setup: "18px"
  pill: "999px"
spacing:
  tight: "4px"
  small: "8px"
  control: "12px"
  medium: "16px"
  section: "24px"
  panel: "28px"
components:
  button-primary:
    backgroundColor: "{colors.button-dark}"
    textColor: "{colors.white}"
    rounded: "{rounded.pill}"
    padding: "12px 24px"
    height: "48px"
    width: "200px"
  button-primary-hover:
    backgroundColor: "{colors.button-hover}"
  button-primary-dark:
    backgroundColor: "{colors.voice-light}"
    textColor: "{colors.navy}"
    rounded: "{rounded.pill}"
    padding: "12px 24px"
  button-secondary:
    rounded: "{rounded.button}"
    padding: "7px 12px"
  message-field:
    rounded: "{rounded.field}"
    padding: "11px 12px"
    width: "100%"
  activity-panel:
    padding: "52px 28px 24px"
---

# Design System: Ambi Desktop Companion

## Overview

**Creative North Star: "A voice-first companion whose actions stay visible"**

This phrase comes from the current direction contract. It describes an extension of the incumbent Ambi interface, not a newly selected visual world. The organic Rive mascot, saved accent, background, scale and motion choices remain the identity. The user's requested larger mascot, stronger activity tint and clearer voice hierarchy are the durable changes recorded here.

The companion uses plain surfaces, short state language and direct controls. Its mascot is expressive, while readable state text and task details explain what is happening. Typing and action details expand when needed; this companion composition is not a universal layout rule for unrelated products.

**Key Characteristics:**
- Existing organic Rive character and saved personal appearance.
- Clear voice state with a single primary conversation control.
- Readable action history and explicit permission and stop controls.
- Accent feedback at active or preview edges, with a transparent screen centre.

## Colors

The default blue and navy identity sits alongside retained white and black backgrounds and six selectable mascot accents. The frontmatter records source values, not a replacement palette.

### Primary
- **Blue:** default saved accent; used for the selected character treatment and activity frame.
- **Teal, Rose, Butter, Peach and Lilac:** alternative saved accents from the existing appearance selector. The selected value sets the activity frame colour; it does not recolour every text or control.

### Neutral
- **Navy / Navy Panel / Navy Text / Navy Muted / Navy Border:** default background, action panel, readable text, supporting copy and panel boundary.
- **White / Black / Ink / Muted:** retained light and black themes and their text roles.
- **Button Dark / Button Hover / Voice Light:** primary conversation control states across light and dark surfaces.
- **Setup / Setup Preview:** incumbent dark appearance dialog layers, independent of the main background choice.
- **Success / Error / Error Dark:** task result and error feedback; do not substitute mascot pose for readable status.

**The Selected Accent Rule.** Use the saved accent for character treatment and activity feedback. Preserve the user's background and appearance choices.

## Typography

The implemented body stack is the platform system sans stack in the frontmatter. It supports compact native companion controls rather than a separate editorial display identity.

### Hierarchy
- **Presence:** the main ready/listening/working/permission state, using the presence role; balanced wrapping keeps it legible beside the mascot.
- **Title:** action panel headings use the title role.
- **Body:** conversation text and controls inherit the body role; conversation paragraphs use a more open line height (1.7).
- **Hint:** voice instructions use the hint role and a short measure (31ch).
- **Label:** task metadata and utility controls use the label role. These smaller incumbent controls are not a prescription for primary interaction text.

## Layout

The resting surface is one centred column. Character space uses top/side/bottom padding (52px / 16px / 24px); voice controls cap at (340px). The source sizes the Rive canvas with an aspect ratio (340 / 240), width `min(calc(150vw * var(--character-scale)), 660px)` and a height allowance `calc(100% - 210px)`. Saved scale defaults to (.78), constrained to (.35–.95). This describes the canvas, not the visible nontransparent mascot bounds; do not freeze a screenshot's artwork height into a token.

Expanded actions use two columns, `minmax(300px, .9fr) minmax(360px, 1fr)`. The mascot canvas then uses `calc(155% * var(--character-scale))`, capped at (650px), with `calc(100% - 230px)` height allowance. At widths up to (680px), expanded layout stacks a character/control row above actions, with the top row taking `minmax(160px, 40%)`. The character row uses columns (.9fr / 1fr), an (8px) gap and canvas width `calc(240% * var(--character-scale))`. Narrow presence text becomes (16px), with a (40px) minimum primary button height. The voice hint is hidden there to preserve room for state and controls.

Native windows start at (560 × 600) with minimum dimensions (360 × 440); expansion requests width (940px), retaining at least (600px) height within the available screen. A (940 × 640) preview is an evidence viewport, not the native window's fixed size.

## Elevation & Depth

Resting controls and action rows use borders and tonal layers. The distinctive glow is reserved for listening feedback and an active or explicitly labelled preview frame. The browser frame uses a (3px) edge with `inset 0 0 48px 12px color-mix(in srgb, var(--agent-accent, #53cdd0) 46%, transparent)`. The listening control uses a (4px) accent ring mixed at (30%). Dialog backdrops darken the content behind them.

Native frame implementations intentionally remain platform-specific: both fade inward through a (72px) band with a (3px) edge and (16px) zero-offset bloom at (.8) opacity. macOS starts the wash at (.46) alpha, uses a (.9) stroke and (14px) corner radius. Windows starts at (118/255) alpha, uses an opaque accent stroke and (12px) border corners. These are source comparisons, not verified installed rendering equivalence.

## Shapes

Primary conversation and appearance-save controls are pills. Regular controls have gently curved button corners; fields and small containers use the field radius. The appearance dialog uses the setup radius. State markers and colour swatches are circles. Actions remain open rows separated by rules, rather than a grid of decorative cards.

## Components

### Buttons

The primary conversation control pairs a microphone SVG with a plain action label. Its minimum geometry is recorded in frontmatter; those minimums are CSS constraints, not fixed size. Hover changes the surface, disabled state uses (.5) opacity, and listening adds the accent ring. Dark themes invert the control to Voice Light. Narrow expanded layout reduces padding to (9px 14px).

Secondary buttons use thin borders or an underlined text treatment for voice alternatives. Stop keeps a visible border and semibold text, independently of whether the optional composer is shown. Button and select keyboard focus use a (2px) current-colour outline with (4px) offset.

### Inputs / Fields

The optional message composer is a full-width transparent textarea, with a thin border, rounded corners and accent caret. Navy adds the Navy background. It appears only after Type instead; the paired action mode selector appears in that typing state. Setup name, range and segmented appearance controls retain their incumbent styles.

### Action rows / Containers

Actions use native disclosure rows with a circular state marker, wrapping title, compact status and optional detail. Running markers breathe over (1.2s); reduced motion disables that animation. Completed and failed markers use semantic colours and readable status text. The action panel scrolls independently.

### Ambi character

Keep the existing `ambi-companion.riv` artboard and state machine. The companion canvas backing store is stable at (1360 × 960); CSS controls its displayed size. Saved Still and OS reduced-motion preferences disable Rive play. Pose selection is presentation-only; a newly observed completed job can show success for (3000ms). An initial completed snapshot does not trigger a new success pose.

### Activity frame

Keep preview and active labels distinct. The native display frame passes pointer input through; its separate control panel accepts Stop task or Close preview. The browser frame is a UI preview of the same feedback idea, not evidence of screen-control permission. No wake-word detector or LED transport is part of this design change.

## Do's and Don'ts

### Do:
- **Do** retain the existing Rive character and saved appearance choices.
- **Do** keep the primary conversation action, readable state and Stop easy to find.
- **Do** preserve reduced-motion and Still behavior for character and activity feedback.
- **Do** distinguish preview, permission, running and completed states in readable text.

### Don't:
- **Don't** infer action success or microphone permission from motion or glow.
- **Don't** treat a screenshot's nontransparent mascot bounds as a fixed canvas-size token.
- **Don't** replace optional typing with an always-present composer on the resting companion surface.

Not canonized: the incumbent system-font display treatment in setup and its small utility-label sizes are recorded as current implementation context, not endorsed as new display or accessibility rules. Final visual review and installed runtime verification remain separate from this source extraction.


## Goal review presentation

Keep the current goal action or progress check pinned in the existing activity header so older history does not conceal ongoing work. Checking progress remains in progress until the read-only review returns; only checked outcomes use Checked. Paused and Stopped remain distinct, and Stop stays visible for the whole goal, including review and recovery. Show concise observations and selected next steps, never hidden model reasoning or raw screenshot/credential data. Retain the established controls, typography and mascot hierarchy.
