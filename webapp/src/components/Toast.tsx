import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

type Toast = { id: number; message: string; tone: "error" | "success" };
const ToastContext = createContext<(message: string, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const notify = useCallback((message: string, tone: Toast["tone"] = "error") => {
    const id = Date.now() + Math.random();
    setToasts((items) => [...items, { id, message, tone }]);
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 5000);
  }, []);
  const value = useMemo(() => notify, [notify]);
  return <ToastContext.Provider value={value}>{children}<div className="toast-region" aria-live="polite">{toasts.map((toast) => <div key={toast.id} className={`toast ${toast.tone}`}>{toast.message}</div>)}</div></ToastContext.Provider>;
}

export const useToast = () => useContext(ToastContext);
