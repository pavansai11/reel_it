"use client";

import type { Vibe } from "@/lib/api";

const VIBES: { id: Vibe; label: string; tagline: string; emoji: string; ring: string }[] = [
  { id: "energetic", label: "Energetic", tagline: "fast, punchy, fun", emoji: "⚡️", ring: "ring-fuchsia-400" },
  { id: "cinematic", label: "Cinematic", tagline: "epic, emotional, wide", emoji: "🎬", ring: "ring-indigo-400" },
  { id: "aesthetic", label: "Aesthetic", tagline: "dreamy, relaxed, soft", emoji: "🌸", ring: "ring-rose-300" },
];

export default function VibeSelector({
  value,
  onChange,
}: {
  value: Vibe;
  onChange: (v: Vibe) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {VIBES.map((v) => {
        const active = value === v.id;
        return (
          <button
            key={v.id}
            type="button"
            onClick={() => onChange(v.id)}
            className={`card p-4 text-left transition ${
              active ? `ring-2 ${v.ring}` : "hover:border-white/25"
            }`}
          >
            <div className="text-2xl">{v.emoji}</div>
            <div className="mt-2 font-semibold">{v.label}</div>
            <div className="text-sm text-white/50">{v.tagline}</div>
          </button>
        );
      })}
    </div>
  );
}
