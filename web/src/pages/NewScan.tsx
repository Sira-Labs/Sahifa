import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, getRouteApi, useNavigate } from "@tanstack/react-router";
import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api } from "../api";
import { StatusChip } from "../components/Chips";
import { ConnectionTest } from "../components/ConnectionTest";
import { ErrorPanel } from "../components/ErrorPanel";
import { UploadDropzone } from "../components/UploadDropzone";
import { DEFAULT_SAMPLE_ROWS } from "../constants";
import { formatBytes } from "../format";
import type { NewScanTab } from "../search";
import type { Scan } from "../types";
import { countError, fileError, mergeFiles, parseSampleRows } from "../validation";


const routeApi = getRouteApi("/scans/new");

/** Sample size field with an explicit "Read everything". Returns rows to send (0 = all). */
function useSample() {
  const [text, setText] = useState(String(DEFAULT_SAMPLE_ROWS));
  const [all, setAll] = useState(false);
  const parsed = parseSampleRows(text);
  return { text, setText, all, setAll, error: all ? null : parsed.error, value: all ? 0 : parsed.value };
}

function SampleField({ sample }: { sample: ReturnType<typeof useSample> }) {
  const id = useId();
  const errId = useId();
  return (
    <fieldset className="fieldset">
      <legend>Sample size</legend>
      <div className="sample-row">
        <label htmlFor={id} className="field-label">
          Rows per table
        </label>
        <input
          id={id}
          className="input num"
          inputMode="numeric"
          value={sample.text}
          disabled={sample.all}
          aria-invalid={sample.error ? true : undefined}
          aria-describedby={sample.error ? errId : undefined}
          onChange={(e) => sample.setText(e.target.value)}
        />
        <label className="check">
          <input type="checkbox" checked={sample.all} onChange={(e) => sample.setAll(e.target.checked)} />
          Read everything
        </label>
      </div>
      <p className="muted text-sm">
        A sample keeps large tables fast; the report&rsquo;s intervals show the uncertainty it adds. Reading everything gives
        zero-width intervals.
      </p>
      {sample.error && (
        <p id={errId} className="text-bad text-sm">
          {sample.error}
        </p>
      )}
    </fieldset>
  );
}

