# PaperForge Design System

Adapted from the local awesome-design-md `wired` reference for an academic conversion workbench. Use these tokens for every UI component.

## Direction

Editorial instrument: the page should feel like a scholarly production desk assembled from paper, proof marks, and typeset pages. The signature is a quiet ivory canvas, ink-black structural type, hairline rules, and one measured cobalt action color.

## Tokens

```css
:root {
  --paper: #f7f6f2;
  --paper-deep: #eceae4;
  --ink: #161616;
  --ink-soft: #5f605d;
  --rule: #d7d5ce;
  --rule-strong: #a9aaa4;
  --cobalt: #2057d4;
  --cobalt-soft: #e8eefc;
  --green: #1d7a51;
  --amber: #a76719;
  --red: #b53b35;
  --display: Georgia, 'Times New Roman', serif;
  --sans: 'Segoe UI', Arial, sans-serif;
  --mono: Consolas, 'SFMono-Regular', monospace;
  --text-xs: 12px;
  --text-sm: 14px;
  --text-md: 16px;
  --text-lg: 19px;
  --text-xl: 28px;
  --text-hero: clamp(38px, 5vw, 64px);
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --space-7: 48px;
  --radius: 4px;
}
```

## Composition

- Operate mode. Put the current job and next safe action first.
- Use a wide two-column workbench: persistent navigation, then a main document surface with a narrow status rail on desktop.
- Use rules and whitespace for hierarchy. Reserve bordered panels for tools, reports, and previews.
- Use serif type for manuscript-like headings and sans-serif for controls, metadata, and navigation.
- Use cobalt only for primary actions, active navigation, and focus. Use semantic colors with text labels.

## Components

- Buttons: square-ish 4px radius, 44px minimum height, sentence-case action labels, icon plus text only when the icon adds clarity.
- Inputs: paper background, 1px rule, visible cobalt focus ring.
- Status: compact labeled markers with text, never color alone.
- Panels: 1px rule, no floating card stacks, 24px internal padding.
- Tables and ledgers: hairline row rules, tabular numerals, aligned columns.

## Responsive

- At 900px, collapse the status rail below the main content.
- At 680px, turn the left navigation into a compact top bar and keep workbench actions full-width.
- Preserve readable line lengths and never allow controls to overflow their containers.

## Motion

One restrained load reveal and purposeful progress transitions. Respect `prefers-reduced-motion`.
