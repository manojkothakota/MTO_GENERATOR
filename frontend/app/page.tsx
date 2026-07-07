"use client";

import { useCallback, useRef, useState } from "react";
import type { MTOResult, JobResponse } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const MAX_SIZE = 20 * 1024 * 1024;
const ALLOWED_TYPES = ["image/png", "image/jpeg", "application/pdf"];

type Stage = "idle" | "uploading" | "processing" | "done" | "error";

export default function Page() {
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [fileType, setFileType] = useState<string>("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<MTOResult | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setStage("idle");
    setError(null);
    setPreview(null);
    setJobId(null);
    setResult(null);
  };

  const validate = (file: File): string | null => {
    if (!ALLOWED_TYPES.includes(file.type)) {
      return `Unsupported file type "${file.type || "unknown"}". Please upload PNG, JPG, or PDF.`;
    }
    if (file.size > MAX_SIZE) {
      return `File too large (${(file.size / 1_000_000).toFixed(1)} MB). Max 20 MB.`;
    }
    return null;
  };

  const handleFile = useCallback(async (file: File) => {
    const validationError = validate(file);
    if (validationError) {
      setError(validationError);
      setStage("error");
      return;
    }

    setError(null);
    setFileType(file.type);
    if (file.type !== "application/pdf") {
      setPreview(URL.createObjectURL(file));
    } else {
      setPreview(null);
    }

    setStage("uploading");
    try {
      const formData = new FormData();
      formData.append("file", file);

      const uploadRes = await fetch(`${API_URL}/api/upload`, {
        method: "POST",
        body: formData,
      });

      if (!uploadRes.ok) {
        const body = await uploadRes.json().catch(() => ({}));
        throw new Error(body.detail || `Upload failed (${uploadRes.status})`);
      }

      const { job_id } = await uploadRes.json();
      setJobId(job_id);
      setStage("processing");

      const mtoRes = await fetch(`${API_URL}/api/mto/${job_id}`);
      if (!mtoRes.ok) {
        const body = await mtoRes.json().catch(() => ({}));
        throw new Error(body.detail || body.error || `Processing failed (${mtoRes.status})`);
      }
      const job: JobResponse = await mtoRes.json();
      if (job.status === "error" || !job.result) {
        throw new Error("Processing failed on the server.");
      }
      setResult(job.result);
      setStage("done");
    } catch (err: any) {
      setError(err.message || "Something went wrong.");
      setStage("error");
    }
  }, []);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <main className="max-w-5xl mx-auto px-6 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold">Isometric &rarr; MTO Generator</h1>
        <p className="text-slate-500 mt-1">
          Upload one piping isometric drawing (PNG, JPG, or PDF). The backend AI pipeline
          extracts a structured Material Take-Off.
        </p>
      </header>

      {(stage === "idle" || stage === "error") && (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-14 text-center cursor-pointer transition-colors
            ${dragOver ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-white"}`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".png,.jpg,.jpeg,.pdf"
            className="hidden"
            onChange={onPick}
          />
          <p className="text-slate-600">
            Drag &amp; drop your isometric here, or <span className="text-indigo-600 underline">browse</span>
          </p>
          <p className="text-slate-400 text-sm mt-2">PNG, JPG, or PDF · max 20 MB</p>
        </div>
      )}

      {stage === "error" && error && (
        <div className="mt-4 border border-red-300 bg-red-50 text-red-700 rounded-lg p-4">
          <strong>Couldn&apos;t process this file.</strong> {error}
        </div>
      )}

      {(stage === "uploading" || stage === "processing") && (
        <div className="border rounded-xl p-14 text-center bg-white">
          <div className="animate-spin h-8 w-8 border-4 border-indigo-500 border-t-transparent rounded-full mx-auto mb-4" />
          <p className="text-slate-600">
            {stage === "uploading" ? "Uploading drawing…" : "Running AI extraction pipeline…"}
          </p>
        </div>
      )}

      {stage === "done" && result && (
        <ResultsView
          result={result}
          preview={preview}
          fileType={fileType}
          jobId={jobId!}
          apiUrl={API_URL}
          onReset={reset}
        />
      )}
    </main>
  );
}

