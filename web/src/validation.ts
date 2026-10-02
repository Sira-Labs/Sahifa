import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_BYTES, MAX_UPLOAD_FILES, MAX_UPLOAD_MB } from "./constants";
import { formatBytes } from "./format";

/** The accepted extension of a file name, lower-cased, or null. */
export function acceptedExtension(name: string): string | null {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.find((ext) => lower.endsWith(ext)) ?? null;
}

/** Why one file cannot be uploaded, or null when it can. */
export function fileError(file: File): string | null {
  if (!acceptedExtension(file.name)) return `Not a supported file type. Use ${ACCEPTED_EXTENSIONS.join(", ")}.`;
  if (file.size > MAX_UPLOAD_BYTES) return `Too large: ${formatBytes(file.size)}; the limit is ${MAX_UPLOAD_MB} MB per file.`;
  if (file.size === 0) return "The file is empty.";
  return null;
}

/** Why the selection as a whole cannot be uploaded, or null. */
export function countError(count: number): string | null {
  if (count === 0) return "Add at least one file.";
  if (count > MAX_UPLOAD_FILES) return `Too many files: ${count} selected, at most ${MAX_UPLOAD_FILES} per scan.`;
  return null;
}

/** Add files to a selection; a file with the same name and size replaces the earlier one. */
export function mergeFiles(current: File[], added: File[]): File[] {
  const key = (f: File) => `${f.name}\u0000${f.size}`;
  const addedKeys = new Set(added.map(key));
  return [...current.filter((f) => !addedKeys.has(key(f))), ...added];
}

/** A sample size from the form: a positive whole number, or an error. */
export function parseSampleRows(text: string): { value: number | null; error: string | null } {
  const t = text.trim().replace(/[,_\s]/g, "");
  if (!/^\d+$/.test(t)) return { value: null, error: "Enter a whole number of rows, or tick “Read everything”." };
  const n = Number(t);
  if (n < 1) return { value: null, error: "Read at least one row, or tick “Read everything”." };
  return { value: n, error: null };
}
