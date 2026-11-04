import type { Round } from "./api";
import type { ChartPoint } from "./rounds";
import { chartPoints } from "./rounds";

const WIDTH = 320;
const HEIGHT = 170;
const PAD = { top: 16, right: 16, bottom: 30, left: 44 };

/** The held-out accuracy and grade of each version tried, a chart for each. */
export function VersionChart({ rounds }: Readonly<{ rounds: Round[] }>) {
  const points = chartPoints(rounds);
  if (points.length === 0) {
    return (
      <p className="muted">
        No version has been tried yet. The chart fills in as rounds finish.
      </p>
    );
  }
  return (
    <div className="charts">
      <Measure
        title="Held-out accuracy"
        points={points}
        value={(point) => point.accuracy}
        top={1}
        format={(value) => `${String(Math.round(value * 100))}%`}
      />
      <Measure
        title="Held-out grade"
        points={points}
        value={(point) => point.grade}
        top={3}
        format={(value) => value.toFixed(2)}
      />
    </div>
  );
}

function Measure({
  title,
  points,
  value,
  top,
  format,
}: Readonly<{
  title: string;
  points: ChartPoint[];
  value: (point: ChartPoint) => number | null;
  top: number;
  format: (value: number) => string;
}>) {
  const inner = WIDTH - PAD.left - PAD.right;
  const tall = HEIGHT - PAD.top - PAD.bottom;
  const x = (index: number) =>
    PAD.left +
    (points.length === 1 ? inner / 2 : (index * inner) / (points.length - 1));
  const y = (amount: number) => PAD.top + tall - (amount / top) * tall;
  const plotted = points.flatMap((point, index) => {
    const amount = value(point);
    return amount === null ? [] : [{ point, index, amount }];
  });
  const path = plotted
    .map(
      ({ index, amount }, n) =>
        `${n === 0 ? "M" : "L"}${String(x(index))},${String(y(amount))}`,
    )
    .join(" ");

  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <svg
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        role="img"
        aria-label={`${title} by version: ${plotted
          .map(
            ({ point, amount }) =>
              `version ${String(point.version)} ${format(amount)}`,
          )
          .join(", ")}`}
      >
        {[0, top / 2, top].map((tick) => (
          <g key={tick}>
            <line
              className="chart-grid"
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text
              className="chart-axis"
              x={PAD.left - 8}
              y={y(tick) + 4}
              textAnchor="end"
            >
              {format(tick)}
            </text>
          </g>
        ))}
        {points.map((point, index) => (
          <text
            key={point.version}
            className="chart-axis"
            x={x(index)}
            y={HEIGHT - 8}
            textAnchor="middle"
          >
            v{point.version}
          </text>
        ))}
        <path className="chart-line" d={path} />
        {plotted.map(({ point, index, amount }) => (
          <circle
            key={point.version}
            className={`chart-point ${point.kept === false ? "rolled-back" : ""}`}
            cx={x(index)}
            cy={y(amount)}
            r={5}
            data-version={point.version}
          >
            <title>
              {`Version ${String(point.version)}: ${format(amount)}${fate(point)}`}
            </title>
          </circle>
        ))}
      </svg>
    </figure>
  );
}

/** What became of a version: before the rounds, kept or rolled back. */
function fate(point: ChartPoint): string {
  if (point.kept === null) return ", before the rounds";
  return point.kept ? ", kept" : ", rolled back";
}
