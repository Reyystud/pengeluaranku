import en from "@/messages/en.json";

type Tree = { [key: string]: string | Tree };

/** Look up a UI string by dotted key, with `{name}` placeholders. Strings live in messages/en.json. */
export function t(key: string, vars: Record<string, string | number> = {}): string {
  let node: string | Tree | undefined = en as Tree;
  for (const part of key.split(".")) {
    node = typeof node === "object" ? node[part] : undefined;
  }
  if (typeof node !== "string") return key;
  return node.replace(/\{(\w+)\}/g, (_, name: string) => String(vars[name] ?? `{${name}}`));
}
