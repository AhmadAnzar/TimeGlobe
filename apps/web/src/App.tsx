import { useEffect, useMemo, useState } from "react";
import { mjdToIso } from "./data/dates";
import { createLoader, type CoreData, type Loader } from "./data/loader";
import { GlobeView } from "./globe/GlobeView";

const defaultLoader = createLoader();

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; core: CoreData };

/** showGlobe is false in tests: they run without WebGL. */
export default function App({ loader = defaultLoader, showGlobe = true }: { loader?: Loader; showGlobe?: boolean }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    loader
      .loadCore()
      .then((core) => {
        if (!cancelled) setState({ status: "ready", core });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [loader]);

  return (
    <main>
      <h1>Time Globe</h1>
      <p className="lede">The world's timekeeping laboratories and how far each one's clock drifts from UTC.</p>
      {state.status === "loading" && <p role="status">Loading the snapshot…</p>}
      {state.status === "error" && (
        <p role="alert" className="error">
          Could not load the data: {state.message}
        </p>
      )}
      {state.status === "ready" && <Snapshot core={state.core} showGlobe={showGlobe} />}
    </main>
  );
}

function Snapshot({ core, showGlobe }: { core: CoreData; showGlobe: boolean }) {
  const { meta, labs, rapid } = core;
  const [filter, setFilter] = useState("");

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return labs.labs;
    return labs.labs.filter((lab) =>
      [lab.code, lab.name, lab.city, lab.country].some((field) => field.toLowerCase().includes(needle)),
    );
  }, [labs.labs, filter]);

  return (
    <>
      {showGlobe && <GlobeView labs={labs} />}

      <dl className="summary">
        <div>
          <dt>Latest Circular T</dt>
          <dd>{meta.circular_t_latest}</dd>
        </div>
        <div>
          <dt>Data last changed</dt>
          <dd>{meta.generated_at}</dd>
        </div>
        <div>
          <dt>Laboratories with data</dt>
          <dd>
            {meta.labs_with_data} of {meta.labs}
          </dd>
        </div>
        <div>
          <dt>Drift values</dt>
          <dd>{meta.values.toLocaleString("en-US")}</dd>
        </div>
        <div>
          <dt>Clocks (not marked stopped)</dt>
          <dd>{meta.clocks.total}</dd>
        </div>
        <div>
          <dt>Provisional rapid values</dt>
          <dd>
            {rapid.labs.length > 0 ? `${meta.rapid.labs} labs after ${mjdToIso(rapid.after_mjd)}` : "none"}
          </dd>
        </div>
      </dl>

      <label className="filter">
        Filter laboratories
        <input type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="code, name, city or country" />
      </label>
      <p role="status" className="count">
        Showing {shown.length} of {labs.labs.length} laboratories
      </p>

      <table>
        <caption>Laboratories in the snapshot</caption>
        <thead>
          <tr>
            <th scope="col">Code</th>
            <th scope="col">Name</th>
            <th scope="col">City</th>
            <th scope="col">Country</th>
            <th scope="col">Status</th>
            <th scope="col" className="num">
              Clocks
            </th>
            <th scope="col">Drift data</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((lab) => (
            <tr key={lab.code}>
              <th scope="row">{lab.code}</th>
              <td>{lab.name}</td>
              <td>{lab.city}</td>
              <td>{lab.country}</td>
              <td>{lab.status.replace("_", " ")}</td>
              <td className="num">{lab.clocks}</td>
              <td>{lab.has_data ? "yes" : "none"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <footer>
        <p>{meta.attribution}</p>
      </footer>
    </>
  );
}
