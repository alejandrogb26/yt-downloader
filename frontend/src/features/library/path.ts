export function displayPath(path: string): string {
  return path ? `/${path}` : "/";
}

export function parentPath(path: string): string {
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}

export function breadcrumbs(path: string): Array<{ label: string; path: string }> {
  const parts = path.split("/").filter(Boolean);
  const crumbs = [{ label: "Inicio", path: "" }];
  let current = "";
  for (const part of parts) {
    current = current ? `${current}/${part}` : part;
    crumbs.push({ label: part, path: current });
  }
  return crumbs;
}

export function isSafeRelativeDisplay(value: string): boolean {
  return !value.startsWith("/") && !value.includes("\\") && !value.includes("\0");
}
