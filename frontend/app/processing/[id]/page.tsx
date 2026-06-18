"use client";

import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { getStatus, STAGE_ORDER, type JobStatus } from "@/lib/api";

const ENCOURAGEMENT = [
  "Hunting for your best shots…",
  "Throwing out the blurry ones…",
  "Feeling the rhythm…",
  "Lining cuts up to the beat…",
  "Almost there…",
];

export default function ProcessingPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tick = useRef(0);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const s = await getStatus(id);
        if (!alive) return;
        setStatus(s);
        if (s.status === "done") {
          router.replace(`/result/${id}`);
          return;
        }
        if (s.status === "failed") {
          setError(s.error || "The reel couldn't be generated.");
          return;
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "Lost connection.");
      }
      tick.current += 1;
      timer = setTimeout(poll, 1500);
    }
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [id, router]);

  const pct = Math.round(
    ((status?.stage_progress ??
      (status ? STAGE_ORDER.indexOf(status.status) / STAGE_ORDER.length : 0)) || 0.02) * 100
  );

  if (error) {
    return (
      <div className="card mt-10 p-8 text-center">
        <div className="text-3xl">😕</div>
        <h1 className="mt-3 text-xl font-bold">We couldn&apos;t finish this one</h1>
        <p className="mx-auto mt-2 max-w-md text-sm text-white/50">{error}</p>
        <Link
          href="/"
          className="mt-6 inline-block rounded-xl bg-white/10 px-5 py-2.5 font-medium hover:bg-white/20"
        >
          Try again
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto mt-10 max-w-md text-center">
      <div className="mx-auto mb-8 h-24 w-24 animate-pulse rounded-3xl bg-gradient-to-br from-violet-500 via-fuchsia-500 to-orange-400" />
      <h1 className="text-2xl font-bold">{status?.stage_message ?? "Getting ready…"}</h1>
      <p className="mt-2 text-sm text-white/45">
        {ENCOURAGEMENT[tick.current % ENCOURAGEMENT.length]}
      </p>

      <div className="mt-8 h-2.5 w-full overflow-hidden rounded-full bg-white/10">
        <div
          className="h-full rounded-full bg-gradient-to-r from-violet-500 via-fuchsia-500 to-orange-400 transition-all duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-white/30">{pct}%</p>
    </div>
  );
}
