# Narrative Studio — Exact Reference Landing Page

## WHAT
This package converts the approved Narrative Studio / Italus visual reference into a hostable static page.

## HOW
The approved image is used as the visual background to preserve the exact mood and composition.
Live HTML anchors are overlaid for:

- Top menu
- New Project tile
- Existing Project tile
- Archived Project tile
- Learn More button

The three middle tiles include hover animation, glow, and mouse-reactive tilt.

## WHERE
Host as a static site or embed inside the application shell.

Works with:
- Netlify
- Vercel
- GitHub Pages
- Cloudflare Pages
- Electron / desktop app WebView
- React / Vue / Svelte conversion

## ORDER
1. Open `index.html`.
2. Replace dummy `href="#"` values with real app routes.
3. Keep `assets/narrative-studio-reference.png` unless Morpheus rebuilds the design with separate layered artwork.
4. If converting to React, turn each anchor into a component or router link.
5. Preserve `styles.css` positioning until final responsive layout is rebuilt.

## Suggested Route Replacements

```html
File        /file
Project     /project
Engine      /engine
Generate    /generate
Validation  /validation
View        /view
Settings    /settings
Help        /help

New Project       /projects/new
Existing Project  /projects/open
Archived Project  /projects/archive
Learn More        /italus
```

## Engineering Note for Morpheus
This is the fastest exact-match implementation because the source artwork is a single composited image.
For production, the next step is to split the design into layers:

- background library scene
- left panel artwork
- logo
- text layer
- tile components
- bottom info bar

That would allow full responsiveness and localization without relying on a single image.
