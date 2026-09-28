import React, { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from 'lucide-react';
import {
  CONFIRM_EVENT,
  FEEDBACK_EVENT,
  ConfirmEventDetail,
  FeedbackEventDetail,
} from '../services/feedback';
import {
  UNSAVED_CONFIRM_EVENT,
  type UnsavedConfirmEventDetail,
  type UnsavedDecision,
} from '../services/unsavedChanges';

const toastStyles = {
  success: { icon: CheckCircle2, className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  error: { icon: AlertCircle, className: 'border-red-200 bg-red-50 text-red-800' },
  warning: { icon: TriangleAlert, className: 'border-amber-200 bg-amber-50 text-amber-900' },
  info: { icon: Info, className: 'border-gray-200 bg-white text-gray-800' },
};

const GlobalFeedback: React.FC = () => {
  const [toasts, setToasts] = useState<FeedbackEventDetail[]>([]);
  const [confirmation, setConfirmation] = useState<ConfirmEventDetail | null>(null);
  const [unsavedConfirm, setUnsavedConfirm] = useState<UnsavedConfirmEventDetail | null>(null);

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

    const handleUnsavedConfirm = (event: Event) => {
      setUnsavedConfirm((event as CustomEvent<UnsavedConfirmEventDetail>).detail);
    };

    window.addEventListener(FEEDBACK_EVENT, handleFeedback);
    window.addEventListener(CONFIRM_EVENT, handleConfirm);
    window.addEventListener(UNSAVED_CONFIRM_EVENT, handleUnsavedConfirm);
    return () => {
      window.removeEventListener(FEEDBACK_EVENT, handleFeedback);
      window.removeEventListener(CONFIRM_EVENT, handleConfirm);
      window.removeEventListener(UNSAVED_CONFIRM_EVENT, handleUnsavedConfirm);
    };
  }, []);

  useEffect(() => {
    if (!confirmation && !unsavedConfirm) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      confirmation?.resolve(false);
      unsavedConfirm?.resolve('stay');
      setConfirmation(null);
      setUnsavedConfirm(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [confirmation, unsavedConfirm]);

  const finishConfirmation = (confirmed: boolean) => {
    confirmation?.resolve(confirmed);
    setConfirmation(null);
  };

  const finishUnsavedConfirm = (decision: UnsavedDecision) => {
    unsavedConfirm?.resolve(decision);
    setUnsavedConfirm(null);
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
              className={`flex items-start gap-3 rounded-md border px-4 py-3 shadow-[0_4px_16px_rgba(20,24,28,0.10)] ${style.className}`}
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
          className="modal-overlay"
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
            className="modal-container max-w-md"
          >
            <div className="modal-body flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-amber-50 text-amber-700">
                <TriangleAlert className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h2 id="global-confirm-title" className="text-base font-bold text-gray-900">{confirmation.title}</h2>
                <p id="global-confirm-message" className="mt-1 break-words text-sm leading-6 text-gray-600">{confirmation.message}</p>
              </div>
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button
                type="button"
                className="ios-btn-secondary rounded-md px-4 py-2 text-sm"
                onClick={() => finishConfirmation(false)}
              >
                {confirmation.cancelLabel}
              </button>
              <button
                type="button"
                className={`${confirmation.danger ? 'ios-btn-danger' : 'ios-btn-primary'} rounded-md px-4 py-2 text-sm`}
                onClick={() => finishConfirmation(true)}
                autoFocus
              >
                {confirmation.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}

      {unsavedConfirm && (
        <div
          className="modal-overlay"
          role="presentation"
          onMouseDown={event => {
            if (event.target === event.currentTarget) finishUnsavedConfirm('stay');
          }}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="unsaved-confirm-title"
            aria-describedby="unsaved-confirm-message"
            className="modal-container max-w-md"
          >
            <div className="modal-body flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-amber-50 text-amber-700">
                <TriangleAlert className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h2 id="unsaved-confirm-title" className="text-base font-bold text-gray-900">有未保存的更改</h2>
                <p id="unsaved-confirm-message" className="mt-1 break-words text-sm leading-6 text-gray-600">
                  「{unsavedConfirm.labels.join('、')}」尚未保存，直接离开会丢失这些更改，请先处理。
                </p>
              </div>
            </div>
            <div className="modal-footer flex flex-wrap justify-end gap-2">
              <button
                type="button"
                className="ios-btn-secondary rounded-md px-4 py-2 text-sm"
                onClick={() => finishUnsavedConfirm('stay')}
              >
                留在本页
              </button>
              <button
                type="button"
                className="ios-btn-danger rounded-md px-4 py-2 text-sm"
                onClick={() => finishUnsavedConfirm('discard')}
              >
                放弃并离开
              </button>
              <button
                type="button"
                className="ios-btn-primary rounded-md px-4 py-2 text-sm"
                onClick={() => finishUnsavedConfirm('save')}
                autoFocus
              >
                保存并离开
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default GlobalFeedback;
