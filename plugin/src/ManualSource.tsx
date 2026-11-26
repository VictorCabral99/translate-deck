import { TextField } from "@decky/ui";

export function ManualField(props: { value: string; onChange: (value: string) => void }) {
  return (
    <TextField
      label="Descritor manual (sideload)"
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
    />
  );
}
