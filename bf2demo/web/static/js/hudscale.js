// The game draws its HUD in an 800 x 600 layout and stretches that layout over the screen, so the HUD keeps the same share of the view at every
// resolution (the user's game screenshot is 1 : 1 at 800 x 600). The page does the same: device pixels per layout pixel = the largest factor at
// which the whole 800 x 600 layout fits the map area, in steps of 1/8 (rounded down, so the layout never overflows) so a window resize does not rebuild every glyph. Fractional factors are fine:
// the game draws its font quads bilinear-filtered as well (never blocky); the HUD size option still offers whole factors.
import { S } from "./state.js";

export const dpr = () => window.devicePixelRatio || 1;

/** Device pixels per layout pixel for a map area of `cssW` x `cssH` CSS pixels: the user's choice, or the game's own fit. */
export function hudK(cssW, cssH) {
  if (S.hudScale > 0) return S.hudScale;
  return Math.max(0.75, Math.floor(Math.min(cssW / 800, cssH / 600) * dpr() * 8) / 8);
}
/** The small HUD pieces (top bar, kill feed) scale like the whole layout. */
export const hudKSmall = (cssW, cssH) => hudK(cssW, cssH) * (S.hudScale > 0 || cssW >= 600 ? 1 : 1.8);   // on a phone the 800 x 600 fit makes the bar 100 px wide: read it at 1.8 x
