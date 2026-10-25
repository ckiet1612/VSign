import { useEffect, useRef } from "react";

/** Closes a `<details>` popover on a click outside it or on Escape, as a menu would. */
export function useDismissibleDetails<T extends HTMLDetailsElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const close = (focus: boolean) => {
      const details = ref.current;
      if (!details?.open) return;
      details.open = false;
      if (focus) details.querySelector("summary")?.focus();
    };
    const onPointer = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) close(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && ref.current?.contains(document.activeElement)) close(true);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  return ref;
}
