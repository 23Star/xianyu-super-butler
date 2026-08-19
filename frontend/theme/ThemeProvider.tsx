import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from 'react';

export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const THEME_STORAGE_KEY = 'xianyu-theme-preference';
const DARK_MEDIA_QUERY = '(prefers-color-scheme: dark)';

interface ThemeContextValue {
  theme: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const normalizeTheme = (value: string | null): ThemePreference => (
  value === 'light' || value === 'dark' || value === 'system' ? value : 'system'
);

const readStoredTheme = (): ThemePreference => {
  if (typeof window === 'undefined') return 'system';
  try {
    return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return 'system';
  }
};

const readSystemTheme = (): ResolvedTheme => {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia(DARK_MEDIA_QUERY).matches ? 'dark' : 'light';
};

interface ThemeProviderProps {
  children: React.ReactNode;
}

export const ThemeProvider: React.FC<ThemeProviderProps> = ({ children }) => {
  const [theme, setThemeState] = useState<ThemePreference>(readStoredTheme);
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(readSystemTheme);

  useEffect(() => {
    const media = window.matchMedia(DARK_MEDIA_QUERY);
    const handleChange = (event: MediaQueryListEvent) => {
      setSystemTheme(event.matches ? 'dark' : 'light');
    };

    setSystemTheme(media.matches ? 'dark' : 'light');
    media.addEventListener('change', handleChange);
    return () => media.removeEventListener('change', handleChange);
  }, []);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY) {
        setThemeState(normalizeTheme(event.newValue));
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  const resolvedTheme = theme === 'system' ? systemTheme : theme;

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolvedTheme;
    root.dataset.themePreference = theme;
    root.classList.toggle('dark', resolvedTheme === 'dark');
    root.style.colorScheme = resolvedTheme;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // 存储被浏览器禁用时，主题仍在当前页面内正常生效。
    }
  }, [resolvedTheme, theme]);

  const setTheme = useCallback((nextTheme: ThemePreference) => {
    setThemeState(nextTheme);
  }, []);

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme }),
    [resolvedTheme, setTheme, theme]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export const useTheme = (): ThemeContextValue => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used inside ThemeProvider');
  }
  return context;
};
