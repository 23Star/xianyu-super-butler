import React from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';
import { ThemePreference, useTheme } from '../theme/ThemeProvider';

interface ThemeToggleProps {
  compact?: boolean;
  className?: string;
}

const themeOptions: Array<{
  value: ThemePreference;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { value: 'light', label: '浅色', description: '使用浅色主题', icon: Sun },
  { value: 'dark', label: '深色', description: '使用深色主题', icon: Moon },
  { value: 'system', label: '自动', description: '跟随系统外观', icon: Monitor },
];

const ThemeToggle: React.FC<ThemeToggleProps> = ({ compact = false, className = '' }) => {
  const { theme, resolvedTheme, setTheme } = useTheme();

  const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex = index;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextIndex = (index + 1) % themeOptions.length;
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextIndex = (index - 1 + themeOptions.length) % themeOptions.length;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = themeOptions.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    const nextTheme = themeOptions[nextIndex].value;
    setTheme(nextTheme);
    event.currentTarget.parentElement
      ?.querySelector<HTMLButtonElement>(`[data-theme-option="${nextTheme}"]`)
      ?.focus();
  };

  return (
    <div
      className={`theme-picker ${compact ? 'theme-picker--compact' : ''} ${className}`.trim()}
      data-resolved-theme={resolvedTheme}
    >
      {!compact && (
        <div className="theme-picker__heading">
          <span>显示主题</span>
          <span className="theme-picker__status">
            {theme === 'system' ? `自动 · ${resolvedTheme === 'dark' ? '深色' : '浅色'}` : theme === 'dark' ? '深色' : '浅色'}
          </span>
        </div>
      )}
      <div className="theme-switcher" role="radiogroup" aria-label="显示主题">
        {themeOptions.map((option, index) => {
          const Icon = option.icon;
          const selected = theme === option.value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-label={option.description}
              title={option.description}
              tabIndex={selected ? 0 : -1}
              data-theme-option={option.value}
              className={`theme-switcher__option ${selected ? 'theme-switcher__option--active' : ''}`}
              onClick={() => setTheme(option.value)}
              onKeyDown={(event) => handleKeyDown(event, index)}
            >
              <Icon className="h-3.5 w-3.5" />
              {!compact && <span>{option.label}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default ThemeToggle;
