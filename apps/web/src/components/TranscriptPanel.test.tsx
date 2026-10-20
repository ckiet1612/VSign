import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TranscriptPanel } from "./TranscriptPanel";

describe("TranscriptPanel", () => {
  it("không hiển thị bộ đếm rỗng, hiển thị lại số từ khi đã xác nhận", () => {
    const props = { words: [] as string[], notice: "", composedSentence: "",
      composing: false, composeAvailable: true, composeWithAi: false,
      onCompose: vi.fn(), onUndo: vi.fn(), onClear: vi.fn(), onCopy: vi.fn() };
    const view = render(<TranscriptPanel {...props} />);
    expect(screen.queryByText("0 từ")).not.toBeInTheDocument();
    expect(screen.getByText("Chưa có từ")).toBeVisible();
    view.rerender(<TranscriptPanel {...props} words={["Tôi"]} />);
    expect(screen.getByText("1 từ")).toBeVisible();
  });

  it("ẩn thanh công cụ khi câu trống nhưng giữ trạng thái disabled", () => {
    render(<TranscriptPanel words={[]} notice="" composedSentence=""
      composing={false} composeAvailable composeWithAi={false}
      onCompose={vi.fn()} onUndo={vi.fn()} onClear={vi.fn()} onCopy={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Hoàn tác từ cuối", hidden: true })).not.toBeVisible();
  });

  it("giữ tên truy cập và tooltip cho các nút công cụ", async () => {
    const onUndo = vi.fn();
    const onClear = vi.fn();
    const onCopy = vi.fn();
    render(<TranscriptPanel words={["Tôi", "Muốn"]} notice="" composedSentence=""
      composing={false} composeAvailable composeWithAi={false}
      onCompose={vi.fn()} onUndo={onUndo} onClear={onClear} onCopy={onCopy} />);
    const undo = screen.getByRole("button", { name: "Hoàn tác từ cuối" });
    const clear = screen.getByRole("button", { name: "Xóa toàn bộ câu" });
    const copy = screen.getByRole("button", { name: "Sao chép câu" });
    expect(undo).toHaveAttribute("title", "Hoàn tác từ cuối");
    expect(clear).toHaveAttribute("title", "Xóa toàn bộ câu");
    expect(copy).toHaveAttribute("title", "Sao chép câu");
    await userEvent.click(undo);
    await userEvent.click(clear);
    await userEvent.click(copy);
    expect(onUndo).toHaveBeenCalledOnce();
    expect(onClear).toHaveBeenCalledOnce();
    expect(onCopy).toHaveBeenCalledOnce();
  });

  it("shows both capture and grammar warnings beside the automatic draft", () => {
    render(<TranscriptPanel words={["Laptop", "Mới", "Cũ"]} notice="" composedSentence=""
      composing={false} composeAvailable composeWithAi={false} automatic
      sentenceDrafts={[{ id: 0, words: ["Laptop", "Mới", "Cũ"], sentence: "Laptop mới cũ.",
        status: "review", warning: "Có đoạn chưa nhận dạng", compositionWarning: "Thuộc tính chưa rõ" }]}
      onCompose={vi.fn()} onUndo={vi.fn()} onClear={vi.fn()} onCopy={vi.fn()} />);
    expect(screen.getByText(/Có đoạn chưa nhận dạng.*Thuộc tính chưa rõ/)).toBeInTheDocument();
    expect(screen.getByText("Laptop mới cũ.")).toBeInTheDocument();
  });

  it("shows grammar warnings in manual mode too", () => {
    render(<TranscriptPanel words={["Laptop", "Mới", "Cũ"]} notice="" composedSentence="Laptop mới cũ."
      composedWarning="Thuộc tính chưa rõ" composing={false} composeAvailable composeWithAi={false}
      onCompose={vi.fn()} onUndo={vi.fn()} onClear={vi.fn()} onCopy={vi.fn()} />);
    expect(screen.getByText("Thuộc tính chưa rõ")).toBeInTheDocument();
  });
  it("yêu cầu máy chủ hoàn thiện câu từ các từ đã xác nhận", async () => {
    const onCompose = vi.fn();
    const user = userEvent.setup();

    render(
      <TranscriptPanel
        words={["Tôi", "Muốn", "Mua", "Điện thoại"]}
        notice=""
        composedSentence=""
        composing={false}
        composeAvailable
        composeWithAi
        onCompose={onCompose}
        onUndo={vi.fn()}
        onClear={vi.fn()}
        onCopy={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Hoàn thiện câu bằng AI" }));
    expect(onCompose).toHaveBeenCalledOnce();
  });

  it("hiển thị câu hoàn thiện và khóa thao tác khi đang xử lý", () => {
    render(
      <TranscriptPanel
        words={["Tôi", "Muốn", "Mua", "Điện thoại"]}
        notice=""
        composedSentence="Tôi muốn mua điện thoại."
        composing
        composeAvailable
        composeWithAi
        onCompose={vi.fn()}
        onUndo={vi.fn()}
        onClear={vi.fn()}
        onCopy={vi.fn()}
      />,
    );

    expect(screen.getByText("Tôi muốn mua điện thoại.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đang hoàn thiện câu" })).toBeDisabled();
  });
});
