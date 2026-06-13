---
name: Warm Editorial
colors:
  surface: '#faf9f5'
  surface-dim: '#dbdad6'
  surface-bright: '#faf9f5'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f4f4f0'
  surface-container: '#efeeea'
  surface-container-high: '#e9e8e4'
  surface-container-highest: '#e3e2df'
  on-surface: '#1b1c1a'
  on-surface-variant: '#54433e'
  inverse-surface: '#2f312e'
  inverse-on-surface: '#f2f1ed'
  outline: '#87736d'
  outline-variant: '#dac1ba'
  surface-tint: '#924a31'
  primary: '#8f482f'
  on-primary: '#ffffff'
  primary-container: '#ad5f45'
  on-primary-container: '#fffbff'
  inverse-primary: '#ffb59d'
  secondary: '#605e5b'
  on-secondary: '#ffffff'
  secondary-container: '#e6e2de'
  on-secondary-container: '#666461'
  tertiary: '#5f5c53'
  on-tertiary: '#ffffff'
  tertiary-container: '#78746b'
  on-tertiary-container: '#fffbff'
  error: '#c64545'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffdbd0'
  primary-fixed-dim: '#ffb59d'
  on-primary-fixed: '#390c00'
  on-primary-fixed-variant: '#75331c'
  secondary-fixed: '#e6e2de'
  secondary-fixed-dim: '#cac6c2'
  on-secondary-fixed: '#1c1b19'
  on-secondary-fixed-variant: '#484644'
  tertiary-fixed: '#e8e2d7'
  tertiary-fixed-dim: '#cbc6bb'
  on-tertiary-fixed: '#1d1b15'
  on-tertiary-fixed-variant: '#49473f'
  background: '#faf9f5'
  on-background: '#1b1c1a'
  surface-variant: '#e3e2df'
  ink: '#141413'
  primary-active: '#a9583e'
  hairline: '#e6dfd8'
  surface-dark-elevated: '#252320'
  accent-teal: '#5db8a6'
typography:
  display-xl:
    fontFamily: Source Serif 4
    fontSize: 64px
    fontWeight: '400'
    lineHeight: '1.05'
    letterSpacing: -1.5px
  display-lg:
    fontFamily: Source Serif 4
    fontSize: 48px
    fontWeight: '400'
    lineHeight: '1.1'
    letterSpacing: -1px
  display-md:
    fontFamily: Source Serif 4
    fontSize: 36px
    fontWeight: '400'
    lineHeight: '1.15'
    letterSpacing: -0.5px
  display-sm:
    fontFamily: Source Serif 4
    fontSize: 28px
    fontWeight: '400'
    lineHeight: '1.2'
    letterSpacing: -0.3px
  headline-lg-mobile:
    fontFamily: Source Serif 4
    fontSize: 32px
    fontWeight: '400'
    lineHeight: '1.2'
    letterSpacing: -0.5px
  title-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '500'
    lineHeight: '1.4'
    letterSpacing: '0'
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.55'
    letterSpacing: '0'
  caption-up:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: '1.4'
    letterSpacing: 1.5px
  code:
    fontFamily: jetbrainsMono
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: '0'
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  section: 96px
---

## Brand & Style

The design system for this internal real estate marketing portal is rooted in **Editorial Minimalism**. It rejects the sterile, cold aesthetics of traditional property management software in favor of a warm, humanist, and literary atmosphere. The goal is to position the tool as an sophisticated "editorial partner" that helps agents craft compelling narratives for their listings.

The visual language draws heavily from high-end magazine layouts, prioritizing intentional whitespace, masterful typography, and a "Warm Canvas" color philosophy. The emotional response should be one of calm focus, prestige, and intellectual clarity.

- **Minimalism:** Use generous white (cream) space and a disciplined grid to organize complex marketing data.
- **Planar Depth:** Instead of shadows, use distinct color bands and surface-on-surface layering to define hierarchy.
- **Sophisticated Contrast:** The tension between the organic cream tones and the sharp, technical navy surfaces creates a professional yet approachable environment.

## Colors

The palette is built on a "Warm Canvas" foundation. Avoid pure whites and blacks; use the tinted neutrals to maintain a literary, paper-like quality.

