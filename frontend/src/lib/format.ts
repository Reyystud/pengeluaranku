export const DEFAULT_TZ = "Asia/Jakarta";

export function formatDate(iso: string, timeZone: string = DEFAULT_TZ, withTime = false): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
  }).format(new Date(iso));
}

/** Local calendar date (YYYY-MM-DD) of an instant in a time zone. */
export function localDate(iso: string, timeZone: string = DEFAULT_TZ): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(iso));
}

export function nowLocalParts(timeZone: string = DEFAULT_TZ): { date: string; time: string } {
  const now = new Date();
  const date = new Intl.DateTimeFormat("en-CA", { timeZone }).format(now);
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(now);
  return { date, time };
}

/** Offset like "+07:00" of a time zone on a given date, so a local date/time becomes an instant. */
export function zoneOffset(date: string, timeZone: string = DEFAULT_TZ): string {
  const probe = new Date(`${date}T12:00:00Z`);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    timeZoneName: "longOffset",
  }).formatToParts(probe);
  const name = parts.find((p) => p.type === "timeZoneName")?.value ?? "GMT";
  const m = /GMT([+-]\d{2}):?(\d{2})?/.exec(name);
  return m ? `${m[1]}:${m[2] ?? "00"}` : "+00:00";
}

/** Date-only stays "YYYY-MM-DD" (has_time false); with a time it becomes an ISO instant with offset. */
export function toApiDate(date: string, time: string, timeZone: string = DEFAULT_TZ): string {
  if (!time) return date;
  return `${date}T${time}:00${zoneOffset(date, timeZone)}`;
}
