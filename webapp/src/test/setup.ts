import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom implements neither of these. The PDF reader measures its shell with a
// ResizeObserver to fit page width, and touches the 2D context before handing the
// canvas to the (mocked) pdf.js engine.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(window, "ResizeObserver", {
  writable: true,
  value: ResizeObserverStub,
});

HTMLCanvasElement.prototype.getContext = (() => ({
  canvas: null,
  save() {}, restore() {}, scale() {}, translate() {}, setTransform() {},
  clearRect() {}, fillRect() {}, drawImage() {}, beginPath() {}, fill() {},
  measureText: () => ({ width: 0 }),
})) as unknown as HTMLCanvasElement["getContext"];

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
