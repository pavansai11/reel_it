"use client";

import { useCallback, useRef, useState } from "react";

export const MAX_FILES = 60;

export default function DropZone({
  files,
  onChange,
}: {
  files: File[];
  onChange: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const accept = useCallback(
    (list: FileList | null) => {
      if (!list) return;
      const picked = Array.from(list).filter(
        (f) => f.type.startsWith("image/") || f.type.startsWith("video/")
      );
      onChange([...files, ...picked]);
    },
    [files, onChange]
  );

  return (
    <div>
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          accept(e.dataTransfer.files);
        }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-10 text-center transition ${
          dragging ? "border-fuchsia-400 bg-fuchsia-500/5" : "border-white/15 hover:border-white/30"
        }`}
      >
        <div className="text-4xl">📸🎥</div>
        <p className="mt-3 font-medium">Drop your trip photos &amp; clips here</p>
        <p className="text-sm text-white/40">or click to browse — up to {MAX_FILES} files</p>
        <input
          ref={inputRef}
          type="file"
          accept="image/*,video/*"
          multiple
          hidden
          onChange={(e) => accept(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className={files.length > MAX_FILES ? "text-rose-400" : "text-white/60"}>
              {files.length} file{files.length === 1 ? "" : "s"} selected
              {files.length > MAX_FILES ? ` — max ${MAX_FILES}` : ""}
            </span>
            <button className="text-white/50 hover:text-white" onClick={() => onChange([])}>
              Clear
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {files.slice(0, 18).map((f, i) => (
              <span
                key={i}
                className="max-w-[160px] truncate rounded-lg bg-white/5 px-2 py-1 text-xs text-white/60"
                title={f.name}
              >
                {f.type.startsWith("video/") ? "🎞 " : "🖼 "}
                {f.name}
              </span>
            ))}
            {files.length > 18 && (
              <span className="rounded-lg bg-white/5 px-2 py-1 text-xs text-white/40">
                +{files.length - 18} more
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
