"use client";

import type { RadarItem } from "@/lib/types";

/**
 * 纯 SVG 雷达图：零图表库依赖，双环对比「候选人得分 vs 岗位基准」。
 * 只负责画，所有数值由后端 MatchReport.radar 提供（固定 6 维）。
 */
export function RadarChart({
  items,
  size = 300,
  className,
}: {
  items: RadarItem[];
  size?: number;
  className?: string;
}) {
  const n = Math.max(3, items.length);
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 52;

  const angle = (i: number) => ((-90 + (i * 360) / n) * Math.PI) / 180;
  const point = (i: number, value: number) => {
    const r = (radius * Math.max(0, Math.min(100, value))) / 100;
    return [cx + r * Math.cos(angle(i)), cy + r * Math.sin(angle(i))] as const;
  };

  const polygon = (getter: (item: RadarItem) => number) =>
    items
      .map((item, i) => {
        const [x, y] = point(i, getter(item));
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      width="100%"
      height={size}
      className={className}
      role="img"
      aria-label="匹配度雷达图"
    >
      {/* 网格环 */}
      {[25, 50, 75, 100].map((level) => (
        <polygon
          key={level}
          points={items.map((_, i) => {
            const [x, y] = point(i, level);
            return `${x.toFixed(1)},${y.toFixed(1)}`;
          }).join(" ")}
          fill="none"
          stroke={level === 100 ? "#e2e8f0" : "#eef1f5"}
          strokeWidth={1}
        />
      ))}

      {/* 轴线 */}
      {items.map((item, i) => {
        const [x, y] = point(i, 100);
        return (
          <line
            key={`axis-${item.dimension}`}
            x1={cx}
            y1={cy}
            x2={x}
            y2={y}
            stroke="#eef1f5"
            strokeWidth={1}
          />
        );
      })}

      {/* 岗位基准（虚线） */}
      <polygon
        points={polygon((i) => i.benchmark || 0)}
        fill="none"
        stroke="#cbd5e1"
        strokeWidth={1.5}
        strokeDasharray="4 3"
      />

      {/* 候选人得分 */}
      <polygon
        points={polygon((i) => i.score)}
        fill="rgba(31,159,137,.18)"
        stroke="#1f9f89"
        strokeWidth={2}
        strokeLinejoin="round"
      />
      {items.map((item, i) => {
        const [x, y] = point(i, item.score);
        return <circle key={`dot-${item.dimension}`} cx={x} cy={y} r={3} fill="#137f70" />;
      })}

      {/* 维度标签 */}
      {items.map((item, i) => {
        const a = angle(i);
        const lx = cx + (radius + 22) * Math.cos(a);
        const ly = cy + (radius + 22) * Math.sin(a);
        const anchor = Math.abs(Math.cos(a)) < 0.25 ? "middle" : Math.cos(a) > 0 ? "start" : "end";
        return (
          <g key={`label-${item.dimension}`}>
            <text
              x={lx}
              y={ly - 3}
              textAnchor={anchor}
              className="fill-slate-500"
              style={{ fontSize: 10.5, fontWeight: 500 }}
            >
              {item.dimension}
            </text>
            <text
              x={lx}
              y={ly + 9}
              textAnchor={anchor}
              className="fill-brand-600"
              style={{ fontSize: 10, fontWeight: 600 }}
            >
              {item.score}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
