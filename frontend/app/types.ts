export type Category =
  | "PIPE" | "FITTING" | "FLANGE" | "VALVE" | "GASKET" | "BOLT" | "SUPPORT";

export interface MTOItem {
  item_no: number;
  category: Category;
  description: string;
  size_nps: string | null;
  schedule_rating: string | null;
  material_spec: string | null;
  end_type: string | null;
  quantity: number;
  unit: "M" | "EA" | "NO" | "SET";
  length_m: number | null;
  confidence: number | null;
  remarks: string | null;
}

export interface DrawingMeta {
  drawing_no: string | null;
  revision: string | null;
  line_number: string | null;
  nps: string | null;
  material_class: string | null;
  service: string | null;
}

export interface Summary {
  total_pipe_length_m: number;
  fittings: number;
  flanges: number;
  valves: number;
  gaskets: number;
  bolt_sets: number;
  field_welds: number;
  supports: number;
}

export interface MTOResult {
  drawing_meta: DrawingMeta;
  items: MTOItem[];
  summary: Summary;
  mode: "mock" | "gemini" | "groq";
  warnings: string[];
}

export interface JobResponse {
  status: "processing" | "done" | "error";
  filename: string | null;
  result: MTOResult | null;
}
