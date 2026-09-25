import { useEffect } from 'react';
import { Check, Save } from 'lucide-react';
import { clearUnsavedScope, registerUnsavedScope } from '../services/unsavedChanges';

interface FloatingSaveButtonProps {
  dirty: boolean;
  guardKey: string;
  guardLabel: string;
  onSave: () => void;
  onDiscard: () => void;
  label?: string;
}

const FloatingSaveButton = ({
  dirty,
  guardKey,
  guardLabel,
  onSave,
  onDiscard,
  label = '保存设置',
}: FloatingSaveButtonProps) => {
  useEffect(() => {
    if (!dirty) return undefined;
    registerUnsavedScope({ key: guardKey, label: guardLabel, save: onSave, discard: onDiscard });
    return () => clearUnsavedScope(guardKey);
  }, [dirty, guardKey, guardLabel, onSave, onDiscard]);

  return (
    <button
      type="button"
      className={`floating-save-capsule${dirty ? ' floating-save-capsule--dirty' : ''}`}
      onClick={onSave}
      disabled={!dirty}
      aria-label={dirty ? label : '已保存'}
    >
      <span className="floating-save-capsule__icon" aria-hidden="true">
        {dirty ? <Save className="h-4 w-4" /> : <Check className="h-4 w-4" />}
      </span>
      <span>{dirty ? label : '已保存'}</span>
    </button>
  );
};

export default FloatingSaveButton;