function UploadPanel({ onCreated }: { onCreated: (scan: Scan) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [tried, setTried] = useState(false);
  const sample = useSample();
  const upload = useMutation({ mutationFn: () => api.uploadScan(files, sample.value ?? undefined), onSuccess: onCreated });

  const errors = files.map(fileError);
  const tooMany = files.length > 0 ? countError(files.length) : null;
  const blocked = files.length === 0 || errors.some(Boolean) || tooMany !== null || sample.error !== null;

  function submit(e: FormEvent) {
    e.preventDefault();
    setTried(true);
    if (!blocked) upload.mutate();
  }

  return (
    <form onSubmit={submit} className="stack" noValidate>
      <UploadDropzone onFiles={(added) => setFiles((cur) => mergeFiles(cur, added))} disabled={upload.isPending} />
      {files.length > 0 && (
        <ul className="file-list" aria-label="Selected files">
          {files.map((file, i) => (
            <li key={`${file.name}-${file.size}`} className={errors[i] ? "has-error" : undefined}>
              <div className="min-w-0">
                <span className="file-name">{file.name}</span> <span className="num muted">{formatBytes(file.size)}</span>
                {errors[i] && <p className="text-bad text-sm">{errors[i]}</p>}
              </div>
              <button
                type="button"
                className="btn btn-small btn-quiet"
                aria-label={`Remove ${file.name}`}
                onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      {tooMany && (
        <p role="alert" className="text-bad">
          {tooMany}
        </p>
      )}
      {tried && files.length === 0 && (
        <p role="alert" className="text-bad">
          {countError(0)}
        </p>
      )}
      {tried && errors.some(Boolean) && (
        <p role="alert" className="text-bad">
          Remove the files marked above, then start the scan.
        </p>
      )}
      <SampleField sample={sample} />
      {upload.isError && <ErrorPanel title="The upload was not accepted" error={upload.error} onRetry={() => upload.mutate()} />}
      <div>
        <button type="submit" className="btn btn-primary" disabled={upload.isPending}>
          {upload.isPending ? "Uploading…" : files.length > 1 ? `Scan ${files.length} files` : "Start scan"}
        </button>
      </div>
    </form>
  );
}

function ConnectionPanel({ onCreated, initial }: { onCreated: (scan: Scan) => void; initial?: string }) {
  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });
  const [picked, setPicked] = useState<string | undefined>(initial);
  const [tried, setTried] = useState(false);
  const sample = useSample();
  const create = useMutation({
    mutationFn: (id: string) => api.createScan({ connection_id: id, sample_rows: sample.value ?? undefined }),
    onSuccess: onCreated,
  });
  const items = (connections.data?.items ?? []).filter((c) => c.kind !== "upload");

  function submit(e: FormEvent) {
    e.preventDefault();
    setTried(true);
    if (picked && !sample.error) create.mutate(picked);
  }

  if (connections.isPending) return <p role="status">Loading connections…</p>;
  if (connections.isError) {
    return <ErrorPanel title="Could not load the connections" error={connections.error} onRetry={() => void connections.refetch()} />;
  }
  if (items.length === 0) {
    return (
      <div className="card">
        <p className="font-semibold">No connections registered</p>
        <p className="muted">
          Connections come from <code>SAHIFA_CONN_&lt;NAME&gt;</code> variables on the API; see the{" "}
          <Link to="/connections">connections page</Link>. You can upload files meanwhile.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="stack" noValidate>
      <fieldset className="fieldset">
        <legend>Connection</legend>
        <ul className="conn-pick">
          {items.map((c) => (
            <li key={c.id}>
              <label className="radio">
                <input type="radio" name="connection" value={c.id} checked={picked === c.id} onChange={() => setPicked(c.id)} />
                <span>
                  <span className="font-semibold">{c.name}</span> <span className="tag">{c.kind}</span>
                </span>
                {!c.available && <StatusChip status="unavailable" />}
              </label>
              <ConnectionTest connectionId={c.id} name={c.name} />
            </li>
          ))}
        </ul>
        {tried && !picked && (
          <p role="alert" className="text-bad">
            Pick a connection to scan.
          </p>
        )}
      </fieldset>
      <SampleField sample={sample} />
      {create.isError && (
        <ErrorPanel title="The scan was not accepted" error={create.error} onRetry={() => picked && create.mutate(picked)} />
      )}
      <div>
        <button type="submit" className="btn btn-primary" disabled={create.isPending}>
          {create.isPending ? "Starting…" : "Start scan"}
        </button>
      </div>
    </form>
  );
}

const TABS: { id: NewScanTab; label: string }[] = [
  { id: "upload", label: "Upload files" },
  { id: "connection", label: "Connection" },
];

/** `/scans/new`: upload files or pick a connection; on 202 go to the report. */
export function NewScan() {
  const search = routeApi.useSearch();
  const navigate = useNavigate();
  const tab: NewScanTab = search.tab ?? "upload";
  const baseId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const onCreated = (scan: Scan) => void navigate({ to: "/scans/$scanId", params: { scanId: scan.id } });
  const select = (id: NewScanTab) => void navigate({ to: "/scans/new", search: { ...search, tab: id }, replace: true });

  function onKey(e: KeyboardEvent, index: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = (index + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
    select(TABS[next]!.id);
    tabRefs.current[next]?.focus();
  }

  return (
    <section aria-labelledby="new-scan-heading" className="stack">
      <div className="page-head">
        <div>
          <p className="eyebrow">Scans</p>
          <h1 id="new-scan-heading">New scan</h1>
        </div>
      </div>
      <div role="tablist" aria-label="What to scan" className="tabs">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              tabRefs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`${baseId}-${t.id}-tab`}
            aria-selected={tab === t.id}
            aria-controls={`${baseId}-${t.id}-panel`}
            tabIndex={tab === t.id ? 0 : -1}
            className="tab"
            onClick={() => select(t.id)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${baseId}-${tab}-panel`} aria-labelledby={`${baseId}-${tab}-tab`} className="card">
        {tab === "upload" ? <UploadPanel onCreated={onCreated} /> : <ConnectionPanel onCreated={onCreated} initial={search.connection} />}
      </div>
    </section>
  );
}
