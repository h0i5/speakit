import { useCallback, useEffect, useRef, useState } from "react";
import {
  RiCheckLine, RiFileCopyLine, RiKeyboardLine, RiMagicLine, RiMicLine, RiRestartLine,
  RiSparkling2Line, RiVolumeUpLine,
} from "@remixicon/react";
import { Button } from "@/components/base/buttons/button";
import { Chip } from "@/components/base/badges/chip";
import { Input } from "@/components/base/input/input";
import { NumberField } from "@/components/base/number-field/number-field";
import { Select, SelectItem } from "@/components/base/select/select";
import { Switch } from "@/components/base/switch/switch";
import { Tab, TabList, TabPanel, Tabs } from "@/components/base/tabs/tabs";
import { Textarea } from "@/components/base/textarea/textarea";
import { Toaster, toast } from "@/components/base/toast/toast";
import { api, type HistoryItem, type Setting, type Settings, type Status, type Value } from "./api";

const TABS: { id: string; label: string; sections: string[] }[] = [
  { id: "general", label: "General", sections: ["recording", "feedback"] },
  { id: "typing", label: "Typing", sections: ["typing"] },
  { id: "cleanup", label: "Cleanup", sections: ["cleanup"] },
  { id: "words", label: "Words", sections: [] },
  { id: "history", label: "History", sections: [] },
  { id: "advanced", label: "Advanced", sections: ["model"] },
];
const SECTION_TITLES: Record<string, string> = {
  recording: "Recording", feedback: "Feedback", typing: "Typing", cleanup: "Cleanup model", model: "Speech model",
};

function Card({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border-button-default bg-background-secondary-default">
      <header className="flex items-center justify-between px-5 pt-4 pb-2">
        <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
        {aside}
      </header>
      <div className="divide-y divide-border-button-default">{children}</div>
    </section>
  );
}

