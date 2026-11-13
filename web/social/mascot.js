// The prototype's cat drawings (Mascot.dc.html and the default avatar in
// Feed.dc.html), as markup only. Their colours are the illustration's own,
// the same in every theme: web/tokens.css, ".mascot" and ".cat-face".

import { html } from "../vendor/preact-htm.js";

// The sitting cat that keeps the Home tab company. `coat`: gray, ginger or
// black. Decoration: hidden from a screen reader.
export function Mascot({ coat = "gray", size = 64 }) {
  return html`<svg class="mascot" data-coat=${coat} width=${size} height=${size} viewBox="0 0 100 100" aria-hidden="true">
    <ellipse class="m-shadow" cx="50" cy="95.5" rx="22" ry="3" />
    <path class="m-line" d="M64 91 C84 93 92 78 85 66 C81 59 85 53 90 54" stroke-width="7" />
    <path class="m-coat" d="M29 94 C24 73 33 55 50 55 C67 55 76 73 71 94 Z" />
    <path class="m-line m-stripes" d="M32 74 Q36 71 39 74 M31 82 Q35 79 38 82 M68 74 Q64 71 61 74 M69 82 Q65 79 62 82" stroke-width="2.2" />
    <ellipse class="m-light" cx="50" cy="80" rx="11" ry="13.5" />
    <ellipse class="m-light" cx="41.5" cy="93" rx="6.5" ry="4" />
    <ellipse class="m-light" cx="58.5" cy="93" rx="6.5" ry="4" />
    <path class="m-coat m-ear" d="M31.5 34 L29.5 12.5 L46 23.5 Z" />
    <path class="m-pink" d="M33.5 30 L32.5 17.5 L42 24 Z" opacity="0.75" />
    <path class="m-coat m-ear" d="M68.5 34 L70.5 12.5 L54 23.5 Z" />
    <path class="m-pink" d="M66.5 30 L67.5 17.5 L58 24 Z" opacity="0.75" />
    <ellipse class="m-coat" cx="50" cy="40" rx="21.5" ry="18" />
    <path class="m-line m-stripes" d="M45.5 24.5 L46.5 30 M50 23.5 L50 30 M54.5 24.5 L53.5 30" stroke-width="2.2" />
    <ellipse class="m-light" cx="50" cy="47.5" rx="8.5" ry="5.8" />
    <ellipse class="m-pink" cx="38.5" cy="46.5" rx="3.2" ry="1.9" opacity="0.45" />
    <ellipse class="m-pink" cx="61.5" cy="46.5" rx="3.2" ry="1.9" opacity="0.45" />
    <ellipse class="m-ink" cx="42.5" cy="39.5" rx="2.9" ry="3.7" />
    <ellipse class="m-ink" cx="57.5" cy="39.5" rx="2.9" ry="3.7" />
    <circle class="m-glint" cx="43.4" cy="38.2" r="0.95" />
    <circle class="m-glint" cx="58.4" cy="38.2" r="0.95" />
    <path class="m-pink" d="M48.2 44.8 L51.8 44.8 L50 47 Z" />
    <path class="m-whisker" d="M50 47 Q48.6 49.3 46.7 48.5 M50 47 Q51.4 49.3 53.3 48.5" stroke-width="1.1" />
    <path class="m-whisker" d="M37 45.5 L26.5 43.5 M37 48 L26.5 49 M63 45.5 L73.5 43.5 M63 48 L73.5 49" stroke-width="0.8" opacity="0.4" />
  </svg>`;
}

// The cat's face a person has until they choose a photo (B1).
export function CatFace({ size = 34 }) {
  return html`<svg class="cat-face" width=${size} height=${size} viewBox="0 0 24 24" aria-hidden="true">
    <path class="f-head" d="M6.2 9.2L5.4 4l4.5 2.6a8.6 8.6 0 0 1 4.2 0L18.6 4l-.8 5.2c1.2 1.2 1.8 2.6 1.8 4.1 0 3.6-3.4 6.2-7.6 6.2s-7.6-2.6-7.6-6.2c0-1.5.6-2.9 1.8-4.1z" />
    <circle class="f-eye" cx="9.3" cy="12.8" r="1.9" />
    <circle class="f-eye" cx="14.7" cy="12.8" r="1.9" />
    <circle class="f-head" cx="9.5" cy="13" r="0.9" />
    <circle class="f-head" cx="14.9" cy="13" r="0.9" />
    <path class="f-nose" d="M11.4 15.4h1.2l-.6.7z" />
  </svg>`;
}
