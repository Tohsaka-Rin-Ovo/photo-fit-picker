import {
  ArrowLeft,
  ArrowRight,
  ArrowUpDown,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Cpu,
  FlaskConical,
  Folder,
  FolderOpen,
  Grid2X2,
  HardDrive,
  Image as ImageIcon,
  Images,
  Info,
  Leaf,
  List,
  Maximize2,
  Moon,
  MoveRight,
  Play,
  RotateCcw,
  Rows3,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Square,
  Sun,
  Trash2,
  Undo2,
  UserRound,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { demoGroups } from "./demo";
import { engine } from "./engine";
import type {
  AnalysisJob,
  Photo,
  PhotoGroup,
  Preferences,
  ReviewStatus,
  SortMode,
  ThemeMode,
  ViewMode,
} from "./types";

const DEFAULT_PREFERENCES: Preferences = {
  theme: "light",
  reduceMotion: false,
  hideSingletons: true,
  viewMode: "compact",
  thumbnailSize: 210,
  sortMode: "recommended",
  options: {
    similarity_threshold: 0.84,
    time_window_seconds: 90,
    color_weight: 0.22,
    hash_method: "difference",
    detect_exact_duplicates: true,
    sharpness_weight: 0.75,
    exposure_weight: 0.25,
    resolution_weight: 0,
    detect_portraits: false,
  },
};

type SettingsSection = "general" | "folders" | "analysis" | "experiments" | "about";
type ConfirmAction = "trash" | "restart" | null;

function loadPreferences(): Preferences {
  try {
    const saved = JSON.parse(localStorage.getItem("photo-fit-picker.preferences") || "{}");
    return {
      ...DEFAULT_PREFERENCES,
      ...saved,
      options: { ...DEFAULT_PREFERENCES.options, ...(saved.options || {}) },
    };
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知时间";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function sortPhotos(photos: Photo[], mode: SortMode): Photo[] {
  return [...photos].sort((left, right) => {
    if (mode === "size") return right.file_size - left.file_size;
    if (mode === "time") return left.captured_at.localeCompare(right.captured_at);
    const rank = (photo: Photo) => Number(photo.recommended) * 2 + Number(photo.portrait_detected);
    return rank(right) - rank(left) || right.quality_score - left.quality_score;
  });
}

function statusLabel(status: ReviewStatus): string {
  if (status === "kept") return "已保留";
  if (status === "rejected") return "已排除";
  if (status === "moved") return "已移动";
  if (status === "trashed") return "回收站";
  return "待筛选";
}

function IconButton({
  label,
  active = false,
  disabled = false,
  children,
  onClick,
}: {
  label: string;
  active?: boolean;
  disabled?: boolean;
  children: ReactNode;
  onClick?: () => void;
}) {
  return (
    <button
      className={`icon-button${active ? " is-active" : ""}`}
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: Array<{ value: T; label: string; icon?: ReactNode }>;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={value === option.value ? "is-active" : ""}
          onClick={() => onChange(option.value)}
          title={option.label}
        >
          {option.icon}
          <span>{option.label}</span>
        </button>
      ))}
    </div>
  );
}

