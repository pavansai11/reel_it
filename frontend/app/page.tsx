"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import DropZone, { MAX_FILES } from "@/components/DropZone";
import VibeSelector from "@/components/VibeSelector";
import { createJob, uploadFiles, type Vibe } from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [files, setFiles] = useState<File[]>([]);
  const [vibe, setVibe] = useState<Vibe>("energetic");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tooMany = files.length > MAX_FILES;
  const canSubmit = files.length > 0 && !tooMany && !busy;

  async function makeReel() {
    setError(null);
    setBusy(true);
    try {
      const { assets } = await uploadFiles(files);
      if (assets.length === 0) throw new Error("No supported photos or videos found.");
      const { job_id } = await createJob(vibe, assets.map((a) => a.id));
      router.push(`/processing/${job_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <section className="pt-4 text-center">
        <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">
          One tap. <span className="brand-gradient">A reel you&apos;d actually post.</span>
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-white/55">
          Drop a messy dump of trip photos and clips. We curate the best moments and cut them
          to the beat — no manual editing, no template slots.
        </p>
      </section>

      <section className="card p-5">
        <DropZone files={files} onChange={setFiles} />
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-white/50">
          Pick a vibe
        </h2>
        <VibeSelector value={vibe} onChange={setVibe} />
      </section>

      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <button
        disabled={!canSubmit}
        onClick={makeReel}
        className="w-full rounded-2xl bg-gradient-to-r from-violet-500 via-fuchsia-500 to-orange-400 py-4 text-lg font-bold text-white shadow-lg shadow-fuchsia-500/20 transition disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? "Uploading…" : "Make my reel ✨"}
      </button>
      <p className="text-center text-xs text-white/30">
        Free reels include a small watermark. Media is auto-deleted after 48 hours.
      </p>
    </div>
  );
}
