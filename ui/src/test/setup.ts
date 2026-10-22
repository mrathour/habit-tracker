import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { charts } from "./chartRegistry";

// ECharts draws on a canvas, which jsdom lacks: every test uses the stand-in in echartMock.
// The real charts are checked by the end-to-end window tests.
vi.mock("../dashboard/EChart", () => import("./echartMock"));

// Testing Library only cleans up automatically when Vitest globals are on; they're off here.
afterEach(() => {
  cleanup();
  charts.clear();
});
