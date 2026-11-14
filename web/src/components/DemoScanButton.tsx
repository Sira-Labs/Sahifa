import { useMutation } from "@tanstack/react-query";
import { api } from "../api";
import type { Scan } from "../types";
import { VIEWER_REASON, editableWorkspaces, uploadWorkspace, useMe, useWorkspaceFilter } from "../workspace";
import { ErrorPanel } from "./ErrorPanel";

/** Starts a scan of the demo shop (spec 022) and hands the new scan to `onCreated`. The scan
 * goes to `workspaceId`, or to the workspace an upload would go to. Viewers cannot start it. */
export function DemoScanButton({
  label,
  className = "btn",
  workspaceId,
  onCreated,
}: {
  label: string;
  className?: string;
  workspaceId?: string;
  onCreated: (scan: Scan) => void;
}) {
  const me = useMe();
  const editable = editableWorkspaces(me.data);
  const filtered = useWorkspaceFilter();
  const readOnly = !!me.data && editable.length === 0;
  const demo = useMutation({
    // With one workspace to upload to, the API picks it; with several, the choice goes along.
    mutationFn: () => api.demoScan(editable.length > 1 ? workspaceId || uploadWorkspace(editable, filtered) : undefined),
    onSuccess: onCreated,
  });
  return (
    <>
      <button
        type="button"
        className={className}
        disabled={demo.isPending || readOnly}
        title={readOnly ? VIEWER_REASON : undefined}
        onClick={() => demo.mutate()}
      >
        {demo.isPending ? "Starting the demo…" : label}
      </button>
      {demo.isError && <ErrorPanel title="The demo scan did not start" error={demo.error} onRetry={() => demo.mutate()} />}
    </>
  );
}
