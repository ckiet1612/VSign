// Keys that move focus. Space and Enter only press what is already focused, so they never count as navigating.
const NAVIGATION_KEYS = new Set(["Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"]);

/**
 * Marks the root with how the user is moving around: `data-input="pointer"` after a click or tap,
 * `"keyboard"` once focus is moved with the keys, and `data-pointer-down` while a pointer is pressed.
 * The stylesheet draws focus rings for keyboard navigation and the press-in only under a real press,
 * so pressing Space after clicking a tab neither rings nor shrinks it.
 */
export function trackInputModality(root: HTMLElement = document.documentElement): () => void {
  const pointerDown = (event: PointerEvent) => {
    root.dataset.input = "pointer";
    if (event.isPrimary) root.dataset.pointerDown = "";
  };
  const pointerUp = () => { delete root.dataset.pointerDown; };
  const keyDown = (event: KeyboardEvent) => {
    if (NAVIGATION_KEYS.has(event.key) && !event.metaKey && !event.ctrlKey && !event.altKey) root.dataset.input = "keyboard";
  };
  document.addEventListener("pointerdown", pointerDown, true);
  document.addEventListener("pointerup", pointerUp, true);
  document.addEventListener("pointercancel", pointerUp, true);
  window.addEventListener("blur", pointerUp);
  document.addEventListener("keydown", keyDown, true);
  return () => {
    document.removeEventListener("pointerdown", pointerDown, true);
    document.removeEventListener("pointerup", pointerUp, true);
    document.removeEventListener("pointercancel", pointerUp, true);
    window.removeEventListener("blur", pointerUp);
    document.removeEventListener("keydown", keyDown, true);
    delete root.dataset.input;
    delete root.dataset.pointerDown;
  };
}