function Row({ label, help, children, badge }: { label: string; help?: string; children: React.ReactNode; badge?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-6 px-5 py-3.5">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-medium text-text-primary">{label}{badge}</div>
        {help && <p className="mt-0.5 text-xs text-text-tertiary">{help}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Control({ s, value, onChange, disabled }: { s: Setting; value: Value; onChange: (v: Value) => void; disabled: boolean }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  if (typeof s.default === "boolean")
    return <Switch isSelected={Boolean(value)} onChange={onChange} isDisabled={disabled} aria-label={s.label} />;
  if (s.choices.length)
    return (
      <Select aria-label={s.label} selectedKey={String(value)} isDisabled={disabled}
        onSelectionChange={(k) => k != null && onChange(String(k))} className="w-64">
        {s.choices.map((c) => <SelectItem key={c} id={c}>{c || "none (full precision)"}</SelectItem>)}
      </Select>
    );
  if (typeof s.default === "number")
    return (
      <NumberField aria-label={s.label} value={Number(value)} isDisabled={disabled} className="w-40"
        formatOptions={{ useGrouping: false, maximumFractionDigits: 2 }}
        minValue={s.min ?? undefined} maxValue={s.max ?? undefined}
        step={Number.isInteger(s.default) && !String(s.default).includes(".") && s.name !== "HOLD_SECONDS" ? 1 : 0.1}
        onChange={(v) => !Number.isNaN(v) && v !== value && onChange(v)} />
    );
  return (
    <Input aria-label={s.label} value={draft} onChange={setDraft} isDisabled={disabled} className="w-80"
      placeholder={s.name === "MIC_TARGET" ? "system default" : undefined}
      onBlur={() => draft !== value && onChange(draft)}
      onKeyDown={(e) => e.key === "Enter" && draft !== value && onChange(draft)} />
  );
}

function StatusBar({ status }: { status: Status | null }) {
  if (!status) return <Chip color="rose">daemon unreachable</Chip>;
  const rec = status.state === "recording";
  return (
    <div className="flex flex-wrap gap-2">
      <Chip color={rec ? "rose" : "neutral"}>{rec ? "● recording" : "idle"}</Chip>
      <Chip color={status.model_ready ? "lime" : "yellow"}>
        {status.model_ready ? `speech ready · ${status.device}` : "speech loading…"}
      </Chip>
      <Chip color={status.llm ? "lime" : "rose"}>{status.llm ? "cleanup online" : "cleanup offline"}</Chip>
    </div>
  );
}

const KEYS = [
  { key: "Home", icon: RiMicLine, title: "Dictate", text: "Your words as spoken, fillers dropped." },
  { key: "Insert", icon: RiSparkling2Line, title: "Cleanup", text: "Grammar, self-corrections, lists, app-matched tone." },
  { key: "End", icon: RiMagicLine, title: "Command", text: "Select text, say what to do with it. Nothing selected: writes what you ask." },
];

function Keys() {
  return (
    <Card title="Keys" aside={<span className="text-xs text-text-tertiary">tap to toggle · hold to talk</span>}>
      <div className="grid grid-cols-3 gap-3 p-4">
        {KEYS.map(({ key, icon: Icon, title, text }) => (
          <div key={key} className="rounded-xl border border-border-button-default bg-background-tertiary-default p-3.5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-sm font-medium text-text-primary"><Icon className="size-4" />{title}</span>
              <kbd className="rounded-md border border-border-button-default px-1.5 py-0.5 font-mono text-xs text-text-secondary">{key}</kbd>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-text-tertiary">{text}</p>
          </div>
        ))}
      </div>
      <p className="px-5 py-3 text-xs text-text-tertiary">
        <RiKeyboardLine className="mr-1 inline size-3.5" />
        Rebind in <code className="font-mono">~/.config/hypr/hyprland.conf</code> ($speakitKey, $speakitCleanKey, $speakitCommandKey).
      </p>
    </Card>
  );
}

function Words() {
  const [text, setText] = useState<string | null>(null);
  const [path, setPath] = useState("");
  useEffect(() => { api<{ text: string; path: string }>("replacements").then((r) => { setText(r.text); setPath(r.path); }); }, []);
  if (text === null) return null;
  return (
    <Card title="Word fixes" aside={<span className="font-mono text-xs text-text-tertiary">{path}</span>}>
      <div className="space-y-3 p-5">
        <p className="text-xs text-text-tertiary">
          One <code className="font-mono">wrong =&gt; right</code> per line: whole words, any case, applied to every
          dictation. Also works for snippets (<code className="font-mono">my email =&gt; you@example.com</code>).
        </p>
        <Textarea aria-label="Replacements" value={text} onChange={setText} rows={14} resize="vertical"
          fieldClassName="font-mono" />
        <div className="flex justify-end">
          <Button leadingIcon={RiCheckLine}
            onClick={() => api("replacements", { method: "PUT", body: { text } })
              .then(() => toast("Word fixes saved", { status: "success", duration: 1800 }))
              .catch((e) => toast("Couldn't save", { status: "error", description: String(e.message) }))}>
            Save
          </Button>
        </div>
      </div>
    </Card>
  );
}

const MODE_CHIP = { raw: ["neutral", "dictate"], clean: ["yellow", "cleanup"], command: ["purple", "command"] } as const;

function History() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  useEffect(() => {
    const load = () => api<HistoryItem[]>("history").then(setItems).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);
  return (
    <Card title="Recent dictations" aside={<span className="text-xs text-text-tertiary">kept in memory only · last 50</span>}>
      {items.length === 0 && <p className="px-5 py-8 text-center text-sm text-text-tertiary">Nothing yet. Press Home and talk.</p>}
      {items.map((h) => {
        const [color, label] = MODE_CHIP[h.mode];
        return (
          <div key={h.time} className="group flex items-start gap-4 px-5 py-3.5">
            <div className="w-24 shrink-0 space-y-1.5 pt-0.5">
              <div className="text-xs text-text-tertiary">{new Date(h.time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
              <Chip color={color}>{label}</Chip>
            </div>
            <p className="min-w-0 flex-1 whitespace-pre-wrap text-sm text-text-primary">{h.text}</p>
            <div className="flex shrink-0 items-center gap-2">
              <span className="text-xs text-text-tertiary">{h.app}</span>
              <Button variant="ghost" size="small" iconOnly leadingIcon={RiFileCopyLine} aria-label="Copy"
                onClick={() => navigator.clipboard.writeText(h.text).then(() => toast("Copied", { duration: 1200 }))} />
            </div>
          </div>
        );
      })}
    </Card>
  );
}

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [needsRestart, setNeedsRestart] = useState(false);
  const savedToast = useRef<number | string | undefined>(undefined);

  useEffect(() => {
    api<Settings>("settings").then(setSettings).catch((e) => setError(e.message));
    const poll = () => api<Status>("status").then(setStatus).catch(() => setStatus(null));
    poll();
    const t = setInterval(poll, 2000);
    return () => clearInterval(t);
  }, []);

  const update = useCallback((s: Setting, v: Value) => {
    api<{ values: Settings["values"] }>("settings", { method: "PUT", body: { [s.name]: v } })
      .then((r) => {
        setSettings((cur) => cur && { ...cur, values: r.values });
        if (s.restart) setNeedsRestart(true);
        savedToast.current = toast(s.restart ? "Saved · restart to apply" : "Saved", {
          id: "saved", status: "success", duration: 1500,
        });
      })
      .catch((e) => toast(`Couldn't save ${s.label}`, { status: "error", description: String(e.message) }));
  }, []);

  const restart = () => {
    api("restart", { method: "POST" }).then(() => {
      setNeedsRestart(false);
      toast("Restarting speakit…", { duration: 2500 });
    });
  };

  if (error)
    return (
      <main className="grid min-h-screen place-items-center p-8 text-center">
        <div className="space-y-2">
          <p className="text-sm text-text-primary">Can't reach speakit: {error}</p>
          <p className="text-xs text-text-tertiary">Open settings with <code className="font-mono">speakit-toggle settings</code>.</p>
        </div>
      </main>
    );
  if (!settings) return null;

  const section = (id: string) => (
    <Card key={id} title={SECTION_TITLES[id]}
      aside={id === "recording" ? <Button variant="secondary" size="xs" leadingIcon={RiVolumeUpLine}
        onClick={() => api("test-sound", { method: "POST" })}>Test sounds</Button> : undefined}>
      {settings.schema.filter((s) => s.section === id).map((s) => {
        const env = settings.env.includes(s.name);
        return (
          <Row key={s.name} label={s.label} help={env ? `Set by SPEAKIT_${s.name} in the environment.` : s.help}
            badge={s.restart ? <Chip color="soft">restart</Chip> : undefined}>
            <Control s={s} value={settings.values[s.name]} disabled={env} onChange={(v) => update(s, v)} />
          </Row>
        );
      })}
    </Card>
  );

  return (
    <main className="mx-auto max-w-4xl px-8 py-7">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="grid size-9 place-items-center rounded-xl bg-background-primary-default text-text-white"><RiMicLine className="size-5" /></div>
          <div>
            <h1 className="text-base font-semibold text-text-primary">speakit</h1>
            <p className="text-xs text-text-tertiary">Local voice-to-text · {settings.path}</p>
          </div>
        </div>
        <StatusBar status={status} />
      </header>

      {needsRestart && (
        <div className="mb-5 flex items-center justify-between rounded-xl border border-border-button-default bg-background-tertiary-default px-4 py-3">
          <span className="text-sm text-text-secondary">Some changes apply after a restart (about 3 seconds).</span>
          <Button size="small" leadingIcon={RiRestartLine} onClick={restart}>Restart speakit</Button>
        </div>
      )}

      <Tabs defaultSelectedKey={new URLSearchParams(location.search).get("tab") ?? "general"}>
        <TabList aria-label="Settings">
          {TABS.map((t) => <Tab key={t.id} id={t.id}>{t.label}</Tab>)}
        </TabList>
        {TABS.map((t) => (
          <TabPanel key={t.id} id={t.id} className="mt-5 space-y-5 outline-none">
            {t.id === "general" && <Keys />}
            {t.sections.map(section)}
            {t.id === "cleanup" && (
              <Card title="Per-app tone">
                <p className="px-5 py-4 text-xs leading-relaxed text-text-tertiary">
                  Cleanup and command mode read the focused window: terminals and Claude Code get backticked commands
                  and file paths, chat apps (WhatsApp, Slack, Discord, Telegram) a casual tone, email (Gmail,
                  Thunderbird, Outlook) polished paragraphs.
                </p>
              </Card>
            )}
            {t.id === "words" && <Words />}
            {t.id === "history" && <History />}
          </TabPanel>
        ))}
      </Tabs>
      <Toaster position="bottom-end" />
    </main>
  );
}
