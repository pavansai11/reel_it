// Typed API client. Every call sends the session cookie (credentials:include)
// since the backend identifies anonymous sessions via an httponly cookie.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

export type Vibe = "energetic" | "cinematic" | "aesthetic";

export interface Asset {
  id: string;
  kind: "photo" | "video";
  original_filename: string | null;
}

export interface UploadResponse {
  session_id: string;
  assets: Asset[];
}

export interface JobResponse {
  job_id: string;
  status: string;
}

export interface JobStatus {
  job_id: string;
  status: string;
  stage_progress: number;
  stage_message: string;
  error: string | null;
}

export interface EdlDecision {
  moment_id: string;
  order: number;
  start_at_s: number;
  duration_s: number;
  effect: string;
  overlay_text: string | null;
  reason: string;
}

export interface JobResult {
  job_id: string;
  status: string;
  result_url: string | null;
  vibe: string;
  track_id: string | null;
  edl: { decisions: EdlDecision[] } | null;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function uploadFiles(files: File[]): Promise<UploadResponse> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const res = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    body: form,
    credentials: "include",
  });
  return jsonOrThrow<UploadResponse>(res);
}

export async function createJob(vibe: Vibe, assetIds: string[]): Promise<JobResponse> {
  const res = await fetch(`${API_BASE}/job`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vibe, asset_ids: assetIds }),
    credentials: "include",
  });
  return jsonOrThrow<JobResponse>(res);
}

export async function getStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/job/${jobId}/status`, {
    credentials: "include",
    cache: "no-store",
  });
  return jsonOrThrow<JobStatus>(res);
}

export async function getResult(jobId: string): Promise<JobResult> {
  const res = await fetch(`${API_BASE}/job/${jobId}/result`, {
    credentials: "include",
    cache: "no-store",
  });
  return jsonOrThrow<JobResult>(res);
}

export async function logAction(
  jobId: string,
  action: string,
  detail?: Record<string, unknown>
): Promise<JobResponse> {
  const res = await fetch(`${API_BASE}/job/${jobId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, detail: detail ?? null }),
    credentials: "include",
  });
  return jsonOrThrow<JobResponse>(res);
}

export const STAGE_ORDER = [
  "queued",
  "ingesting",
  "shots",
  "scoring",
  "editing",
  "rendering",
  "done",
];
