import type { Profile } from "../api/types";

type ProfileSelectProps = {
  profiles: Profile[];
  value: string;
  onChange: (profileId: string) => void;
  disabled?: boolean;
};

export function ProfileSelect({
  profiles,
  value,
  onChange,
  disabled = false,
}: ProfileSelectProps) {
  return (
    <label className="field">
      <span>Perfil</span>
      <select
        value={value}
        disabled={disabled || profiles.length === 0}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Selecciona un perfil</option>
        {profiles.map((profile) => (
          <option key={profile.id} value={profile.id}>
            {profile.display_name}
          </option>
        ))}
      </select>
    </label>
  );
}
