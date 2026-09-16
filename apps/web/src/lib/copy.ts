export type CopyMethod = "clipboard" | "fallback";

export async function copyText(
  text: string,
  clipboard: Pick<Clipboard, "writeText"> | undefined = navigator.clipboard,
): Promise<CopyMethod> {
  if (!text.trim()) throw new Error("Không có nội dung để sao chép.");
  if (clipboard) {
    try {
      await clipboard.writeText(text);
      return "clipboard";
    } catch {
      // Continue to the explicit, synchronous browser fallback.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.readOnly = true;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand?.("copy") ?? false;
  textarea.remove();
  if (!copied) throw new Error("Trình duyệt không cho phép sao chép tự động.");
  return "fallback";
}
