export type UnsavedDecision = 'save' | 'discard' | 'stay';

export interface UnsavedScope {
  key: string;
  label: string;
  save: () => void;
  discard: () => void;
}

export interface UnsavedConfirmEventDetail {
  labels: string[];
  resolve: (decision: UnsavedDecision) => void;
}

export const UNSAVED_CONFIRM_EVENT = 'app:unsaved-confirm';

const scopes = new Map<string, UnsavedScope>();

export const registerUnsavedScope = (scope: UnsavedScope) => {
  scopes.set(scope.key, scope);
};

export const clearUnsavedScope = (key: string) => {
  scopes.delete(key);
};

export const hasUnsavedScopes = () => scopes.size > 0;

export const getUnsavedScopeLabels = () => Array.from(scopes.values(), (scope) => scope.label);

export const resolveUnsavedScopes = (decision: 'save' | 'discard') => {
  for (const scope of [...scopes.values()]) {
    if (decision === 'save') scope.save();
    else scope.discard();
  }
};

export const requestUnsavedDecision = (labels: string[]) =>
  new Promise<UnsavedDecision>((resolve) => {
    window.dispatchEvent(new CustomEvent<UnsavedConfirmEventDetail>(UNSAVED_CONFIRM_EVENT, {
      detail: { labels, resolve },
    }));
  });

export const confirmLeaveUnsaved = async () => {
  if (!hasUnsavedScopes()) return true;
  const decision = await requestUnsavedDecision(getUnsavedScopeLabels());
  if (decision === 'stay') return false;
  resolveUnsavedScopes(decision);
  return true;
};
