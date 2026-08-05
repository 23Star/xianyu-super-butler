import React, { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from 'lucide-react';
import {
  CONFIRM_EVENT,
  FEEDBACK_EVENT,
  ConfirmEventDetail,
  FeedbackEventDetail,
} from '../services/feedback';

const toastStyles = {
  success: { icon: CheckCircle2, className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  error: { icon: AlertCircle, className: 'border-red-200 bg-red-50 text-red-800' },
  warning: { icon: TriangleAlert, className: 'border-amber-200 bg-amber-50 text-amber-900' },
  info: { icon: Info, className: 'border-gray-200 bg-white text-gray-800' },
};

const GlobalFeedback: React.FC = () => {
  const [toasts, setToasts] = useState<FeedbackEventDetail[]>([]);
  const [confirmation, setConfirmation] = useState<ConfirmEventDetail | null>(null);

  useEffect(() => {
    const handleFeedback = (event: Event) => {
      const detail = (event as CustomEvent<FeedbackEventDetail>).detail;
      setToasts(current => [...current.slice(-3), detail]);
      window.setTimeout(() => {
        setToasts(current => current.filter(item => item.id !== detail.id));
      }, detail.type === 'error' ? 6000 : 3600);
    };

    const handleConfirm = (event: Event) => {
      setConfirmation((event as CustomEvent<ConfirmEventDetail>).detail);
    };

    window.addEventListener(FEEDBACK_EVENT, handleFeedback);
    window.addEventListener(CONFIRM_EVENT, handleConfirm);
    return () => {
      window.removeEventListener(FEEDBACK_EVENT, handleFeedback);
      window.removeEventListener(CONFIRM_EVENT, handleConfirm);
    };
  }, []);

  useEffect(() => {
    if (!confirmation) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      confirmation.resolve(false);
      setConfirmation(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [confirmation]);

  const finishConfirmation = (confirmed: boolean) => {
    confirmation?.resolve(confirmed);
    setConfirmation(null);
  };

  return (
    <>
      <div className="fixed right-4 top-4 z-[10000] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
        {toasts.map(toast => {
          const style = toastStyles[toast.type];
          const Icon = style.icon;
          return (
            <div
              key={toast.id}
              role={toast.type === 'error' ? 'alert' : 'status'}
              className={`flex items-start gap-3 rounded-md border px-4 py-3 shadow-lg ${style.className}`}
            >
              <Icon className="mt-0.5 h-5 w-5 shrink-0" />
              <span className="min-w-0 flex-1 break-words text-sm font-medium">{toast.message}</span>
              <button
                type="button"
                className="shrink-0 rounded p-0.5 hover:bg-black/5"
                onClick={() => setToasts(current => current.filter(item => item.id !== toast.id))}
                aria-label="关闭提示"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>

      {confirmation && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/35 p-4"
          role="presentation"
          onMouseDown={event => {
            if (event.target === event.currentTarget) finishConfirmation(false);
          }}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="global-confirm-title"
            aria-describedby="global-confirm-message"
            className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-5 shadow-2xl"
          >
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-amber-50 text-amber-700">
                <TriangleAlert className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h2 id="global-confirm-title" className="text-base font-bold text-gray-900">{confirmation.title}</h2>
                <p id="global-confirm-message" className="mt-1 break-words text-sm leading-6 text-gray-600">{confirmation.message}</p>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                onClick={() => finishConfirmation(false)}
              >
                {confirmation.cancelLabel}
              </button>
              <button
                type="button"
                className={`rounded-md px-4 py-2 text-sm font-bold ${
                  confirmation.danger
                    ? 'bg-red-600 text-white hover:bg-red-700'
                    : 'bg-[#FFE815] text-black hover:bg-[#FFD600]'
                }`}
                onClick={() => finishConfirmation(true)}
                autoFocus
              >
                {confirmation.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default GlobalFeedback;
