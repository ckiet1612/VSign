import { Cpu } from "../icons";
import type { ServerModelOption } from "../hooks/useServerModel";

interface Props {
  options: readonly ServerModelOption[];
  value: string;
  disabled: boolean;
  switching: boolean;
  error: string;
  onChange: (id: string) => void;
}

export function ServerModelSelector({ options, value, disabled, switching, error, onChange }: Props) {
  return <div className="server-model-bar">
    <label className="server-model-select"><Cpu size={18} aria-hidden="true" /><span>Model máy chủ</span>
      <select aria-label="Model máy chủ" value={value} disabled={disabled || switching} onChange={event => onChange(event.target.value)}>
        {options.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
      </select>
    </label>
    {switching && <span role="status">Đang kiểm tra model…</span>}
    {error && <span role="alert">{error}</span>}
  </div>;
}