- **Primary (Coral):** Reserved strictly for primary calls to action, active states, and critical brand accents. It represents energy and human touch.
- **Secondary (Dark Navy):** Used for "Product Surfaces"—areas of high utility like code editors, property data tables, or footers. It provides a technical counterpoint to the warm canvas.
- **Tertiary (Light Cream):** The primary surface for content cards and containers, providing subtle separation from the base canvas.
- **Neutral (Warm Cream):** The global background color. It serves as the "paper" upon which all other elements are placed.

**Functional Colors:** Use `accent-teal` for success or "available" statuses and `error` red for validation. All borders should default to the `hairline` token to maintain a soft, low-contrast structure.

## Typography

The typography system relies on a high-contrast pairing of a sturdy Slab Serif (Source Serif 4) and a neutral, functional Sans-Serif (Inter).

**Key Rules:**
1. **Negative Tracking:** All `display` levels must utilize negative letter-spacing as defined. This is non-negotiable for achieving the "editorial" brand feel.
2. **Hierarchy:** Use the Slab Serif for narrative elements (listing headlines, section starts) and Inter for all utility and UI elements (form labels, buttons, data points).
3. **Upper Case:** Use the `caption-up` style for metadata, category tags, and "overlines" above main headlines to provide a structured, organized feel.

## Layout & Spacing

The system uses a **Fixed Grid** for desktop (1280px max-width) and a **Fluid Grid** for mobile devices. It is built on a 4px base unit.

- **Desktop:** 12-column grid with 24px gutters and 32px side margins.
- **Mobile:** 4-column fluid grid with 16px gutters and 16px side margins.
- **Rhythm:** Use `section` (96px) spacing to separate major content blocks (e.g., between the Hero and the Property Gallery). 
- **Card Padding:** Content cards must use `xl` (32px) padding to ensure an airy, premium feel. Never crowd the content.

## Elevation & Depth

This design system avoids traditional shadows in favor of **Tonal Layering** and **Planar Contrast**.

- **Surface Tiers:** 
  - Level 0: `canvas` (#faf9f5) - The base of the application.
  - Level 1: `surface-card` (#efe9de) - For primary interactive elements and content containers.
  - Level 2: `surface-dark` (#181715) - For high-utility "Product" areas like dashboards or code views.
- **Shadows:** Only a single, extremely subtle shadow is permitted for hover states on cards: `0 1px 3px rgba(20,20,19,0.08)`.
- **Outlines:** Use 1px `hairline` borders to define inputs and secondary buttons. The goal is to feel like ink on paper, not plastic elements floating in space.

## Shapes

The shape language is "Hierarchical Roundedness." As an element grows in size and importance, its corner radius increases to soften its impact.

- **Buttons & Inputs:** Use the standard 8px radius (`rounded-md`).
- **Cards & Data Containers:** Use 12px radius (`rounded-lg`) to create a distinct containerized feel.
- **Hero/Media Containers:** Use 16px radius (`rounded-xl`) for large imagery or video assets.
- **Badges/Labels:** Always use a `pill` shape for status indicators to contrast against the architectural structure of the rest of the UI.

## Components

### Buttons
- **Primary:** Coral background, white text. No shadow. 8px radius. Height: 40px or 48px for hero actions.
- **Secondary:** Transparent background, `hairline` border, `ink` text.
- **Tertiary:** Text-only, `ink` color, with a subtle underline on hover.

### Content Cards
- Always use `surface-card` (#efe9de) background.
- 12px corner radius.
- 32px internal padding.
- Use `hairline` for internal dividers within the card.

### Input Fields
- Background: Transparent or `canvas`.
- Border: 1px `hairline`. On focus, border changes to `primary` (Coral).
- Radius: 8px.
- Typography: `body-md`.

### Chips & Tags
- Style: Pill-shaped.
- Color: `surface-cream-strong` background with `muted` text.
- For active filters, use `primary` (Coral) background with white text.

### Lists
- Property lists should use `hairline-soft` dividers. 
- Ensure generous vertical padding (16px - 24px) between list items to maintain the editorial rhythm.