import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "./App";
import { createLoader } from "./data/loader";
import { fakeFetch, makeSnapshot } from "./test/snapshot";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(files: Record<string, unknown>) {
  const loader = createLoader("/data", fakeFetch(files).fetchImpl);
  await act(async () => {
    root.render(<App loader={loader} />);
  });
}

const rows = () => Array.from(container.querySelectorAll("tbody tr")).map((tr) => tr.querySelector("th")?.textContent);

describe("App", () => {
  it("lists the laboratories from the snapshot", async () => {
    await render(makeSnapshot());
    expect(rows()).toEqual(["AAA", "BBB", "CCC"]);
    expect(container.textContent).toContain("Alpha Institute");
    expect(container.textContent).toContain("Showing 3 of 3 laboratories");
  });

  it("shows the snapshot's own figures and attribution, not constants", async () => {
    await render(makeSnapshot());
    const text = container.textContent ?? "";
    expect(text).toContain("465"); // latest Circular T
    expect(text).toContain("2026-11-09"); // when the data last changed
    expect(text).toContain("2 of 3"); // labs with data
    expect(text).toContain("1 labs after 2026-09-26"); // provisional rapid values
    expect(text).toContain("Not affiliated with or endorsed by BIPM");
  });

  it("marks a lab with no data and shows a former lab's status", async () => {
    await render(makeSnapshot());
    const ccc = Array.from(container.querySelectorAll("tbody tr")).find((tr) => tr.textContent?.startsWith("CCC"));
    expect(ccc?.textContent).toContain("former");
    expect(ccc?.textContent).toContain("none");
  });

  it("filters by code, name, city or country", async () => {
    await render(makeSnapshot());
    const input = container.querySelector("input") as HTMLInputElement;
    const type = async (value: string) => {
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
        setter.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    };
    await type("betaburg");
    expect(rows()).toEqual(["BBB", "CCC"]);
    expect(container.textContent).toContain("Showing 2 of 3 laboratories");
    await type("gamma");
    expect(rows()).toEqual(["CCC"]);
    await type("");
    expect(rows()).toEqual(["AAA", "BBB", "CCC"]);
  });

  it("says what went wrong when the data cannot be loaded", async () => {
    const files = makeSnapshot();
    delete files["labs.json"];
    await render(files);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("labs.json: HTTP 404");
    expect(rows()).toEqual([]);
  });
});
