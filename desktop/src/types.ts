export type ReviewStatus = "pending" | "kept" | "rejected" | "moved" | "trashed";
export type ViewMode = "compact" | "large" | "list";
export type SortMode = "recommended" | "time" | "size";
export type ThemeMode = "light" | "dark" | "kook";

export interface PhotoMetadata {
  captured_at: string | null;
  make: string;
  model: string;
  lens: string;
  exposure_time: number | null;
  aperture: number | null;
  iso: number | null;
  focal_length: number | null;
  exposure_bias: number | null;
  white_balance: string;
  focus_mode: string;
  metering_mode: string;
  exposure_program: string;
  flash: string;
  software: string;
  latitude: number | null;
  longitude: number | null;
  details: string[][];
  camera_label: string;
  shooting_summary: string;
}

export interface Photo {
  id: string;
  path: string;
  name: string;
  format: string;
  width: number;
  height: number;
  dimensions: string;
  file_size: number;
  file_size_label: string;
  captured_at: string;
  quality_score: number;
  quality_summary: string;
  portrait_detected: boolean | null;
  status: ReviewStatus;
  recommended: boolean;
  recommendation_reason: string;
  metadata: PhotoMetadata;
  image_url?: string;
}

export interface PhotoGroup {
  id: number;
  count: number;
  reviewed: boolean;
  kept_count: number;
  photos: Photo[];
}

export interface AnalysisOptions {
  similarity_threshold: number;
  time_window_seconds: number;
  color_weight: number;
  hash_method: "difference" | "average";
  detect_exact_duplicates: boolean;
  sharpness_weight: number;
  exposure_weight: number;
  resolution_weight: number;
  detect_portraits: boolean;
  performance_mode: "balanced" | "high";
}

export interface Project {
  id: string;
  name: string;
  folders: string[];
  createdAt: string;
  lastOpenedAt: string;
}

export interface Preferences {
  theme: ThemeMode;
  reduceMotion: boolean;
  hideSingletons: boolean;
  viewMode: ViewMode;
  thumbnailSize: number;
  sortMode: SortMode;
  options: AnalysisOptions;
}

export interface AnalysisJob {
  id: string;
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  stage: "scan" | "features" | "grouping" | "complete";
  current: number;
  total: number;
  detail: string;
  source: string;
  sources?: string[];
  failure_count: number;
  error?: string;
  groups?: PhotoGroup[];
}
