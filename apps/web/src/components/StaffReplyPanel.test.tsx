import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { StaffReplyPanel } from "./StaffReplyPanel";

class Recognition {
  static last: Recognition | null = null;
  lang = ""; interimResults = false; continuous = true; maxAlternatives = 0;
  onresult: ((event: unknown) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn(() => { Recognition.last = this; });
  stop = vi.fn(() => this.onend?.());
  abort = vi.fn();
}

afterEach(() => { vi.unstubAllGlobals(); Recognition.last = null; });

it("sends typed and quick replies and shows what the customer sees", () => {
  const onSend = vi.fn();
  const onClear = vi.fn();
  const { rerender } = render(<StaffReplyPanel reply="" counter onSend={onSend} onClear={onClear} />);
  // Without the Web Speech API there is no microphone button at all.
  expect(screen.queryByRole("button", { name: "Nói để nhập câu trả lời" })).not.toBeInTheDocument();
  // Templates live in a menu; picking one sends it and closes the menu.
  const templates = screen.getByText("Câu mẫu").closest("details")!;
  fireEvent.click(screen.getByText("Câu mẫu"));
  expect(templates.open).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Vui lòng chờ một chút." }));
  expect(onSend).toHaveBeenLastCalledWith("Vui lòng chờ một chút.", "quick");
  expect(templates.open).toBe(false);
  fireEvent.change(screen.getByLabelText("Câu trả lời"), { target: { value: "  Quầy 2 bên trái  " } });
  fireEvent.click(screen.getByRole("button", { name: "Gửi câu trả lời" }));
  expect(onSend).toHaveBeenLastCalledWith("Quầy 2 bên trái", "typed");
  expect(screen.getByLabelText("Câu trả lời")).toHaveValue("");

  rerender(<StaffReplyPanel reply="Quầy 2 bên trái" counter={false} onSend={onSend} onClear={onClear} />);
  expect(screen.getByText("Khách đang thấy")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Ẩn câu trả lời" }));
  expect(onClear).toHaveBeenCalled();
});

it("fills the box from Vietnamese dictation and waits for the staff member to send it", () => {
  vi.stubGlobal("webkitSpeechRecognition", Recognition);
  const onSend = vi.fn();
  render(<StaffReplyPanel reply="" counter={false} onSend={onSend} onClear={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Nói để nhập câu trả lời" }));
  const recognition = Recognition.last!;
  expect(recognition.lang).toBe("vi-VN");
  act(() => recognition.onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: "còn hàng ở kệ số ba" } }] }));
  expect(screen.getByLabelText("Câu trả lời")).toHaveValue("còn hàng ở kệ số ba");
  expect(onSend).not.toHaveBeenCalled();
  act(() => recognition.onend?.());
  fireEvent.click(screen.getByRole("button", { name: "Gửi câu trả lời" }));
  expect(onSend).toHaveBeenCalledWith("còn hàng ở kệ số ba", "voice");
  fireEvent.click(screen.getByRole("button", { name: "Nói để nhập câu trả lời" }));
  act(() => Recognition.last!.onerror?.({ error: "not-allowed" }));
  expect(screen.getByRole("alert")).toHaveTextContent("cấp quyền micro");
});
