import { callable, toaster } from "@decky/api";
import { ButtonItem, Dropdown, Field, Focusable, TextField } from "@decky/ui";
import { useState } from "react";

type GameOption = { appid: number; name: string; engine: string };

type Report = {
  appid: number;
  game: string;
  pack: string;
  pack_layout: string;
  mode: string;
  artifact: string;
  sha256: string;
  size: number;
  locale: string;
  target: string;
  candidates: string[];
  required_bytes: number;
  warnings: string[];
};

const inspectTranslation = callable<
  [number, string, string],
  { ok: boolean; report?: Report; error?: string }
>("inspect_translation");
const libraryAdd = callable<
  [number, string, string],
  { ok: boolean; entry?: { ref: string }; error?: string }
>("library_add");

const MODE_LABELS: Record<string, string> = {
  insert: "traducao (.translation/.po)",
  replace_pack: "pack inteiro (.pck)",
  descriptor: "descritor .json",
};

function mb(bytes: number): string {
  return `${Math.max(1, Math.round(bytes / (1024 * 1024)))} MB`;
}

export function LibrarySection(props: {
  games: GameOption[];
  onChanged: () => void;
}) {
  const godot = props.games.filter((game) => game.engine === "godot");
  const [appid, setAppid] = useState<number>(0);
  const [path, setPath] = useState("");
  const [target, setTarget] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const selected = appid || godot[0]?.appid || 0;

  const inspect = async (chosen: string) => {
    if (!selected || !path.trim()) {
      setError("escolha um jogo Godot e informe o caminho do arquivo");
      return;
    }
    setBusy(true);
    setError("");
    setReport(null);
    const result = await inspectTranslation(selected, path.trim(), chosen);
    setBusy(false);
    if (!result.ok || !result.report) {
      setError(result.error ?? "falha na inspecao");
      return;
    }
    setReport(result.report);
    setTarget(result.report.target);
  };

  const add = async () => {
    setBusy(true);
    const result = await libraryAdd(selected, path.trim(), target);
    setBusy(false);
    if (!result.ok) {
      setError(result.error ?? "falha ao adicionar");
      return;
    }
    toaster.toast({ title: "Biblioteca", body: `adicionada ${result.entry?.ref ?? ""}` });
    setReport(null);
    setPath("");
    setTarget("");
    props.onChanged();
  };

  return (
    <>
      <Focusable style={{ width: "100%" }}>
        <Field label="Minhas traducoes (sideload)">
          {godot.length > 0
            ? `${godot.length} jogo(s) Godot`
            : "nenhum jogo Godot instalado"}
        </Field>
        {godot.length > 0 && (
          <Dropdown
            rgOptions={godot.map((game) => ({ data: game.appid, label: game.name }))}
            selectedOption={selected}
            disabled={busy}
            onChange={(option) => {
              setAppid(option.data as number);
              setReport(null);
              setTarget("");
              setError("");
            }}
          />
        )}
        <TextField
          label="Arquivo (.translation/.po/.pck/.json/.zip) ou pasta"
          value={path}
          disabled={busy}
          onChange={(e) => setPath(e.target.value)}
        />
        <Focusable style={{ display: "flex", gap: "8px" }}>
          <ButtonItem layout="below" disabled={busy || !selected} onClick={() => inspect(target)}>
            Inspecionar
          </ButtonItem>
        </Focusable>
        {error && <Field label={error} />}
        {report && (
          <>
            <Field label={`${MODE_LABELS[report.mode] ?? report.mode}: ${report.artifact}`}>
              {`${report.locale} | sha256 ${report.sha256.slice(0, 12)} | ${mb(report.size)}`}
            </Field>
            <Field label={`pack ${report.pack} (${report.pack_layout})`}>
              {report.mode === "replace_pack" ? "substitui o pack inteiro" : report.target || "escolha o destino"}
            </Field>
            {report.mode === "insert" && report.candidates.length > 1 && (
              <Dropdown
                rgOptions={report.candidates.map((item) => ({ data: item, label: item }))}
                selectedOption={target}
                disabled={busy}
                onChange={(option) => inspect(String(option.data))}
              />
            )}
            {report.warnings.map((warning) => (
              <Field key={warning} label={warning} />
            ))}
            <Field label={`espaco necessario ~${mb(report.required_bytes)}`} />
            <Focusable style={{ display: "flex", gap: "8px" }}>
              <ButtonItem
                layout="below"
                disabled={busy || !report.target}
                onClick={add}
              >
                Adicionar a biblioteca
              </ButtonItem>
            </Focusable>
          </>
        )}
      </Focusable>
    </>
  );
}
