# GUAPA DESIGN GUIDE

Reference this file when styling any Guapa page or component. These are the exact values and patterns used across the site.

---

## Core Palette

| Token | Hex | Usage |
|-------|-----|-------|
| --black | #0a0a0a | Page background, primary bg |
| --dark | #111111 | Alternate section backgrounds |
| --gray-900 | #1a1a1a | Card backgrounds |
| --gray-800 | #2a2a2a | Borders, dividers, subtle backgrounds |
| --gray-600 | #666666 | Muted text, timestamps, metadata |
| --gray-400 | #999999 | Secondary text, nav links (default), body copy |
| --gray-200 | #e5e5e5 | Light text on dark (rarely used) |
| --white | #ffffff | Headings, primary text, emphasis |
| --pink | #e8a0b0 | Primary accent — links, active states, section titles, CTA hover |
| --pink-hover | #d88a9a | Pink interactive hover state |
| --pink-muted | #c4848f | Subtle pink — outline button borders |
| --yellow | #f0c014 | Highlight accent — primary CTA buttons, "view all" links, focus outlines, text selection |
| --yellow-hover | #d4a912 | Yellow interactive hover state |

### Rules
- NEVER use gradients for fills or backgrounds (flat colors only)
- Pink = primary brand accent (links, highlights, hover states)
- Yellow = action/CTA color (buttons, "view all", focus rings, text selection)
- Blue (#88a8d4) = data visualizations only (charts, metrics, data-heavy sections)
- Background is always #0a0a0a or #111111 — never white, never light

---

## Typography

### Fonts
- **UI font**: `'Instrument Sans', -apple-system, sans-serif` — everything: nav, body, labels, buttons, metadata
- **Editorial font**: `'Newsreader', Georgia, serif` — italic only, used for: hero headlines, "From the Collective" newspaper section, about section quotes, newsletter headings

### Load from Google Fonts
```html
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=Newsreader:ital,wght@0,400;1,400&display=swap" rel="stylesheet">
```

### Scale
| Element | Size | Weight | Font |
|---------|------|--------|------|
| Page title (h1) | clamp(2.5rem, 6vw, 4rem) | 700 | Instrument Sans |
| Hero headline | clamp(2.5rem, 6vw, 4rem) | 400 italic | Newsreader |
| Section title | 1.5rem | 600 | Instrument Sans |
| Card title | 1rem–1.1rem | 600 | Instrument Sans |
| Body text | 0.9rem–1rem | 400 | Instrument Sans |
| Small labels | 0.7rem–0.8rem | 600 | Instrument Sans |
| Metadata / timestamps | 0.75rem–0.85rem | 400–500 | Instrument Sans |
| Uppercase labels | 0.65rem–0.75rem | 600–700, uppercase, letter-spacing: 0.05em–0.12em | Instrument Sans |
| Nav links | 0.9rem | 500 | Instrument Sans |
| Buttons | 0.85rem–0.9rem | 600 | Instrument Sans |

### Rules
- Newsreader is ONLY used italic — never upright, never bold
- Body line-height: 1.6
- Heading line-height: 1.1–1.3
- Letter-spacing: -0.02em on section titles, 0.05em on uppercase labels
- -webkit-font-smoothing: antialiased on body

---

## Spacing

| Token | Value | Usage |
|-------|-------|-------|
| --space-xs | 0.5rem (8px) | Tight gaps — between label and value, inner padding |
| --space-sm | 1rem (16px) | Standard gap — between elements, card padding |
| --space-md | 1.5rem (24px) | Section padding, nav padding, card inner spacing |
| --space-lg | 3rem (48px) | Between sections, major spacing |
| --space-xl | 5rem (80px) | Section top/bottom padding |
| --space-2xl | 8rem (128px) | Hero padding |

---

## Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| --radius-sm | 4px | Buttons, small tags, chips, badges |
| --radius-md | 8px | Cards, images, containers |
| --radius-lg | 12px | Large containers, about section image |

---

## Cards

The universal card pattern:

```css
.card {
    background: var(--gray-900);         /* #1a1a1a */
    border: 1px solid var(--gray-800);   /* #2a2a2a */
    border-radius: var(--radius-md);     /* 8px */
    padding: var(--space-md);            /* 1.5rem */
    transition: all 0.2s ease;
}

.card:hover {
    border-color: var(--pink);           /* #e8a0b0 */
    background: var(--gray-800);         /* #2a2a2a */
}
```

### Card variants across the site
- **Review/nav cards**: flex row, icon + content + arrow. Arrow fades in on hover with translateX.
- **Product cards**: vertical stack, image (aspect-ratio: 1) + info below.
- **Post cards**: vertical stack, image (16:9) + tag + title + excerpt. Hover: translateY(-2px) + pink border.
- **Chart cards** (economics): header + value + sparkline + footer. Top border accent line on hover.
- **Photo cards**: image fill + overlay on hover with title/price/details.

---

## Buttons

### Primary (yellow)
```css
background: var(--yellow);
color: var(--black);
/* hover: */ background: var(--yellow-hover);
```

### Secondary (white)
```css
background: var(--white);
color: var(--black);
/* hover: */ background: var(--gray-200);
```

### Outline
```css
background: transparent;
color: var(--white);
border: 1px solid var(--pink-muted);
/* hover: */ border-color: var(--pink); color: var(--pink);
```

### All buttons
- padding: 1rem 1.5rem
- font-size: 0.9rem, weight 600
- border-radius: 4px
- transition: 0.2s ease
- No gradients, no shadows

---

## Navigation

- Sticky top, z-index 100
- Background: #0a0a0a with 1px bottom border (gray-800)
- Logo: image (36px height) + "GUAPA inc" text (1.8rem, weight 700, "inc" at 0.6rem weight 400)
- Links: gray-400 default, white on hover, 0.9rem weight 500
- Social icon: gray-400, pink on hover
- CTA button (Shop →): pink bg, black text, 0.85rem weight 600
- Mobile: hamburger at 768px, full-screen overlay nav

---

## Sections

### Page headers (sub-pages)
```css
.page-header h1 {
    font-size: clamp(2.5rem, 6vw, 4rem);
    font-weight: 700;
    color: var(--pink);
}
/* Subtitle beside or below: gray-400, 1rem */
```

### Dividers
- Always 1px solid var(--gray-800)
- Used between: nav and content, section headers and content, card footers, sidebar items

### Full-width accent sections
- **Yellow banner**: background yellow, black text, used for featured announcements
- **Pink section**: background pink, black text, used for newsletter and "coming soon" banners

---

## Interactive States

| State | Treatment |
|-------|-----------|
| Hover (links) | color: white (from gray-400) |
| Hover (cards) | border-color: pink, bg shifts one shade lighter |
| Hover (images) | transform: scale(1.03–1.05), 0.3–0.5s ease |
| Hover (arrows/icons) | opacity 0→1, translateX(-5px→0) |
| Active/selected | pink text, pink border, rgba(232,160,176,0.1) background |
| Focus visible | 2px solid yellow outline, 2px offset |
| Text selection | yellow background, black text |

### Transition
- Default: `0.2s ease` for colors, borders, opacity
- Images: `0.3s–0.5s ease` for transforms
- All transitions use the `--transition` variable (0.2s ease) unless a slower image zoom

---

## Status Badges

Pattern from economics page — reusable for any status indicator:

```css
.badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 5px 12px;
    border-radius: 4px;
}

/* Green (live/active) */
color: #7ec89b;
background: rgba(126, 200, 155, 0.12);
border: 1px solid rgba(126, 200, 155, 0.2);

/* Red (down/negative) */
color: #d47878;
background: rgba(212, 120, 120, 0.12);
border: 1px solid rgba(212, 120, 120, 0.2);

/* Blue (info/data) */
color: #88a8d4;
background: rgba(136, 168, 212, 0.12);
border: 1px solid rgba(136, 168, 212, 0.2);

/* Yellow (highlight/pending) */
color: var(--yellow);
background: rgba(240, 192, 20, 0.12);
border: 1px solid rgba(240, 192, 20, 0.2);

/* Pink (accent) */
color: var(--pink);
background: rgba(232, 160, 176, 0.12);
border: 1px solid rgba(232, 160, 176, 0.2);
```

---

## Layout

- Max content width: 1200px (general), 1400px (data-heavy pages like economics)
- Container padding: 0 1.5rem
- Grid gaps: 1rem (tight), 1.5rem (standard), 3rem (major)
- Sub-page sidebar: 220px fixed, sticky top 100px
- Responsive breakpoints: 1024px (tablet), 768px (mobile), 480px (small mobile)

---

## Footer

- 4-column grid: brand (2fr) + 3 link columns (1fr each)
- Link headers: 0.8rem, uppercase, weight 600, letter-spacing 0.05em, gray-400
- Links: 0.9rem, gray-400, white on hover
- Bottom: 1px border top (gray-800), copyright in gray-600 at 0.8rem
- Collapses to 2-col at 1024px, 1-col centered at 768px

---

## Things to NEVER Do

- No gradients (flat colors only — the only exception is image overlays using transparent-to-black for text readability)
- No shadows (except subtle box-shadow on hover for photo cards)
- No emoji in professional/business outputs
- No rounded-full / pill shapes (use radius-sm or radius-md)
- No bright white backgrounds — darkest is #0a0a0a, lightest card bg is #1a1a1a
- No color other than the defined palette — no random blues, greens, oranges
- No Newsreader in non-italic form
- No heavy borders — always 1px
