import { callable, toaster } from "@decky/api";
import {
  ButtonItem,
  Field,
  Focusable,
  PanelSection,
  PanelSectionRow,
  Spinner,
} from "@decky/ui";
import { ComponentType, useCallback, useEffect, useState } from "react";

type Translation = {
  id: string;
  title: string;
  locale: string;
  version: string;
  installable: boolean;
  blocked: string;
  source: string;
  permission: string;
};

type GameRow = {
  appid: number;
  name: string;
  buildid: string;
  installed_translation: string;
  translations: Translation[];
};

type Job = { id: string; message: string; done: boolean; error: string };

type ManualFieldProps = { value: string; onChange: (value: string) => void };

const getGames = callable<[], { ok: boolean; error?: string; games: GameRow[] }>("list_games");
const refreshCatalog = callable<[], { ok: boolean; error?: string; games?: number }>("refresh_catalog");
const runInstall = callable<[number, string, boolean, string], { ok: boolean; job?: string; error?: string }>(
  "install",
);
const runUninstall = callable<[number], { ok: boolean; message?: string; error?: string }>("uninstall");
const runVerify = callable<
  [number],
  { ok: boolean; status?: string; message?: string; error?: string }
>("verify");
const getJob = callable<[string], Job>("get_job");
const manualAvailable = callable<[], { ok: boolean; available: boolean }>("manual_source_available");
const readLog = callable<[number], { ok: boolean; lines: string[] }>("read_log");

export function QAM() {
  const [games, setGames] = useState<GameRow[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [ManualField, setManualField] = useState<ComponentType<ManualFieldProps> | null>(null);
  const [manualPath, setManualPath] = useState("");

  const reload = useCallback(async () => {
    const result = await getGames();
    if (result.ok) {
      setGames(result.games);
      setError("");
    } else {
      setError(result.error ?? "falha ao listar jogos");
    }
  }, []);

  useEffect(() => {
    reload();
    manualAvailable().then(async (r) => {
      if (!r.available) return;
      const module = await import("./ManualSource");
      setManualField(() => module.ManualField);
    });
  }, [reload]);

  const watchJob = useCallback(
    async (jobId: string) => {
      for (;;) {
        const job = await getJob(jobId);
        setBusy(job.message);
        if (job.done) {
          setBusy("");
          toaster.toast({
            title: job.error ? "Traducao falhou" : "Traducao",
            body: job.error || job.message,
          });
          await reload();
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    },
    [reload],
  );

  const install = async (appid: number, translationId: string) => {
    setBusy("iniciando");
    const result = await runInstall(appid, translationId, false, manualPath);
    if (!result.ok || !result.job) {
      setBusy("");
      toaster.toast({ title: "Traducao", body: result.error ?? "falha ao iniciar" });
      return;
    }
    await watchJob(result.job);
  };

  return (
    <PanelSection title="Traducoes">
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => refreshCatalog().then(reload)}>
          Atualizar catalogo
        </ButtonItem>
      </PanelSectionRow>
      {ManualField && (
        <PanelSectionRow>
          <ManualField value={manualPath} onChange={setManualPath} />
        </PanelSectionRow>
      )}
      {busy && (
        <PanelSectionRow>
          <Field label={busy}>
            <Spinner />
          </Field>
        </PanelSectionRow>
      )}
      {error && (
        <PanelSectionRow>
          <Field label={error} />
        </PanelSectionRow>
      )}
      {games.map((game) => (
        <PanelSectionRow key={game.appid}>
          <Focusable style={{ width: "100%" }}>
            <Field label={`${game.name}${game.installed_translation ? " (traduzido)" : ""}`}>
              build {game.buildid}
            </Field>
            {game.translations.length === 0 && (
              <Field label="Nenhuma traducao no catalogo para este jogo." />
            )}
            {game.translations.map((translation) => (
              <div key={translation.id}>
                <Field
                  label={`${translation.title || translation.id} - ${translation.locale} v${translation.version}`}
                >
                  {translation.installable
                    ? `fonte: ${translation.source}`
                    : `bloqueado: ${translation.blocked}`}
                </Field>
                <Focusable style={{ display: "flex", gap: "8px" }}>
                  <ButtonItem
                    layout="below"
                    disabled={!translation.installable || !!busy}
                    onClick={() => install(game.appid, translation.id)}
                  >
                    Aplicar
                  </ButtonItem>
                  <ButtonItem
                    layout="below"
                    disabled={!!busy}
                    onClick={() =>
                      runVerify(game.appid).then((r) =>
                        toaster.toast({
                          title: "Verificar",
                          body: r.ok ? r.message ?? "ok" : r.error ?? r.status ?? "falhou",
                        }),
                      )
                    }
                  >
                    Verificar
                  </ButtonItem>
                  <ButtonItem
                    layout="below"
                    disabled={!!busy || !game.installed_translation}
                    onClick={() =>
                      runUninstall(game.appid).then((r) =>
                        toaster.toast({
                          title: "Desinstalar",
                          body: r.ok ? r.message ?? "removido" : r.error ?? "falhou",
                        }),
                      )
                    }
                  >
                    Reverter
                  </ButtonItem>
                </Focusable>
              </div>
            ))}
          </Focusable>
        </PanelSectionRow>
      ))}
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => readLog(80).then((r) => setLog(r.lines))}>
          Log
        </ButtonItem>
      </PanelSectionRow>
      {log.length > 0 && (
        <PanelSectionRow>
          <Field label={log.slice(-8).join("\n")} />
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <Field label="Traducoes aplicadas sao patches da comunidade. Nada aqui traduz texto nem contorna anti-cheat." />
      </PanelSectionRow>
    </PanelSection>
  );
}
