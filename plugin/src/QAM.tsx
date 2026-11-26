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
  local?: boolean;
  kind?: string;
  targets?: string[];
};

type GameRow = {
  appid: number;
  name: string;
  buildid: string;
  engine: string;
  installed_translation: string;
  translations: Translation[];
};

type Job = { id: string; message: string; done: boolean; error: string };

type LibraryProps = { games: GameRow[]; onChanged: () => void };

const getGames = callable<
  [],
  { ok: boolean; error?: string; warning?: string; games: GameRow[] }
>("list_games");
const refreshCatalog = callable<[], { ok: boolean; error?: string; games?: number }>("refresh_catalog");
const runInstall = callable<[number, string, boolean, string], { ok: boolean; job?: string; error?: string }>(
  "install",
);
const runUninstall = callable<[number], { ok: boolean; message?: string; error?: string }>("uninstall");
const runVerify = callable<
  [number],
  { ok: boolean; status?: string; message?: string; error?: string }
>("verify");
const removeLocal = callable<[number, string], { ok: boolean; error?: string }>("library_remove");
const getJob = callable<[string], Job>("get_job");
const manualAvailable = callable<[], { ok: boolean; available: boolean }>("manual_source_available");
const readLog = callable<[number], { ok: boolean; lines: string[] }>("read_log");

export function QAM() {
  const [games, setGames] = useState<GameRow[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [Library, setLibrary] = useState<ComponentType<LibraryProps> | null>(null);

  const reload = useCallback(async () => {
    const result = await getGames();
    if (result.ok) {
      setGames(result.games);
      setError("");
      setNotice(result.warning ?? "");
    } else {
      setError(result.error ?? "falha ao listar jogos");
    }
  }, []);

  useEffect(() => {
    reload();
    manualAvailable().then(async (r) => {
      if (!r.available) return;
      const module = await import("./ManualSource");
      setLibrary(() => module.LibrarySection);
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
    const result = await runInstall(appid, translationId, false, "");
    if (!result.ok || !result.job) {
      setBusy("");
      toaster.toast({ title: "Traducao", body: result.error ?? "falha ao iniciar" });
      return;
    }
    await watchJob(result.job);
  };

  const remove = async (appid: number, translationId: string) => {
    const result = await removeLocal(appid, translationId);
    toaster.toast({
      title: "Biblioteca",
      body: result.ok ? "removida da biblioteca" : result.error ?? "falhou",
    });
    await reload();
  };

  return (
    <PanelSection title="Traducoes">
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => refreshCatalog().then(reload)}>
          Atualizar catalogo
        </ButtonItem>
      </PanelSectionRow>
      {Library && (
        <PanelSectionRow>
          <Library games={games} onChanged={reload} />
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
      {notice && !error && (
        <PanelSectionRow>
          <Field label={notice} />
        </PanelSectionRow>
      )}
      {games.map((game) => (
        <PanelSectionRow key={game.appid}>
          <Focusable style={{ width: "100%" }}>
            <Field label={`${game.name}${game.installed_translation ? " (traduzido)" : ""}`}>
              {`${game.engine} | build ${game.buildid}`}
            </Field>
            {game.translations.length === 0 && (
              <Field
                label={
                  game.engine === "godot"
                    ? "Nenhuma traducao conhecida; adicione um arquivo na secao acima."
                    : `Engine ${game.engine}: somente Godot por enquanto.`
                }
              />
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
                  {translation.local && (
                    <ButtonItem
                      layout="below"
                      disabled={
                        !!busy || game.installed_translation === translation.id
                      }
                      onClick={() => remove(game.appid, translation.id)}
                    >
                      Remover
                    </ButtonItem>
                  )}
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
