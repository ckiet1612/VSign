import { fireEvent, render, screen, within } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { CameraPanel } from "./CameraPanel";

function readyCameraProps() {
  return {
    videoRef: createRef<HTMLVideoElement>(),
    camera: { status: "ready", message: "Camera sẵn sàng.", enable: vi.fn(), disable: vi.fn() },
    connection: "connected", captureStatus: "idle", canCapture: true,
    purpose: "recognize", framingMode: "fixed", captureInputMode: "manual",
    automaticPhase: "off", automaticAvailable: true,
    automaticCollectionPhase: "off", automaticCollectionCountdown: null,
    onCaptureInputModeChange: vi.fn(), onTrackingFrame: vi.fn(),
    onPointerDown: vi.fn(), onPointerUp: vi.fn(), onPointerCancel: vi.fn(),
  } satisfies Parameters<typeof CameraPanel>[0];
}

describe("CameraPanel framing guide", () => {
  it("giữ tiêu đề và trạng thái camera trước vùng hình ảnh trong bố cục chia khung", () => {
    const props = readyCameraProps();
    const view = render(<CameraPanel {...props} />);
    const heading = screen.getByRole("heading", { name: "Camera" });
    const stage = screen.getByLabelText("Hình ảnh camera trực tiếp").closest(".camera-stage")!;
    expect(heading).not.toHaveClass("sr-only");
    expect(stage.previousElementSibling).toContainElement(heading);
    view.rerender(<CameraPanel {...props} camera={{ ...props.camera, status: "off" }} />);
    expect(stage.previousElementSibling).toContainElement(screen.getByText("Chưa bật", { exact: true }));
    view.rerender(<CameraPanel {...props} camera={{ ...props.camera, status: "denied", message: "Quyền camera bị từ chối." }} />);
    expect(stage.previousElementSibling).toContainElement(screen.getByText("Chưa có quyền", { exact: true }));
    expect(screen.getByText("Quyền camera bị từ chối.")).toBeVisible();
  });

  it("hiển thị cách thu dạng segmented control luôn nhìn thấy", () => {
    const props = readyCameraProps();
    render(<CameraPanel {...props} />);
    const group = screen.getByRole("group", { name: "Chế độ thu ký hiệu" });
    expect(group.closest("details")).toBeNull();
    expect(screen.getByRole("button", { name: "Thủ công" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Tự động beta" }));
    expect(props.onCaptureInputModeChange).toHaveBeenCalledWith("automatic");
  });

  it("đưa focus về nút bật camera khi tắt camera bằng bàn phím", () => {
    const props = readyCameraProps();
    const view = render(<CameraPanel {...props} />);
    const stop = screen.getByRole("button", { name: "Tắt camera" });
    stop.focus();
    fireEvent.click(stop);
    expect(props.camera.disable).toHaveBeenCalledOnce();
    view.rerender(<CameraPanel {...props} camera={{ ...props.camera, status: "off" }} />);
    expect(screen.getByRole("button", { name: "Bật camera" })).toHaveFocus();
  });

  it("chỉ mời bật camera khi chưa bắt đầu, không bày nút thu vô hiệu hóa", () => {
    render(<CameraPanel
      videoRef={createRef<HTMLVideoElement>()}
      camera={{ status: "off", message: "Camera đang tắt.", enable: vi.fn(), disable: vi.fn() }}
      connection="connected" captureStatus="idle" canCapture={false}
      purpose="recognize" framingMode="fixed" captureInputMode="manual"
      automaticPhase="off" automaticAvailable={false}
      automaticCollectionPhase="off" automaticCollectionCountdown={null}
      onCaptureInputModeChange={vi.fn()} onTrackingFrame={vi.fn()}
      onPointerDown={vi.fn()} onPointerUp={vi.fn()} onPointerCancel={vi.fn()}
    />);
    expect(screen.getByRole("button", { name: "Bật camera" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Giữ để ký, cũng có thể giữ phím Space" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Camera" })).not.toHaveClass("sr-only");
    expect(screen.getByText("Chưa bật", { exact: true })).toBeVisible();
  });

  it("phân biệt camera sẵn sàng với trạng thái xin quyền và bị từ chối", () => {
    const props = readyCameraProps();
    const view = render(<CameraPanel {...props} />);
    expect(screen.queryByText("Đang bật", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("Trực tiếp", { exact: true })).toBeVisible();
    view.rerender(<CameraPanel {...props} camera={{ ...props.camera, status: "requesting", message: "Đang xin quyền dùng camera…" }} />);
    expect(screen.getByText("Đang bật", { exact: true })).toBeVisible();
    expect(screen.getByRole("button", { name: "Đang bật…" })).toBeDisabled();
    view.rerender(<CameraPanel {...props} camera={{ ...props.camera, status: "denied", message: "Quyền camera bị từ chối." }} />);
    expect(screen.getByText("Chưa có quyền", { exact: true })).toBeVisible();
    expect(screen.getByRole("button", { name: "Bật camera" })).toBeEnabled();
    expect(screen.getByText("Quyền camera bị từ chối.")).toBeVisible();
  });

  it("hiển thị khung RGB cố định khi webcam phải khớp pipeline train", () => {
    render(
      <CameraPanel
        videoRef={createRef<HTMLVideoElement>()}
        camera={{
          status: "off",
          message: "Camera đang tắt.",
          enable: vi.fn(),
          disable: vi.fn(),
        }}
        connection="connected"
        captureStatus="idle"
        canCapture={false}
        purpose="recognize"
        framingMode="fixed"
        captureInputMode="manual"
        automaticPhase="off"
        automaticAvailable={false}
        automaticCollectionPhase="off"
        automaticCollectionCountdown={null}
        onCaptureInputModeChange={vi.fn()}
        onTrackingFrame={vi.fn()}
        onPointerDown={vi.fn()}
        onPointerUp={vi.fn()}
        onPointerCancel={vi.fn()}
      />,
    );

    expect(screen.getByText("Khung RGB cố định · Giữ hai tay bên trong")).toBeInTheDocument();
    const controls = screen.getByRole("group", { name: "Điều khiển camera" });
    expect(screen.getByRole("button", { name: "Bật camera" })).toBeEnabled();
    expect(within(controls).getByRole("button", { name: "Thủ công" })).toHaveAttribute("aria-pressed", "true");
    expect(within(controls).queryByRole("button", { name: "Giữ để ký, cũng có thể giữ phím Space" })).not.toBeInTheDocument();
  });

  it("khớp khung center-square thật khi camera ở chiều dọc", () => {
    const { container } = render(
      <CameraPanel
        videoRef={createRef<HTMLVideoElement>()}
        camera={{
          status: "ready",
          message: "Camera sẵn sàng.",
          enable: vi.fn(),
          disable: vi.fn(),
        }}
        connection="connected"
        captureStatus="idle"
        canCapture
        purpose="recognize"
        framingMode="fixed"
        captureInputMode="manual"
        automaticPhase="off"
        automaticAvailable={false}
        automaticCollectionPhase="off"
        automaticCollectionCountdown={null}
        onCaptureInputModeChange={vi.fn()}
        onTrackingFrame={vi.fn()}
        onPointerDown={vi.fn()}
        onPointerUp={vi.fn()}
        onPointerCancel={vi.fn()}
      />,
    );
    const video = screen.getByLabelText("Hình ảnh camera trực tiếp");
    Object.defineProperties(video, {
      videoWidth: { configurable: true, value: 720 },
      videoHeight: { configurable: true, value: 1280 },
    });

    fireEvent.loadedMetadata(video);

    const guide = container.querySelector(".guide-rgb-crop");
    expect(guide).toHaveAttribute("x", "328.125");
    expect(guide).toHaveAttribute("y", "118.125");
    expect(guide).toHaveAttribute("width", "303.75");
    expect(guide).toHaveAttribute("height", "303.75");
  });

  it("hiển thị đầy hàng đợi và đặt timing riêng trong mục mở rộng", () => {
    render(<CameraPanel
      videoRef={createRef<HTMLVideoElement>()}
      camera={{ status: "ready", message: "Camera sẵn sàng.", enable: vi.fn(), disable: vi.fn() }}
      connection="connected" captureStatus="idle" canCapture={false}
      purpose="recognize" framingMode="fixed" captureInputMode="automatic"
      automaticPhase="cooldown" automaticAvailable
      automaticCollectionPhase="off" automaticCollectionCountdown={null}
      automaticQueue={{
        waitingCount: 2, busy: true, full: true, notice: "",
        lastTiming: { sequence: 4, captureMs: 2100, encodeMs: 15, queueWaitMs: 250, responseMs: 800 },
      }}
      onCaptureInputModeChange={vi.fn()} onTrackingFrame={vi.fn()}
      onPointerDown={vi.fn()} onPointerUp={vi.fn()} onPointerCancel={vi.fn()}
    />);
    expect(screen.getByText("Hàng đợi đầy · chờ AI xử lý")).toBeInTheDocument();
    expect(screen.getByText("Chờ: 2/2")).toBeInTheDocument();
    expect(screen.getByText("Đoạn thu")).toBeInTheDocument();
    expect(screen.getByText("2100 ms")).toBeInTheDocument();
    expect(screen.getByText("Encode ảnh")).toBeInTheDocument();
    expect(screen.getByText("15 ms")).toBeInTheDocument();
    expect(screen.getByText("Chờ gửi")).toBeInTheDocument();
    expect(screen.getByText("250 ms")).toBeInTheDocument();
    expect(screen.getByText("Phản hồi AI")).toBeInTheDocument();
    expect(screen.getByText("800 ms")).toBeInTheDocument();
    expect(screen.getByText("800 ms").closest("details")).not.toHaveAttribute("open");
  });

  it.each([
    ["rearming", "Chờ tay nghỉ · chưa nhận lượt mới"],
    ["cooldown", "Chờ tay nghỉ · chưa nhận lượt mới"],
    ["waiting", "Sẵn sàng · hãy ký một từ"],
    ["encoding", "Đang xử lý ảnh ký hiệu…"],
  ] as const)("báo đúng trạng thái %s thay vì báo sẵn sàng quá sớm", (phase, message) => {
    render(<CameraPanel
      videoRef={createRef<HTMLVideoElement>()}
      camera={{ status: "ready", message: "Camera sẵn sàng.", enable: vi.fn(), disable: vi.fn() }}
      connection="connected" captureStatus="idle" canCapture={false}
      purpose="recognize" framingMode="fixed" captureInputMode="automatic"
      automaticPhase={phase} automaticAvailable
      automaticCollectionPhase="off" automaticCollectionCountdown={null}
      onCaptureInputModeChange={vi.fn()} onTrackingFrame={vi.fn()}
      onPointerDown={vi.fn()} onPointerUp={vi.fn()} onPointerCancel={vi.fn()}
    />);
    expect(screen.getByText(message)).toBeInTheDocument();
    if (phase !== "waiting") {
      expect(screen.queryByText("Sẵn sàng · hãy ký một từ")).not.toBeInTheDocument();
    }
  });

  it("đặt lại nền chọn của công tắc khi quay từ thu dữ liệu về nhận dạng ở cùng chế độ tự động", () => {
    const props = { ...readyCameraProps(), captureInputMode: "automatic" as const };
    const view = render(<CameraPanel {...props} purpose="collect" />);
    view.rerender(<CameraPanel {...props} purpose="recognize" />);
    const modeSwitch = screen.getByRole("group", { name: "Chế độ thu ký hiệu" });
    expect(modeSwitch.style.getPropertyValue("--thumb-w")).not.toBe("");
  });
});
