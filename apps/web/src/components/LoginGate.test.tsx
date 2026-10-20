import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoginGate } from "./LoginGate";

describe("LoginGate", () => {
  it("embeds in an existing page and recovers after a StrictMode login failure", async () => {
    render(<StrictMode><LoginGate embedded workspaceName="VSign" onLogin={async () => { throw new Error("Sai mật khẩu"); }} /></StrictMode>);
    expect(screen.queryByRole("main")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2 })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Email"), "test@example.com");
    await userEvent.type(screen.getByLabelText("Mật khẩu"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
    await screen.findByText("Sai mật khẩu");
    await waitFor(() => expect(screen.getByRole("button", { name: "Đăng nhập" })).toBeEnabled());
  });
  it("shows an inline error and prevents duplicate submits", async () => {
    const user = userEvent.setup();
    let resolve!: () => void;
    const onLogin = vi.fn(() => new Promise<void>(complete => { resolve = complete; }));
    render(<LoginGate workspaceName="VSign workspace" onLogin={onLogin} />);

    await user.type(screen.getByLabelText("Email"), "admin@example.com");
    await user.type(screen.getByLabelText("Mật khẩu"), "password");
    const submit = screen.getByRole("button", { name: "Đăng nhập" });
    await user.click(submit);
    expect(onLogin).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Đang đăng nhập…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Đang đăng nhập…" }));
    expect(onLogin).toHaveBeenCalledTimes(1);
    resolve();
  });
});
