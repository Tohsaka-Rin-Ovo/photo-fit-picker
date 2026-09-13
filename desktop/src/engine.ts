import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import type { AnalysisJob, AnalysisOptions, ReviewStatus } from "./types";

interface EngineEndpoint {
  host: string;
  port: number;
  token: string;
}

const isTauri = () => "__TAURI_INTERNALS__" in window;

class EngineClient {
  private endpoint: EngineEndpoint | null = null;
  private connecting: Promise<EngineEndpoint> | null = null;
  private thumbnailCache = new Map<string, Promise<string>>();

  get desktopAvailable(): boolean {
    return isTauri();
  }

  private async connect(): Promise<EngineEndpoint> {
    if (this.endpoint) return this.endpoint;
    if (!this.connecting) {
      this.connecting = invoke<EngineEndpoint>("start_engine").then((endpoint) => {
        this.endpoint = endpoint;
        return endpoint;
      });
    }
    return this.connecting;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const endpoint = await this.connect();
    const response = await fetch(`http://${endpoint.host}:${endpoint.port}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${endpoint.token}`,
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
    const payload = (await response.json()) as T & { error?: string };
    if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
    return payload;
  }

  async chooseFolder(): Promise<string | null> {
    if (!isTauri()) return null;
    const selected = await open({ directory: true, multiple: false });
    return typeof selected === "string" ? selected : null;
  }

  async demoFolder(): Promise<string | null> {
    return isTauri() ? invoke<string>("demo_folder") : null;
  }

  async startAnalysis(source: string, options: AnalysisOptions): Promise<string> {
    const result = await this.request<{ job_id: string }>("/api/analyze", {
      method: "POST",
      body: JSON.stringify({ source, options }),
    });
    return result.job_id;
  }

  job(jobId: string): Promise<AnalysisJob> {
    return this.request<AnalysisJob>(`/api/jobs/${jobId}`);
  }

  cancel(jobId: string): Promise<{ cancelled: boolean }> {
    return this.request("/api/cancel", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    });
  }

  review(updates: Array<{ id: string; status: ReviewStatus }>): Promise<{ changed: number }> {
    return this.request("/api/review", {
      method: "POST",
      body: JSON.stringify({ updates }),
    });
  }

  move(photoIds: string[], destination: string): Promise<{ moved_files: number }> {
    return this.request("/api/move", {
      method: "POST",
      body: JSON.stringify({ photo_ids: photoIds, destination }),
    });
  }

  trash(photoIds: string[]): Promise<{ trashed_files: number }> {
    return this.request("/api/trash", {
      method: "POST",
      body: JSON.stringify({ photo_ids: photoIds, confirmed: true }),
    });
  }

  undo(destination: string): Promise<{ restored_files: number; errors: string[] }> {
    return this.request("/api/undo", {
      method: "POST",
      body: JSON.stringify({ destination }),
    });
  }

  thumbnailUrl(photoId: string, maximum = 720): Promise<string> {
    const key = `${photoId}:${maximum}`;
    const cached = this.thumbnailCache.get(key);
    if (cached) return cached;
    const pending = this.connect().then(async (endpoint) => {
      const response = await fetch(
        `http://${endpoint.host}:${endpoint.port}/api/thumbnails/${photoId}?max=${maximum}`,
        { headers: { Authorization: `Bearer ${endpoint.token}` } },
      );
      if (!response.ok) throw new Error("无法读取照片预览");
      return URL.createObjectURL(await response.blob());
    });
    this.thumbnailCache.set(key, pending);
    return pending;
  }
}

export const engine = new EngineClient();
