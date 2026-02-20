# Design System

Reference site: [theprincipaluncertainty.com](https://theprincipaluncertainty.com). All
properties should feel like cousins — same visual vocabulary, not identical layouts.

---

## Color Palette (CSS custom properties)

| Variable | Hex | Use |
|---|---|---|
| `--navy` | `#1e2b3c` | Buttons, links, dark sections, footer background |
| `--navy-light` | `#253348` | Hover state for navy |
| `--cream-lighter` | `#f3f1ed` | Page background, pricing section |
| `--cream-light` | `#eae8e2` | Hero section background |
| `--cream` | `#dbd8cf` | Borders, dividers |
| `--dark` | `#3e4948` | Body text |
| `--dark-light` | `#5a6b6a` | Secondary / muted text |
| `--teal` | `#485957` | Retained for potential future use |
| `--white` | `#ffffff` | — |

No warm accent color (no terracotta, no orange). Navy is the sole action color.

---

## Typography

| Role | Font | Style | Weight |
|---|---|---|---|
| h1, h2 | Lora | Italic | 400 |
| h3, h4 | Lora | Normal | 400 |
| Body | Pontano Sans | Normal | 400 / 700 |

Google Fonts import:
```
Lora:ital,wght@0,400;0,500;0,600;1,400&family=Pontano+Sans:wght@400;700
```

---

## Buttons

- **Shape:** 4px border radius (`border-radius: 4px`)
- **Primary:** `background: var(--navy); color: var(--white); hover: var(--navy-light)`
- **Outline:** `background: var(--white); color: var(--navy); border: 1px solid var(--navy)`

---

## Section Rhythm

| Section type | Background |
|---|---|
| Hero | `var(--cream-light)` (`#eae8e2`) |
| Features / free signup | `var(--cream-light)` |
| Pricing | `var(--cream-lighter)` (`#f3f1ed`) |
| Dark (API code, footer) | `var(--navy)` (`#1e2b3c`) |

Dark sections use `var(--white)` for headings and `var(--cream)` for secondary text.

---

## Properties

### verify.georgelaufenberg.com
- Stack: Single HTML file with inline CSS custom properties
- File: `app/static/index.html`
- Deploy: `railway up -s nonprofit-verify-api`

### data.georgelaufenberg.com
- Stack: React + Tailwind CSS
- Repo: `nonprofit-salary-benchmark`
- Tailwind tokens mirror the CSS variables above

### theprincipaluncertainty.com
- Squarespace — do not edit
- This is the visual reference, not a managed property
