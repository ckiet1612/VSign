import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FILM_CHAPTERS, chapterAt, chapterFill } from "./filmChapters";
import { LandingPage } from "./LandingPage";
import { chipScatter, deckOffset, parseStatement } from "./landingLayout";

describe("film chapters", () => {
  it("finds the chapter playing and how far through it the film is", () => {
    expect(chapterAt(0)).toBe(0);
    expect(chapterAt(16)).toBe(2);
    expect(chapterAt(59.9)).toBe(FILM_CHAPTERS.length - 1);
    expect(chapterFill(0, 4.8)).toBeCloseTo(0.5);
    expect(chapterFill(1, 4.8)).toBe(0);
    expect(chapterFill(0, 30)).toBe(1);
  });
});

describe("landing layout", () => {
  it("splits highlighted phrases into words that keep their tone", () => {
    expect(parseStatement("Ở quầy [cảm ơn|green] nhé.")).toEqual([
      { text: "Ở" }, { text: "quầy" }, { text: "cảm", tone: "green" }, { text: "ơn", tone: "green" }, { text: "nhé." },
    ]);
  });

  it("fans the deck out on both sides of the active card", () => {
    expect([0, 1, 2, 3, 4].map(index => deckOffset(index, 0, 5))).toEqual([0, 1, 2, -2, -1]);
    expect([0, 1, 2, 3, 4].map(index => deckOffset(index, 4, 5))).toEqual([1, 2, -2, -1, 0]);
  });

  it("scatters chips the same way on every render, within a small tilt", () => {
    expect(chipScatter(7)).toEqual(chipScatter(7));
    for (let index = 0; index < 30; index += 1) expect(Math.abs(chipScatter(index).rotate)).toBeLessThanOrEqual(6);
  });
});

describe("LandingPage", () => {
  it("renders the hero, the brand film and every section", () => {
    render(<LandingPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Đôi tay cũng biết nói." })).toBeInTheDocument();
    expect(screen.getByLabelText("Phim VSign 60 giây")).toHaveAttribute("src", expect.stringContaining("vsign-brand-film-60s.mp4"));
    expect(within(screen.getByRole("list", { name: "Chương của phim" })).getAllByRole("button")).toHaveLength(FILM_CHAPTERS.length);
    for (const name of ["Từ một cử chỉ đến một câu nói.", "30 ký hiệu cho quầy bán hàng.", "Một quầy. Hai màn hình.", "Điều bạn muốn biết."]) {
      expect(screen.getByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
    expect(document.title).toBe("VSign · Đôi tay cũng biết nói");
  });

  it("moves the step deck with its buttons and arrow keys", () => {
    render(<LandingPage />);
    const active = () => document.querySelector(".landing-step[data-active] h3")?.textContent;
    expect(active()).toBe("Nhìn");
    fireEvent.click(screen.getByRole("button", { name: "Bước sau" }));
    expect(active()).toBe("16 khung hình");
    fireEvent.keyDown(document.querySelector(".landing-deck")!, { key: "ArrowLeft" });
    fireEvent.keyDown(document.querySelector(".landing-deck")!, { key: "ArrowLeft" });
    expect(active()).toBe("Hai màn hình");
    expect(screen.getByRole("tab", { name: "Hai màn hình" })).toHaveAttribute("aria-selected", "true");
  });

  it("plays the reference clip of the sign the visitor picks", () => {
    render(<LandingPage />);
    expect(screen.getByLabelText("Cách ký “Mua”")).toHaveAttribute("src", expect.stringContaining("04-mua.mp4"));
    fireEvent.click(screen.getByRole("button", { name: "Cảm ơn" }));
    expect(screen.getByRole("button", { name: "Cảm ơn" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Cách ký “Cảm ơn”")).toHaveAttribute("src", expect.stringContaining("30-cam-on.mp4"));
  });
});
