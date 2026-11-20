import { describe, expect, it } from "vitest";
import { formatIdr, parseMoney } from "./money";

describe("parseMoney (PRD 8.2: accepts 25000 or 25.000)", () => {
  it.each([
    ["25000", "25000.00"],
    ["25.000", "25000.00"],
    ["1.250.000", "1250000.00"],
    ["25000.5", "25000.50"],
    ["25.000,75", "25000.75"],
    ["Rp 25.000", "25000.00"],
    ["0075", "75.00"],
  ])("%s -> %s", (input, expected) => {
    expect(parseMoney(input)).toBe(expected);
  });

  it.each(["", "abc", "0", "0.00", "-5", "12.3456", "1,2,3", "25.00.0"])("rejects %j", (input) => {
    expect(parseMoney(input)).toBeNull();
  });
});

describe("formatIdr", () => {
  it("groups thousands without floats and trims empty decimals", () => {
    expect(formatIdr("25000.00")).toBe("Rp25.000");
    expect(formatIdr("1250000.00")).toBe("Rp1.250.000");
    expect(formatIdr("999.50")).toBe("Rp999,5");
    expect(formatIdr("12345678901234.00")).toBe("Rp12.345.678.901.234");
  });
});