function ResultsView({
  result, preview, fileType, jobId, apiUrl, onReset,
}: {
  result: MTOResult;
  preview: string | null;
  fileType: string;
  jobId: string;
  apiUrl: string;
  onReset: () => void;
}) {
  const { drawing_meta, items, summary, mode, warnings } = result;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <span
          className={`text-xs font-medium px-2.5 py-1 rounded-full ${
            mode === "mock" ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700"
          }`}
        >
          {mode === "mock" ? "MOCK MTO — no AI provider configured" : `Extracted with ${mode[0].toUpperCase()}${mode.slice(1)}`}
        </span>
        <button onClick={onReset} className="text-sm text-indigo-600 underline">
          Upload another drawing
        </button>
      </div>

      {warnings.length > 0 && (
        <div className="mb-4 border border-amber-300 bg-amber-50 text-amber-800 rounded-lg p-3 text-sm">
          {warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-6 mb-6">
        <div className="bg-white border rounded-xl p-4">
          <h2 className="font-medium mb-2">Drawing preview</h2>
          {preview ? (
            <img src={preview} alt="Uploaded isometric" className="rounded-lg border max-h-80 object-contain mx-auto" />
          ) : fileType === "application/pdf" ? (
            <p className="text-slate-400 text-sm">PDF uploaded — preview not rendered client-side.</p>
          ) : null}
        </div>

        <div className="bg-white border rounded-xl p-4">
          <h2 className="font-medium mb-2">Drawing metadata</h2>
          <dl className="text-sm grid grid-cols-2 gap-y-1">
            <dt className="text-slate-500">Drawing No.</dt><dd>{drawing_meta.drawing_no ?? "—"}</dd>
            <dt className="text-slate-500">Revision</dt><dd>{drawing_meta.revision ?? "—"}</dd>
            <dt className="text-slate-500">Line Number</dt><dd>{drawing_meta.line_number ?? "—"}</dd>
            <dt className="text-slate-500">NPS</dt><dd>{drawing_meta.nps ?? "—"}</dd>
            <dt className="text-slate-500">Material Class</dt><dd>{drawing_meta.material_class ?? "—"}</dd>
            <dt className="text-slate-500">Service</dt><dd>{drawing_meta.service ?? "—"}</dd>
          </dl>
        </div>
      </div>

      <div className="grid grid-cols-3 md:grid-cols-6 gap-3 mb-6">
        <Chip label="Pipe length" value={`${summary.total_pipe_length_m} m`} />
        <Chip label="Fittings" value={summary.fittings} />
        <Chip label="Flanges" value={summary.flanges} />
        <Chip label="Valves" value={summary.valves} />
        <Chip label="Gaskets" value={summary.gaskets} />
        <Chip label="Bolt sets" value={summary.bolt_sets} />
      </div>

      <div className="bg-white border rounded-xl overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="font-medium">Material Take-Off</h2>
          <a
            href={`${apiUrl}/api/mto/${jobId}/csv`}
            className="text-sm bg-indigo-600 text-white px-3 py-1.5 rounded-lg hover:bg-indigo-700"
          >
            Export CSV
          </a>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 text-left">
              <tr>
                {["#", "Category", "Description", "Size", "Sched/Class", "Material", "End", "Qty", "Unit", "Length (m)", "Conf."].map((h) => (
                  <th key={h} className="px-3 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.item_no} className="border-t">
                  <td className="px-3 py-2">{item.item_no}</td>
                  <td className="px-3 py-2">{item.category}</td>
                  <td className="px-3 py-2">{item.description}</td>
                  <td className="px-3 py-2">{item.size_nps ?? "—"}</td>
                  <td className="px-3 py-2">{item.schedule_rating ?? "—"}</td>
                  <td className="px-3 py-2">{item.material_spec ?? "—"}</td>
                  <td className="px-3 py-2">{item.end_type ?? "—"}</td>
                  <td className="px-3 py-2">{item.quantity}</td>
                  <td className="px-3 py-2">{item.unit}</td>
                  <td className="px-3 py-2">{item.length_m ?? "—"}</td>
                  <td className="px-3 py-2">
                    {item.confidence != null ? (
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs ${
                          item.confidence > 0.85
                            ? "bg-emerald-100 text-emerald-700"
                            : item.confidence > 0.6
                            ? "bg-amber-100 text-amber-700"
                            : "bg-red-100 text-red-700"
                        }`}
                      >
                        {Math.round(item.confidence * 100)}%
                      </span>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Chip({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white border rounded-xl p-3 text-center">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}
