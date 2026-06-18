"use client";

import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";

import { getResult, logAction, type JobResult } from "@/lib/api";

export default function ResultPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [result, setResult] = useState<JobResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loved, setLoved] = useState(false);
  const [rerolling, setRerolling] = useState(false);
  const [showClips, setShowClips] = useState(false);

  useEffect(() => {
    if (!id) return;
    getResult(id)
      .then(setResult)
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load your reel."));
  }, [id]);

  async function download() {
    if (!result?.result_url) return;
    logAction(id, "downloaded").catch(() => {});
    const a = document.createElement("a");
    a.href = result.result_url;
    a.download = "reelmagic.mp4";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function reroll() {
    setRerolling(true);
    try {
      await logAction(id, "rerolled");
      router.push(`/processing/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-roll failed.");
      setRerolling(false);
    }
  }

  async function love() {
    setLoved(true);
    logAction(id, "accepted").catch(() => {});
  }

  async function removeClip(momentId: string) {
    await logAction(id, "deleted_clip", { moment_id: momentId, note: "user requested removal" });
    // MVP: removal is logged for the flywheel; nudge a re-roll to honor it.
    reroll();
  }

  if (error) {
    return (
      <div className="card mt-10 p-8 text-center">
        <p className="text-white/60">{error}</p>
        <Link href="/" className="mt-5 inline-block rounded-xl bg-white/10 px-5 py-2.5 hover:bg-white/20">
          Start over
        </Link>
      </div>
    );
  }

  if (!result) {
    return <div className="mt-16 text-center text-white/40">Loading your reel…</div>;
  }

  return (
    <div className="mx-auto mt-6 max-w-md">
      <h1 className="mb-1 text-center text-2xl font-bold">Your reel is ready 🎉</h1>
      <p className="mb-5 text-center text-sm text-white/45">
        {result.vibe} vibe · free reel · watermark included
      </p>

      <div className="card overflow-hidden">
        {result.result_url ? (
          <video
            src={result.result_url}
            controls
            playsInline
            autoPlay
            loop
            className="mx-auto aspect-[9/16] max-h-[72vh] w-full bg-black object-contain"
          />
        ) : (
          <div className="p-10 text-center text-white/40">No video URL.</div>
        )}
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3">
        <button
          onClick={download}
          className="rounded-xl bg-gradient-to-r from-violet-500 to-fuchsia-500 py-3 font-semibold"
        >
          ⬇ Download
        </button>
        <button
          onClick={reroll}
          disabled={rerolling}
          className="rounded-xl bg-white/10 py-3 font-semibold hover:bg-white/20 disabled:opacity-50"
        >
          {rerolling ? "Re-rolling…" : "🎲 Re-roll"}
        </button>
      </div>

      <div className="mt-3 flex items-center justify-between gap-3">
        <button
          onClick={love}
          disabled={loved}
          className="flex-1 rounded-xl border border-white/10 py-2.5 text-sm hover:bg-white/5 disabled:opacity-60"
        >
          {loved ? "Thanks! 💜" : "❤️ Love it"}
        </button>
        <button
          onClick={() => setShowClips((s) => !s)}
          className="flex-1 rounded-xl border border-white/10 py-2.5 text-sm hover:bg-white/5"
        >
          Not happy? Remove a clip
        </button>
      </div>

      {showClips && result.edl && (
        <div className="card mt-4 p-4">
          <p className="mb-3 text-xs text-white/40">
            Tap a moment to remove it — we&apos;ll recut without it.
          </p>
          <ul className="space-y-1.5">
            {result.edl.decisions.map((d) => (
              <li key={d.moment_id}>
                <button
                  onClick={() => removeClip(d.moment_id)}
                  className="flex w-full items-center justify-between rounded-lg bg-white/5 px-3 py-2 text-left text-sm hover:bg-rose-500/15"
                >
                  <span className="text-white/70">
                    #{d.order + 1} · {d.reason || d.moment_id}
                  </span>
                  <span className="text-xs text-white/35">{d.duration_s.toFixed(1)}s ✕</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-6 text-center">
        <Link href="/" className="text-sm text-white/40 hover:text-white">
          ← Make another
        </Link>
      </div>
    </div>
  );
}
