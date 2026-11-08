/* eslint-disable react-refresh/only-export-components -- Context and resolver are shared with lazy routes. */
import { createContext, useContext, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { config } from "./config";

export type RuntimeConfig = Omit<typeof config, "serverModels"> & {
  serverModels: readonly { id: "current" | "seated"; label: string; httpUrl: string; wsUrl: string }[];
};
const RuntimeContext = createContext<RuntimeConfig>(config);
export const useRuntimeConfig = () => useContext(RuntimeContext);

export function PlatformPage({ page: Page }: { page: ComponentType<{ platformUrl: string }> }) {
  const runtime = useRuntimeConfig();
  return <Page platformUrl={runtime.platformHttpUrl} />;
}

export async function platformHealthy(url: string, signal: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(`${url}/api/v1/auth/me`, {
      credentials: "include", cache: "no-store", signal,
    });
    // A logged-out platform must still be a usable failover target.
    if (response.status === 401) return true;
    if (!response.ok) return false;
    const body: unknown = await response.json();
    return typeof body === "object" && body !== null && "user" in body;
  } catch { return false; }
}

export function windowsConfig(): RuntimeConfig {
  const windows = config.windowsRuntime;
  if (!windows) return config;
  return { ...config, platformHttpUrl: windows.httpUrl, inferenceHttpUrl: windows.httpUrl,
    inferenceWsUrl: windows.wsUrl, platformHost: "windows",
    serverModels: config.serverModels.map(model => model.id === "current"
      ? { ...model, httpUrl: windows.httpUrl, wsUrl: windows.wsUrl } : model) };
}

/** Separate databases: remount all consumers on failover; never replay writes or fail back mid-session. */
export function RuntimeBoundary({ children }: { children: ReactNode }) {
  const [windows, setWindows] = useState(false);
  useEffect(() => {
    if (!config.windowsRuntime || config.publicDemo || windows) return;
    let disposed = false;
    let failures = 0;
    let request: AbortController | null = null;
    const check = async () => {
      if (request) return;
      request = new AbortController();
      const timeout = window.setTimeout(() => request?.abort(), 4000);
      const primaryOk = await platformHealthy(config.platformHttpUrl, request.signal);
      window.clearTimeout(timeout);
      if (disposed) return;
      failures = primaryOk ? 0 : failures + 1;
      if (failures >= 2) {
        request = new AbortController();
        const fallbackTimeout = window.setTimeout(() => request?.abort(), 4000);
        const fallbackOk = await platformHealthy(config.windowsRuntime!.httpUrl, request.signal);
        window.clearTimeout(fallbackTimeout);
        if (!disposed && fallbackOk) setWindows(true);
      }
      request = null;
    };
    void check();
    const timer = window.setInterval(() => void check(), 5000);
    return () => { disposed = true; window.clearInterval(timer); request?.abort(); };
  }, [windows]);
  const selected = windows ? windowsConfig() : config;
  return <RuntimeContext.Provider key={selected.platformHost} value={selected}>
    {windows && <div role="status" className="platform-failover-notice">
      Đang dùng máy chủ Windows. Dữ liệu độc lập với Mac; vui lòng đăng nhập bằng tài khoản Windows.
      Tải lại trang để kiểm tra và ưu tiên Mac.
    </div>}
    {children}
  </RuntimeContext.Provider>;
}
