import { describe, expect, it } from "vitest";
import { localDate, toApiDate, zoneOffset } from "./format";

describe("time zone helpers (user's zone, default Asia/Jakarta)", () => {
  it("date-only stays a plain date so the API sets has_time=false", () => {
    expect(toApiDate("2026-11-18", "")).toBe("2026-11-18");
  });

  it("a local time becomes an instant with the zone offset", () => {
    expect(zoneOffset("2026-11-18", "Asia/Jakarta")).toBe("+07:00");
    expect(toApiDate("2026-11-18", "12:30", "Asia/Jakarta")).toBe("2026-11-18T12:30:00+07:00");
    expect(toApiDate("2026-11-18", "08:00", "UTC")).toBe("2026-11-18T08:00:00+00:00");
  });

  it("the local calendar date can differ from the UTC date", () => {
    expect(localDate("2026-11-17T20:00:00Z", "Asia/Jakarta")).toBe("2026-11-18");
  });
});
