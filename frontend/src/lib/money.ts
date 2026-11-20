/**
 * Money is never a float (PRD 4.3): the API takes and returns strings like "25000.00".
 * The input accepts Indonesian style (25.000 / 25.000,50) and plain (25000 / 25000.50).
 */
export function parseMoney(input: string): string | null {
  let s = input
    .trim()
    .replace(/^rp\.?\s*/i, "")
    .replace(/\s+/g, "");
  if (!s) return null;
  if (s.includes(",")) {
    // comma is the decimal separator, dots are thousands
    s = s.replace(/\./g, "").replace(",", ".");
  } else if (/^\d{1,3}(\.\d{3})+$/.test(s)) {
    s = s.replace(/\./g, ""); // 25.000 -> thousands
  }
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null;
  const [whole = "0", frac = ""] = s.split(".");
  const normalized = `${whole.replace(/^0+(?=\d)/, "")}.${frac.padEnd(2, "0")}`;
  return /^0+\.00$/.test(normalized) ? null : normalized;
}

const idr = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});

/** "25000.00" -> "Rp25.000". Digits are grouped as text so no float is involved. */
export function formatIdr(amount: string): string {
  const [whole = "0", frac = "00"] = amount.split(".");
  const negative = whole.startsWith("-");
  const digits = whole.replace("-", "");
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const decimals = /^0*$/.test(frac) ? "" : `,${frac.replace(/0+$/, "")}`;
  return `${negative ? "-" : ""}Rp${grouped}${decimals}`;
}

export { idr as idrFormatter };
