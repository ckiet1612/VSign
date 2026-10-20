function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return (
    target.isContentEditable ||
    tagName === "input" ||
    tagName === "textarea" ||
    tagName === "select" ||
    tagName === "button" ||
    tagName === "a" ||
    tagName === "summary"
  );
}

export function shouldStartSpaceCapture(
  event: Pick<KeyboardEvent, "code" | "repeat" | "target">,
): boolean {
  return (
    event.code === "Space" && !event.repeat && !isEditableTarget(event.target)
  );
}
