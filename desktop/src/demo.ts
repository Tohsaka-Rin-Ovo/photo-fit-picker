import type { Photo, PhotoGroup } from "./types";

const baseMetadata = {
  captured_at: null,
  make: "Nikon",
  model: "NIKON Z 6_2",
  lens: "NIKKOR Z 24-70mm f/4 S",
  exposure_time: 1 / 250,
  aperture: 5.6,
  iso: 100,
  focal_length: 35,
  exposure_bias: 0,
  white_balance: "Auto",
  focus_mode: "AF-S",
  metering_mode: "Matrix",
  exposure_program: "Aperture priority",
  flash: "Off",
  software: "",
  latitude: null,
  longitude: null,
  details: [],
  camera_label: "Nikon Z 6 II",
  shooting_summary: "1/250 秒  ·  f/5.6  ·  ISO 100  ·  35 mm",
};

const files = [
  ["02_lake_bright.jpg", 1, 61200, 0.94],
  ["01_lake_clear.jpg", 1, 55300, 0.89],
  ["03_lake_soft.jpg", 1, 49200, 0.67],
  ["04_street_clear.jpg", 2, 68400, 0.93],
  ["05_street_step.jpg", 2, 64100, 0.82],
  ["06_street_dark.jpg", 2, 57800, 0.61],
  ["07_coast_clear.jpg", 3, 72300, 0.92],
  ["08_coast_shift.jpg", 3, 70100, 0.83],
  ["09_coast_soft.jpg", 3, 62600, 0.66],
  ["10_forest.jpg", 4, 81300, 0.88],
  ["11_abstract.jpg", 5, 44800, 0.79],
] as const;

const photos = files.map(([name, group, size, quality], index): Photo => ({
  id: `demo-${index + 1}`,
  path: `/demo-photos/${name}`,
  name,
  format: "JPG",
  width: 1200,
  height: 800,
  dimensions: "1200 × 800",
  file_size: size,
  file_size_label: `${(size / 1000).toFixed(1)} KB`,
  captured_at: `2026-05-18T09:${String(30 + group).padStart(2, "0")}:0${index}`,
  quality_score: quality,
  quality_summary: quality > 0.85 ? "清晰 · 曝光均衡" : "清晰度尚可 · 曝光均衡",
  portrait_detected: index === 3 || index === 4,
  status: "pending",
  recommended: index === 0 || index === 3 || index === 6 || index === 9 || index === 10,
  recommendation_reason: quality > 0.9 ? "本组清晰度与曝光综合得分最高" : "可与本组推荐照片对比",
  metadata: { ...baseMetadata, captured_at: `2026-05-18T09:${30 + group}:00` },
  image_url: `/${name}`,
}));

export const demoGroups: PhotoGroup[] = [1, 2, 3, 4, 5].map((id) => {
  const groupPhotos = photos.filter((photo) => {
    const index = photos.indexOf(photo);
    return files[index][1] === id;
  });
  return {
    id,
    count: groupPhotos.length,
    reviewed: false,
    kept_count: 0,
    photos: groupPhotos,
  };
});