function Switch({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={`switch${checked ? " is-on" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  );
}

function Thumbnail({ photo, maximum = 720 }: { photo: Photo; maximum?: number }) {
  const [source, setSource] = useState(photo.image_url || "");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setFailed(false);
    if (photo.image_url) {
      setSource(photo.image_url);
      return () => {
        active = false;
      };
    }
    engine.thumbnailUrl(photo.id, maximum).then(
      (url) => active && setSource(url),
      () => active && setFailed(true),
    );
    return () => {
      active = false;
    };
  }, [maximum, photo.id, photo.image_url]);

  if (failed) {
    return (
      <div className="thumbnail-fallback">
        <ImageIcon size={22} />
        <span>无法预览</span>
      </div>
    );
  }
  return source ? <img src={source} alt="" draggable={false} /> : <div className="thumbnail-skeleton" />;
}

function PhotoItem({
  photo,
  selected,
  mode,
  onSelect,
  onOpen,
}: {
  photo: Photo;
  selected: boolean;
  mode: ViewMode;
  onSelect: () => void;
  onOpen: () => void;
}) {
  return (
    <article
      className={`photo-item photo-${mode}${selected ? " is-selected" : ""}`}
      onDoubleClick={onOpen}
    >
      <button
        type="button"
        className="selection-check"
        aria-label={selected ? `取消选择 ${photo.name}` : `选择 ${photo.name}`}
        aria-pressed={selected}
        onClick={(event) => {
          event.stopPropagation();
          onSelect();
        }}
      >
        {selected && <Check size={13} strokeWidth={3} />}
      </button>
      <button type="button" className="photo-open" onClick={onOpen} aria-label={`查看 ${photo.name}`}>
        <div className="photo-media">
          <Thumbnail photo={photo} maximum={mode === "large" ? 1200 : 720} />
          <div className="photo-badges">
            {photo.recommended && (
              <span className="badge badge-best"><Sparkles size={12} />推荐</span>
            )}
            {photo.portrait_detected && (
              <span className="badge"><UserRound size={12} />人像</span>
            )}
          </div>
          {photo.status !== "pending" && (
            <span className={`status-chip status-${photo.status}`}>{statusLabel(photo.status)}</span>
          )}
        </div>
        <div className="photo-copy">
          <strong title={photo.name}>{photo.name}</strong>
          <span>{formatDate(photo.captured_at)}</span>
          <span>{photo.dimensions} · {photo.file_size_label}</span>
          {mode === "list" && <span className="list-quality">{photo.quality_summary}</span>}
        </div>
      </button>
    </article>
  );
}

function VirtualPhotoView({
  photos,
  mode,
  thumbnailSize,
  selected,
  onToggle,
  onOpen,
}: {
  photos: Photo[];
  mode: ViewMode;
  thumbnailSize: number;
  selected: Set<string>;
  onToggle: (id: string) => void;
  onOpen: (photo: Photo) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  useEffect(() => {
    if (!scroller.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(scroller.current);
    return () => observer.disconnect();
  }, []);

  const gap = mode === "large" ? 18 : 12;
  const columns = mode === "list" ? 1 : Math.max(1, Math.floor((width - 36 + gap) / (thumbnailSize + gap)));
  const itemWidth = mode === "list" ? width - 36 : (width - 36 - gap * (columns - 1)) / columns;
  const rowHeight = mode === "list" ? 82 : itemWidth * 0.67 + 70;
  const rows = Math.ceil(photos.length / columns);
  const virtualizer = useVirtualizer({
    count: rows,
    getScrollElement: () => scroller.current,
    estimateSize: () => rowHeight,
    overscan: 3,
  });

  useEffect(() => virtualizer.measure(), [columns, rowHeight, virtualizer]);

  return (
    <div className="photo-scroller" ref={scroller}>
      <div className="virtual-canvas" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const start = virtualRow.index * columns;
          return (
            <div
              className="virtual-row"
              key={virtualRow.key}
              style={{
                height: rowHeight,
                transform: `translateY(${virtualRow.start}px)`,
                gridTemplateColumns: mode === "list" ? "1fr" : `repeat(${columns}, minmax(0, 1fr))`,
                gap,
              }}
            >
              {photos.slice(start, start + columns).map((photo) => (
                <PhotoItem
                  key={photo.id}
                  photo={photo}
                  selected={selected.has(photo.id)}
                  mode={mode}
                  onSelect={() => onToggle(photo.id)}
                  onOpen={() => onOpen(photo)}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DetailViewer({ photo, photos, onClose, onNavigate, onReview }: {
  photo: Photo;
  photos: Photo[];
  onClose: () => void;
  onNavigate: (photo: Photo) => void;
  onReview: (status: ReviewStatus) => void;
}) {
  const [fit, setFit] = useState(true);
  const [zoom, setZoom] = useState(1);
  const index = photos.findIndex((item) => item.id === photo.id);
  const navigate = (offset: number) => {
    const next = photos[index + offset];
    if (next) onNavigate(next);
  };
  useEffect(() => {
    setFit(true);
    setZoom(1);
  }, [photo.id]);

  return (
    <div className="detail-layer" role="dialog" aria-modal="true" aria-label="照片详情">
      <header className="detail-header">
        <IconButton label="关闭详情" onClick={onClose}><X size={20} /></IconButton>
        <div className="detail-title"><strong>{photo.name}</strong><span>{index + 1} / {photos.length}</span></div>
        <div className="detail-tools">
          <IconButton label="缩小" onClick={() => { setFit(false); setZoom((value) => Math.max(0.5, value - 0.25)); }}><ZoomOut size={19} /></IconButton>
          <button className="zoom-value" type="button" onClick={() => { setFit(!fit); setZoom(1); }}>{fit ? "适合" : `${Math.round(zoom * 100)}%`}</button>
          <IconButton label="放大" onClick={() => { setFit(false); setZoom((value) => Math.min(4, value + 0.25)); }}><ZoomIn size={19} /></IconButton>
          <IconButton label="适合窗口" active={fit} onClick={() => { setFit(true); setZoom(1); }}><Maximize2 size={19} /></IconButton>
        </div>
      </header>
      <div className="detail-body">
        <div
          className={`detail-stage${fit ? " is-fit" : " is-actual"}`}
          onDoubleClick={() => { setFit(!fit); setZoom(1); }}
        >
          <div className="detail-image" style={{ "--zoom": zoom } as CSSProperties}>
            <Thumbnail photo={photo} maximum={1600} />
          </div>
          <IconButton label="上一张" disabled={index <= 0} onClick={() => navigate(-1)}><ArrowLeft size={21} /></IconButton>
          <IconButton label="下一张" disabled={index >= photos.length - 1} onClick={() => navigate(1)}><ArrowRight size={21} /></IconButton>
        </div>
        <aside className="inspector">
          <div className="inspector-heading">
            <div><span className="eyebrow">照片信息</span><h2>{photo.name}</h2></div>
            <span className={`quality-score${photo.recommended ? " is-best" : ""}`}>{Math.round(photo.quality_score * 100)}</span>
          </div>
          <p className="quality-line">{photo.quality_summary}</p>
          {photo.recommended && <p className="recommendation"><Sparkles size={15} />{photo.recommendation_reason}</p>}
          <dl className="metadata-list">
            <div><dt>拍摄时间</dt><dd>{formatDate(photo.captured_at)}</dd></div>
            <div><dt>尺寸</dt><dd>{photo.dimensions}</dd></div>
            <div><dt>格式与大小</dt><dd>{photo.format} · {photo.file_size_label}</dd></div>
            <div><dt>相机</dt><dd>{photo.metadata.camera_label || "未记录"}</dd></div>
            <div><dt>镜头</dt><dd>{photo.metadata.lens || "未记录"}</dd></div>
            <div><dt>拍摄参数</dt><dd>{photo.metadata.shooting_summary || "未记录"}</dd></div>
          </dl>
          <div className="detail-actions">
            <button className="button secondary" type="button" onClick={() => onReview("rejected")}><X size={17} />排除</button>
            <button className="button primary" type="button" onClick={() => onReview("kept")}><Check size={17} />保留</button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function SettingRow({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <div className="setting-row">
      <div><strong>{title}</strong><p>{description}</p></div>
      <div className="setting-control">{children}</div>
    </div>
  );
}

function SettingsPage({ preferences, destination, section, onSection, onChange, onDestination, onClose }: {
  preferences: Preferences;
  destination: string;
  section: SettingsSection;
  onSection: (section: SettingsSection) => void;
  onChange: (preferences: Preferences) => void;
  onDestination: () => void;
  onClose: () => void;
}) {
  const patch = (value: Partial<Preferences>) => onChange({ ...preferences, ...value });
  const patchOptions = (value: Partial<Preferences["options"]>) =>
    onChange({ ...preferences, options: { ...preferences.options, ...value } });
  const navigation: Array<[SettingsSection, string, ReactNode]> = [
    ["general", "通用", <SlidersHorizontal size={17} />],
    ["folders", "文件夹", <Folder size={17} />],
    ["analysis", "筛选算法", <Cpu size={17} />],
    ["experiments", "实验功能", <FlaskConical size={17} />],
    ["about", "关于拾影", <Info size={17} />],
  ];
  const titles: Record<SettingsSection, string> = {
    general: "通用", folders: "文件夹", analysis: "筛选算法", experiments: "实验功能", about: "关于拾影",
  };

  return (
    <div className="settings-page">
      <aside className="settings-sidebar">
        <div className="window-drag" data-tauri-drag-region />
        <button className="back-button" type="button" onClick={onClose}><ArrowLeft size={18} />返回照片</button>
        <nav>
          {navigation.map(([key, label, icon]) => (
            <button type="button" key={key} className={section === key ? "is-active" : ""} onClick={() => onSection(key)}>{icon}<span>{label}</span></button>
          ))}
        </nav>
        <div className="settings-version">拾影 0.8 Alpha</div>
      </aside>
      <main className="settings-content">
        <div className="settings-inner">
          <header><span className="eyebrow">设置</span><h1>{titles[section]}</h1></header>
          {section === "general" && (
            <section className="settings-section">
              <div className="section-label">外观</div>
              <SettingRow title="界面主题" description="明亮、深色和 KOOK 绿使用一致的界面层级。">
                <Segmented<ThemeMode>
                  label="界面主题"
                  value={preferences.theme}
                  onChange={(theme) => patch({ theme })}
                  options={[
                    { value: "light", label: "明亮", icon: <Sun size={15} /> },
                    { value: "dark", label: "深色", icon: <Moon size={15} /> },
                    { value: "kook", label: "KOOK", icon: <Leaf size={15} /> },
                  ]}
                />
              </SettingRow>
              <SettingRow title="减少动态效果" description="减弱页面切换、按钮和浮层反馈动画。"><Switch checked={preferences.reduceMotion} onChange={(reduceMotion) => patch({ reduceMotion })} /></SettingRow>
              <div className="section-label">浏览</div>
              <SettingRow title="隐藏独立照片" description="相似分组中不显示只有一张照片的组，照片不会被删除或忽略。"><Switch checked={preferences.hideSingletons} onChange={(hideSingletons) => patch({ hideSingletons })} /></SettingRow>
            </section>
          )}
          {section === "folders" && (
            <section className="settings-section">
              <div className="section-label">输出位置</div>
              <SettingRow title="已筛选照片文件夹" description="批量移动时使用；原图只会在你明确操作后移动。">
                <button className="path-button" type="button" onClick={onDestination}><FolderOpen size={16} /><span>{destination || "选择文件夹"}</span><ChevronRight size={16} /></button>
              </SettingRow>
              <div className="safety-note"><ShieldCheck size={20} /><div><strong>照片安全边界</strong><p>拾影不会自动删除任何照片。移到系统回收站始终需要二次确认，移动操作保留最近一次撤销记录。</p></div></div>
            </section>
          )}
          {section === "analysis" && (
            <section className="settings-section">
              <div className="section-label">相似照片</div>
              <SettingRow title="相似度" description="数值越高，照片需要越相似才会进入同一组。">
                <div className="range-control"><input type="range" min="70" max="96" value={Math.round(preferences.options.similarity_threshold * 100)} onChange={(event) => patchOptions({ similarity_threshold: Number(event.target.value) / 100 })} /><output>{Math.round(preferences.options.similarity_threshold * 100)}%</output></div>
              </SettingRow>
              <SettingRow title="拍摄时间范围" description="相隔更久的照片通常不属于同一次连拍。">
                <div className="range-control"><input type="range" min="15" max="300" step="15" value={preferences.options.time_window_seconds} onChange={(event) => patchOptions({ time_window_seconds: Number(event.target.value) })} /><output>{preferences.options.time_window_seconds} 秒</output></div>
              </SettingRow>
              <SettingRow title="人像标签" description="在本机检测清晰可见的人脸，会增加少量分析耗时。"><Switch checked={preferences.options.detect_portraits} onChange={(detect_portraits) => patchOptions({ detect_portraits })} /></SettingRow>
              <div className="section-label">推荐依据</div>
              <SettingRow title="清晰度权重" description="提高时更倾向推荐对焦清晰的照片。"><div className="range-control"><input type="range" min="0" max="100" value={Math.round(preferences.options.sharpness_weight * 100)} onChange={(event) => patchOptions({ sharpness_weight: Number(event.target.value) / 100 })} /><output>{Math.round(preferences.options.sharpness_weight * 100)}%</output></div></SettingRow>
              <SettingRow title="曝光权重" description="提高时更倾向推荐明暗均衡的照片。"><div className="range-control"><input type="range" min="0" max="100" value={Math.round(preferences.options.exposure_weight * 100)} onChange={(event) => patchOptions({ exposure_weight: Number(event.target.value) / 100 })} /><output>{Math.round(preferences.options.exposure_weight * 100)}%</output></div></SettingRow>
            </section>
          )}
          {section === "experiments" && (
            <section className="settings-section">
              <div className="section-label">可选算法</div>
              <SettingRow title="感知哈希方式" description="差异哈希适合连拍；均值哈希对整体明暗变化更宽容。">
                <Segmented<"difference" | "average"> label="哈希方式" value={preferences.options.hash_method} onChange={(hash_method) => patchOptions({ hash_method })} options={[{ value: "difference", label: "差异" }, { value: "average", label: "均值" }]} />
              </SettingRow>
              <SettingRow title="跨时间查找完全重复" description="使用内容摘要识别完全一致的文件，不会自动删除副本。"><Switch checked={preferences.options.detect_exact_duplicates} onChange={(detect_exact_duplicates) => patchOptions({ detect_exact_duplicates })} /></SettingRow>
              <div className="roadmap-block">
                <span className="eyebrow">后续计划</span>
                <h2>让整理自然发生在筛选之后</h2>
                <div className="roadmap-list"><span>按拍摄日与时间间隔划分活动</span><span>使用 GPS 信息建议地点分组</span><span>读取 XMP / IPTC 标签与评分</span><span>识别失焦、噪点和高光溢出</span></div>
              </div>
            </section>
          )}
          {section === "about" && (
            <section className="settings-section about-section">
              <div className="about-mark"><ImageIcon size={32} /></div>
              <h2>拾影</h2><p>本地优先的照片筛选工作台</p><span>0.8.0-alpha.1 · Tauri + React</span>
              <div className="safety-note"><ShieldCheck size={20} /><div><strong>只在本机处理</strong><p>图片内容和相机参数不会上传。RAW 文件只读取预览与元数据，原文件不会被改写。</p></div></div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}

function App() {
  const [preferences, setPreferences] = useState(loadPreferences);
  const [page, setPage] = useState<"photos" | "settings">("photos");
  const [settingsSection, setSettingsSection] = useState<SettingsSection>("general");
  const [groups, setGroups] = useState<PhotoGroup[]>([]);
  const [activeGroupId, setActiveGroupId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [source, setSource] = useState("");
  const [destination, setDestination] = useState(() => localStorage.getItem("photo-fit-picker.destination") || "");
  const [job, setJob] = useState<AnalysisJob | null>(null);
  const [detail, setDetail] = useState<Photo | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null);
  const [demoMode, setDemoMode] = useState(false);
  const [lastMoveStatuses, setLastMoveStatuses] = useState<Map<string, ReviewStatus> | null>(null);

  useEffect(() => {
    localStorage.setItem("photo-fit-picker.preferences", JSON.stringify(preferences));
    document.documentElement.dataset.theme = preferences.theme;
    document.documentElement.dataset.motion = preferences.reduceMotion ? "reduced" : "full";
  }, [preferences]);
  useEffect(() => {
    if (!notice) return;
    const timeout = window.setTimeout(() => setNotice(""), 2800);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  const visibleGroups = useMemo(
    () => preferences.hideSingletons ? groups.filter((group) => group.count > 1) : groups,
    [groups, preferences.hideSingletons],
  );
  const activeGroup = visibleGroups.find((group) => group.id === activeGroupId) || visibleGroups[0] || null;
  const photos = useMemo(() => sortPhotos(activeGroup?.photos || [], preferences.sortMode), [activeGroup, preferences.sortMode]);
  const reviewed = groups.flatMap((group) => group.photos).filter((photo) => photo.status !== "pending").length;
  const total = groups.reduce((sum, group) => sum + group.photos.length, 0);
  const selectedPhotos = groups.flatMap((group) => group.photos).filter((photo) => selected.has(photo.id));

  useEffect(() => {
    if (activeGroup && activeGroup.id !== activeGroupId) setActiveGroupId(activeGroup.id);
  }, [activeGroup, activeGroupId]);

  const updateLocalStatus = useCallback((ids: string[], status: ReviewStatus) => {
    const idSet = new Set(ids);
    setGroups((current) => current.map((group) => {
      const nextPhotos = group.photos.map((photo) => idSet.has(photo.id) ? { ...photo, status } : photo);
      return {
        ...group,
        photos: nextPhotos,
        reviewed: nextPhotos.every((photo) => photo.status !== "pending"),
        kept_count: nextPhotos.filter((photo) => photo.status === "kept").length,
      };
    }));
    setSelected((current) => {
      const next = new Set(current);
      ids.forEach((id) => next.delete(id));
      return next;
    });
  }, []);

  const review = useCallback(async (ids: string[], status: ReviewStatus) => {
    if (!ids.length) return;
    setBusy(true);
    try {
      if (!demoMode) await engine.review(ids.map((id) => ({ id, status })));
      updateLocalStatus(ids, status);
      setNotice(status === "kept" ? `已保留 ${ids.length} 张照片` : `已排除 ${ids.length} 张照片`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }, [demoMode, updateLocalStatus]);

  const pollJob = useCallback(async (jobId: string) => {
    for (;;) {
      const snapshot = await engine.job(jobId);
      setJob(snapshot);
      if (snapshot.state === "completed") {
        const nextGroups = snapshot.groups || [];
        setGroups(nextGroups);
        setActiveGroupId(nextGroups.find((group) => !preferences.hideSingletons || group.count > 1)?.id || null);
        setSelected(new Set());
        setNotice(`已整理 ${nextGroups.reduce((sum, group) => sum + group.count, 0)} 张照片`);
        return;
      }
      if (snapshot.state === "failed" || snapshot.state === "cancelled") {
        if (snapshot.state === "failed") setNotice(snapshot.error || "分析失败");
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 260));
    }
  }, [preferences.hideSingletons]);

  const analyze = async (path: string) => {
    setSource(path);
    setGroups([]);
    setSelected(new Set());
    setJob({ id: "starting", state: "queued", stage: "scan", current: 0, total: 0, detail: "正在启动本地图片引擎", source: path, failure_count: 0 });
    try {
      const jobId = await engine.startAnalysis(path, preferences.options);
      await pollJob(jobId);
    } catch (error) {
      setJob(null);
      setNotice(error instanceof Error ? error.message : "无法开始分析");
    }
  };

  const chooseSource = async () => {
    if (!engine.desktopAvailable) {
      setNotice("网页预览中请使用演示照片，桌面版可以读取文件夹");
      return;
    }
    const path = await engine.chooseFolder();
    if (path) {
      setDemoMode(false);
      await analyze(path);
    }
  };

  const openDemo = async () => {
    if (!engine.desktopAvailable) {
      setDemoMode(true);
      setSource("演示照片");
      setGroups(demoGroups);
      setActiveGroupId(demoGroups[0].id);
      setJob(null);
      return;
    }
    const path = await engine.demoFolder();
    if (path) {
      setDemoMode(true);
      await analyze(path);
    }
  };

  const chooseDestination = async () => {
    const path = await engine.chooseFolder();
    if (path) {
      setDestination(path);
      localStorage.setItem("photo-fit-picker.destination", path);
      setNotice("已更新保存位置");
    }
  };

  const moveSelected = async () => {
    if (!selected.size) return;
    if (demoMode) {
      setLastMoveStatuses(new Map(selectedPhotos.map((photo) => [photo.id, photo.status])));
      updateLocalStatus([...selected], "moved");
      setNotice("演示模式：已模拟移动照片");
      return;
    }
    let target = destination;
    if (!target) {
      target = (await engine.chooseFolder()) || "";
      if (!target) return;
      setDestination(target);
      localStorage.setItem("photo-fit-picker.destination", target);
    }
    setBusy(true);
    try {
      setLastMoveStatuses(new Map(selectedPhotos.map((photo) => [photo.id, photo.status])));
      await engine.move([...selected], target);
      updateLocalStatus([...selected], "moved");
      setNotice("照片已移动，可在文件夹设置中查看目标位置");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "移动失败");
    } finally {
      setBusy(false);
    }
  };

  const undoMove = async () => {
    if (!lastMoveStatuses || (!demoMode && !destination)) return;
    setBusy(true);
    try {
      if (!demoMode) await engine.undo(destination);
      setGroups((current) => current.map((group) => {
        const nextPhotos = group.photos.map((photo) => {
          const previous = lastMoveStatuses.get(photo.id);
          return previous ? { ...photo, status: previous } : photo;
        });
        return {
          ...group,
          photos: nextPhotos,
          reviewed: nextPhotos.every((photo) => photo.status !== "pending"),
          kept_count: nextPhotos.filter((photo) => photo.status === "kept").length,
        };
      }));
      setLastMoveStatuses(null);
      setNotice("已撤销最近一次移动");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "撤销移动失败");
    } finally {
      setBusy(false);
    }
  };

  const trashSelected = async () => {
    setConfirmAction(null);
    const ids = [...selected];
    if (!ids.length) return;
    setBusy(true);
    try {
      if (!demoMode) await engine.trash(ids);
      updateLocalStatus(ids, "trashed");
      setNotice(demoMode ? "演示模式：已模拟移到回收站" : `已将 ${ids.length} 张照片移到系统回收站`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "回收站操作失败");
    } finally {
      setBusy(false);
    }
  };

  const restart = async () => {
    setConfirmAction(null);
    const allIds = groups.flatMap((group) => group.photos)
      .filter((photo) => photo.status === "pending" || photo.status === "kept" || photo.status === "rejected")
      .map((photo) => photo.id);
    setBusy(true);
    try {
      if (!demoMode) await engine.review(allIds.map((id) => ({ id, status: "pending" })));
      updateLocalStatus(allIds, "pending");
      setActiveGroupId(visibleGroups[0]?.id || null);
      setNotice("已开始新一轮筛选，分析缓存会继续复用");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "无法开始新一轮");
    } finally {
      setBusy(false);
    }
  };

  const keepBestAndNext = async () => {
    if (!activeGroup) return;
    const recommended = activeGroup.photos.find((photo) => photo.recommended);
    if (!recommended) return;
    const updates = activeGroup.photos.map((photo) => ({ id: photo.id, status: photo.id === recommended.id ? "kept" as ReviewStatus : "rejected" as ReviewStatus }));
    setBusy(true);
    try {
      if (!demoMode) await engine.review(updates);
      updateLocalStatus([recommended.id], "kept");
      updateLocalStatus(updates.filter((item) => item.id !== recommended.id).map((item) => item.id), "rejected");
      const index = visibleGroups.findIndex((group) => group.id === activeGroup.id);
      const next = visibleGroups[index + 1];
      if (next) setActiveGroupId(next.id);
      setNotice("已保留推荐照片并完成本组");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (page !== "photos" || detail || !activeGroup) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "a") {
        event.preventDefault();
        setSelected((current) => {
          const next = new Set(current);
          activeGroup.photos.forEach((photo) => next.add(photo.id));
          return next;
        });
      }
      if (event.key === "Escape") setSelected(new Set());
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeGroup, detail, page]);

  if (page === "settings") {
    return <SettingsPage preferences={preferences} destination={destination} section={settingsSection} onSection={setSettingsSection} onChange={setPreferences} onDestination={chooseDestination} onClose={() => setPage("photos")} />;
  }

  const progress = job && job.total ? Math.round((job.current / job.total) * 100) : 0;
  const sorting: Array<{ value: SortMode; label: string; icon: ReactNode }> = [
    { value: "recommended", label: "推荐", icon: <Sparkles size={15} /> },
    { value: "time", label: "时间", icon: <Clock3 size={15} /> },
    { value: "size", label: "大小", icon: <HardDrive size={15} /> },
  ];

  return (
    <div className="app-shell">
      <aside className="main-sidebar">
        <div className="window-drag" data-tauri-drag-region />
        <div className="brand"><span className="brand-mark"><ImageIcon size={19} /></span><strong>拾影</strong></div>
        <button className="source-button" type="button" onClick={chooseSource}><FolderOpen size={17} /><span>打开照片文件夹</span></button>
        <div className="sidebar-heading"><span>相似照片</span>{groups.length > 0 && <small>{visibleGroups.length} 组</small>}</div>
        <nav className="group-list">
          {visibleGroups.map((group, index) => {
            const preview = group.photos.find((photo) => photo.recommended) || group.photos[0];
            return (
              <button key={group.id} type="button" className={activeGroup?.id === group.id ? "is-active" : ""} onClick={() => setActiveGroupId(group.id)}>
                <span className="group-thumb"><Thumbnail photo={preview} maximum={240} /></span>
                <span className="group-copy"><strong>照片组 {String(index + 1).padStart(2, "0")}</strong><small>{group.count} 张 · {group.reviewed ? "已完成" : "待筛选"}</small></span>
                {group.reviewed ? <CheckCircle2 className="group-done" size={17} /> : <ChevronRight size={16} />}
              </button>
            );
          })}
          {!groups.length && <p className="sidebar-empty">导入照片后，相似连拍会出现在这里。</p>}
        </nav>
        <div className="sidebar-footer">
          {groups.length > 0 && <div className="review-progress"><div><span>本轮进度</span><strong>{reviewed} / {total}</strong></div><progress value={reviewed} max={Math.max(1, total)} /></div>}
          <button type="button" onClick={() => setPage("settings")}><Settings size={18} /><span>设置</span></button>
        </div>
      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div className="workspace-title">
            <span className="eyebrow">{source || "本地照片"}</span>
            <h1>{activeGroup ? `照片组 ${String(visibleGroups.indexOf(activeGroup) + 1).padStart(2, "0")}` : "照片筛选"}</h1>
          </div>
          {groups.length > 0 && (
            <div className="header-actions">
              <Segmented<SortMode> label="照片排序" value={preferences.sortMode} onChange={(sortMode) => setPreferences({ ...preferences, sortMode })} options={sorting} />
              <div className="toolbar-divider" />
              <div className="view-tools">
                <IconButton label="小图" active={preferences.viewMode === "compact"} onClick={() => setPreferences({ ...preferences, viewMode: "compact" })}><Grid2X2 size={18} /></IconButton>
                <IconButton label="大图" active={preferences.viewMode === "large"} onClick={() => setPreferences({ ...preferences, viewMode: "large" })}><Rows3 size={18} /></IconButton>
                <IconButton label="列表" active={preferences.viewMode === "list"} onClick={() => setPreferences({ ...preferences, viewMode: "list" })}><List size={19} /></IconButton>
                {preferences.viewMode !== "list" && <input className="size-slider" aria-label="缩略图大小" type="range" min="150" max="330" value={preferences.thumbnailSize} onChange={(event) => setPreferences({ ...preferences, thumbnailSize: Number(event.target.value) })} />}
              </div>
              {lastMoveStatuses && (demoMode || destination) && <IconButton label="撤销最近一次移动" disabled={busy} onClick={undoMove}><Undo2 size={18} /></IconButton>}
              <IconButton label="开始新一轮" onClick={() => setConfirmAction("restart")}><RotateCcw size={18} /></IconButton>
            </div>
          )}
        </header>

        {job && (job.state === "queued" || job.state === "running") ? (
          <section className="analysis-state">
            <div className="analysis-symbol"><ArrowUpDown size={28} /></div>
            <span className="eyebrow">本地分析</span><h2>{job.detail}</h2>
            <p>{job.total ? `${job.current} / ${job.total}` : "正在准备图片读取器"}</p>
            <div className="large-progress"><span style={{ width: `${Math.max(4, progress)}%` }} /></div>
            <button className="button secondary" type="button" onClick={() => job.id !== "starting" && engine.cancel(job.id)}><Square size={15} />取消</button>
          </section>
        ) : activeGroup ? (
          <>
            <div className="group-summary">
              <p><strong>{activeGroup.count} 张相似照片</strong><span>推荐依据：清晰度、曝光与照片尺寸</span></p>
              <button className="button primary subtle" type="button" disabled={busy} onClick={keepBestAndNext}><Sparkles size={16} />保留推荐并继续</button>
            </div>
            <VirtualPhotoView photos={photos} mode={preferences.viewMode} thumbnailSize={preferences.viewMode === "large" ? Math.max(280, preferences.thumbnailSize) : preferences.thumbnailSize} selected={selected} onToggle={(id) => setSelected((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next; })} onOpen={setDetail} />
          </>
        ) : (
          <section className="welcome-state">
            <div className="welcome-visual"><Images size={34} /></div>
            <span className="eyebrow">在电脑上完成</span>
            <h2>从一千张里，留下真正想看的</h2>
            <p>选择一个照片文件夹，拾影会把连拍与相似画面归在一起。分析结果只保存在本机。</p>
            <div className="welcome-actions"><button className="button primary" type="button" onClick={chooseSource}><FolderOpen size={18} />选择照片文件夹</button><button className="button secondary" type="button" onClick={openDemo}><Play size={17} />试用演示照片</button></div>
            <div className="format-line">JPG · HEIC · PNG · TIFF · Nikon NEF · Canon CR3 · Sony ARW · DNG</div>
          </section>
        )}
      </main>

      {selected.size > 0 && (
        <div className="batch-bar">
          <div className="batch-count"><span>{selected.size}</span><strong>张已选择</strong><small>{selectedPhotos.reduce((sum, photo) => sum + photo.file_size, 0) > 0 ? `${(selectedPhotos.reduce((sum, photo) => sum + photo.file_size, 0) / 1024 / 1024).toFixed(1)} MB` : ""}</small></div>
          <div className="batch-actions">
            <button type="button" disabled={busy} onClick={() => review([...selected], "kept")}><Check size={17} />保留</button>
            <button type="button" disabled={busy} onClick={() => review([...selected], "rejected")}><X size={17} />排除</button>
            <span />
            <button type="button" disabled={busy} onClick={moveSelected}><MoveRight size={17} />移动</button>
            <button className="danger-action" type="button" disabled={busy} onClick={() => setConfirmAction("trash")}><Trash2 size={17} />回收站</button>
          </div>
          <IconButton label="清空选择" onClick={() => setSelected(new Set())}><X size={18} /></IconButton>
        </div>
      )}

      {detail && <DetailViewer photo={detail} photos={photos} onClose={() => setDetail(null)} onNavigate={setDetail} onReview={(status) => { review([detail.id], status); setDetail(null); }} />}

      {confirmAction && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setConfirmAction(null)}>
          <div className="confirm-dialog" role="alertdialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <span className={`dialog-icon${confirmAction === "trash" ? " is-danger" : ""}`}>{confirmAction === "trash" ? <Trash2 size={22} /> : <RotateCcw size={22} />}</span>
            <h2>{confirmAction === "trash" ? `将 ${selected.size} 张照片移到回收站？` : "开始新一轮筛选？"}</h2>
            <p>{confirmAction === "trash" ? "照片会进入系统回收站，拾影不会永久删除文件。你可以之后从系统回收站恢复。" : "所有保留和排除标记会恢复为待筛选。照片文件与分析缓存不会改变。"}</p>
            <div className="dialog-actions"><button className="button secondary" type="button" onClick={() => setConfirmAction(null)}>取消</button><button className={`button ${confirmAction === "trash" ? "danger" : "primary"}`} type="button" onClick={confirmAction === "trash" ? trashSelected : restart}>{confirmAction === "trash" ? "移到回收站" : "开始新一轮"}</button></div>
          </div>
        </div>
      )}
      {notice && <div className="toast"><CheckCircle2 size={17} /><span>{notice}</span></div>}
    </div>
  );
}

export default App;
