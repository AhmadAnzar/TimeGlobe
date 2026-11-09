// The shape of the static snapshot the pipeline publishes to the `data` branch (see docs/phase2-data-shapes.md).
// Values are integer tenths of a nanosecond; null always means "no data" and is never zero.

export interface Meta {
  attribution: string;
  circular_t_latest: number;
  /** Date of the last pipeline run that changed data (not the build date). */
  generated_at: string;
  mjd_first: number;
  mjd_last: number;
  labs: number;
  labs_with_data: number;
  values: number;
  years: number[];
  unit: string;
  flags: Record<string, string[]>;
  clocks: {
    definition: string;
    total: number;
    in_labs: number;
    unmapped: Record<string, number>;
  };
  rapid: { provisional: boolean; after_mjd: number; labs: number };
}

export type LabStatus = "current" | "former" | "not_in_issue";

export interface Lab {
  code: string;
  name: string;
  city: string;
  /** BIPM's own wording, verbatim. */
  country: string;
  iso2: string;
  lat: number;
  lon: number;
  year_start: number | null;
  year_stop: number | null;
  status: LabStatus;
  clocks: number;
  /** Index into LabsFile.sites. */
  site: number;
  has_data: boolean;
}

export interface Site {
  id: number;
  lat: number;
  lon: number;
  city: string;
  country: string;
  labs: string[];
}

export interface LabsFile {
  labs: Lab[];
  sites: Site[];
}

/** One row per date, one column per lab (same order as LabsFile.labs). */
export interface Frame {
  year: number;
  labs: string[];
  mjd: number[];
  v: (number | null)[][];
}

/** The provisional rapid days after the latest Circular T date, in the same layout as a Frame. */
export interface RapidFile {
  provisional: boolean;
  after_mjd: number;
  labs: string[];
  mjd: number[];
  v: (number | null)[][];
}

export interface Cluster {
  lat: number;
  lon: number;
  labs: string[];
  /** Site ids (LabsFile.sites) the cluster merges. */
  sites: number[];
}

export interface ClusterBucket {
  altitude: number;
  radius_km: number;
  min_altitude: number;
  max_altitude: number | null;
  clusters: Cluster[];
}

export interface ClustersFile {
  unit: string;
  cap_km: number;
  buckets: ClusterBucket[];
}

export interface LabDetail {
  code: string;
  source: "api" | "circular_t";
  mjd: number[];
  v: number[];
  u: (number | null)[];
  rapid?: { mjd: number[]; v: number[]; u: (number | null)[]; provisional: boolean };
}
