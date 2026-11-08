import { useTheme, type ThemePreference } from "../theme";
import { IconMoon, IconMonitor, IconSun } from "./icons";

const OPTIONS: Array<{ value: ThemePreference; label: string; Icon: typeof IconSun }> = [
  { value: "light", label: "Light", Icon: IconSun },
  { value: "dark", label: "Dark", Icon: IconMoon },
  { value: "system", label: "System", Icon: IconMonitor },
];

/** Accessible Light / Dark / System segmented control. */
export function ThemeToggle() {
  const { preference, setPreference } = useTheme();
  return (
    <div className="theme-toggle" role="group" aria-label="Color theme">
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          className="theme-seg"
          aria-pressed={preference === value}
          aria-label={`${label} theme`}
          title={`${label} theme`}
          onClick={() => setPreference(value)}
        >
          <Icon />
        </button>
      ))}
    </div>
  );
}
