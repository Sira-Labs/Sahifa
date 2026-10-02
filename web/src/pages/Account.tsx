import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { METHOD_NAMES, authApi, browser, deviceName, type Device } from "../auth";
import { ErrorPanel } from "../components/ErrorPanel";
import { formatLocalTime } from "../format";

/** `/settings/account`: who is signed in, the signed-in devices, and passkeys (spec 006). */
export function Account() {
  const client = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: authApi.me, retry: false, staleTime: 60_000 });
  const options = useQuery({ queryKey: ["auth-options"], queryFn: authApi.options });
  const signedIn = me.data?.mode === "oidc";
  const devices = useQuery({ queryKey: ["sessions"], queryFn: authApi.sessions, enabled: signedIn });
  const refresh = () => client.invalidateQueries({ queryKey: ["sessions"] });
  const revoke = useMutation({
    mutationFn: (device: Device) => authApi.revokeSession(device.id),
    // Signing out this device ends the session: back to the sign-in page.
    onSuccess: (_, device) => (device.current ? browser.assign("/login") : refresh()),
  });
  const revokeOthers = useMutation({ mutationFn: authApi.revokeOthers, onSuccess: refresh });
  const others = devices.data?.filter((d) => !d.current).length ?? 0;
  const accountUrl = options.data?.account_url ?? null;

  return (
    <section aria-labelledby="account-heading" className="stack-lg">
      <div className="page-head">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 id="account-heading">Account</h1>
        </div>
      </div>

      {me.data && (
        <p className="lede">
          {signedIn ? (
            <>
              Signed in as <strong className="break-anywhere">{me.data.user.email}</strong> with{" "}
              {METHOD_NAMES[me.data.sign_in_method] ?? me.data.sign_in_method}
              {me.data.admin ? ", as the administrator" : ""}.
            </>
          ) : (
            <>This server runs with {METHOD_NAMES[me.data.sign_in_method] ?? me.data.sign_in_method}: there are no accounts or devices to manage.</>
          )}
        </p>
      )}

      {signedIn && (
        <section aria-labelledby="devices-heading" className="card stack">
          <div className="section-head">
            <h2 id="devices-heading">Signed-in devices</h2>
            <button
              type="button"
              className="btn btn-small"
              disabled={others === 0 || revokeOthers.isPending}
              onClick={() => revokeOthers.mutate()}
            >
              Sign out all other devices
            </button>
          </div>
          {devices.isPending && <p role="status">Loading devices…</p>}
          {devices.isError && <ErrorPanel title="Could not load devices" error={devices.error} onRetry={() => void devices.refetch()} />}
          {revoke.isError && (
            <p role="alert" className="text-bad">
              Could not sign out: {revoke.error.message}
            </p>
          )}
          {revokeOthers.isError && (
            <p role="alert" className="text-bad">
              Could not sign out other devices: {revokeOthers.error.message}
            </p>
          )}
          {devices.data && devices.data.length > 0 && (
            <ul className="device-list">
              {devices.data.map((d) => (
                <li key={d.id} aria-label={deviceName(d.user_agent)}>
                  <div className="device-info">
                    <p className="font-semibold">
                      {deviceName(d.user_agent)} {d.current && <span className="chip chip-ok">This device</span>}
                    </p>
                    <p className="muted device-meta">
                      Signed in with {METHOD_NAMES[d.sign_in_method] ?? d.sign_in_method} · last active{" "}
                      <span className="num">{formatLocalTime(d.last_seen_at)}</span>
                      {d.ip_address && (
                        <>
                          {" "}
                          · <span className="num">{d.ip_address}</span>
                        </>
                      )}
                    </p>
                  </div>
                  <button type="button" className="btn btn-small" disabled={revoke.isPending} onClick={() => revoke.mutate(d)}>
                    Sign out
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {signedIn && accountUrl && (
        <section aria-labelledby="passkeys-heading" className="card stack-sm">
          <h2 id="passkeys-heading">Passkeys</h2>
          <p className="muted">
            Add, rename or remove passkeys in the sign-in service's account console (under “Signing in”). A first sign-in always goes
            through Google or GitHub.
          </p>
          <div>
            <a href={accountUrl} className="btn" rel="noopener">
              Manage passkeys
            </a>
          </div>
        </section>
      )}
    </section>
  );
}
