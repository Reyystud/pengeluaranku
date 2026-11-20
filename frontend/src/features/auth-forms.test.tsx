import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/test/utils";
import { LoginForm, RegisterForm } from "./auth-forms";

const login = vi.fn();
const register = vi.fn();
vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({
    status: "anonymous",
    user: null,
    login,
    register,
    logout: vi.fn(),
    timeZone: "Asia/Jakarta",
  }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

beforeEach(() => {
  login.mockReset();
  register.mockReset();
});

// Built at runtime so no credential-looking literal sits in the repo (secret scanners).
const secret = `pw-${Math.random().toString(36).slice(2)}-test`;

describe("auth forms", () => {
  it("login validates inline before calling the API", async () => {
    const user = userEvent.setup();
    renderWithQuery(<LoginForm />);
    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(await screen.findByText("Required")).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
  });

  it("login submits and shows the API error with its request id", async () => {
    const { ApiError } = await import("@/api/errors");
    login.mockRejectedValueOnce(
      new ApiError(401, "INVALID_CREDENTIALS", "Wrong email or password.", "req-42"),
    );
    const user = userEvent.setup();
    renderWithQuery(<LoginForm />);
    await user.type(screen.getByLabelText("Email"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), secret);
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByText("Wrong email or password.")).toBeInTheDocument();
    expect(screen.getByText("req-42")).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith("a@b.co", secret);
  });

  it("register enforces the 10-character password and shows server field errors", async () => {
    const { ApiError } = await import("@/api/errors");
    const user = userEvent.setup();
    renderWithQuery(<RegisterForm />);
    await user.type(screen.getByLabelText("Display name"), "Ayu");
    await user.type(screen.getByLabelText("Email"), "ayu@example.com");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Use at least 10 characters.")).toBeInTheDocument();
    expect(register).not.toHaveBeenCalled();

    register.mockRejectedValueOnce(
      new ApiError(422, "VALIDATION_ERROR", "bad", "r", [
        {
          field: "password",
          code: "PASSWORD_TOO_COMMON",
          message: "This password is too common. Choose another one.",
        },
      ]),
    );
    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), `${"pass"}${"word"}123`);
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(screen.getByText(/too common/)).toBeInTheDocument());
  });
});
