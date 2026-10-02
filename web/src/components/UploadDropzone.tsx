import { useId, useState, type DragEvent } from "react";
import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_FILES, MAX_UPLOAD_MB } from "../constants";

/** A drop zone with a file picker. Validation is the caller's; this only collects files. */
export function UploadDropzone({ onFiles, disabled }: { onFiles: (files: File[]) => void; disabled?: boolean }) {
  const [dragging, setDragging] = useState(false);
  const inputId = useId();
  const hintId = useId();

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length) onFiles(files);
  }

  return (
    <div
      className={`dropzone${dragging ? " is-dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <p className="font-semibold">Drop files here</p>
      <p className="muted">or</p>
      <label htmlFor={inputId} className="btn">
        Choose files
      </label>
      <input
        id={inputId}
        type="file"
        multiple
        className="sr-only"
        accept={ACCEPTED_EXTENSIONS.join(",")}
        aria-describedby={hintId}
        disabled={disabled}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          e.target.value = "";
        }}
      />
      <p id={hintId} className="muted text-sm">
        <span className="num">{ACCEPTED_EXTENSIONS.join(" ")}</span> · up to {MAX_UPLOAD_FILES} files · up to {MAX_UPLOAD_MB} MB each
      </p>
    </div>
  );
}
