import { useCallback, useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import {
  RiBookOpenLine, RiCpuLine, RiFileCopyLine, RiHistoryLine, RiKeyboardBoxLine, RiMicLine,
  RiRestartLine, RiSettings3Line, RiSparkling2Line, RiVolumeUpLine,
} from "@remixicon/react";
import { Tab, TabList, TabPanel, Tabs, type Key } from "react-aria-components";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NumberField } from "@/components/base/number-field/number-field";
import { Select, SelectItem } from "@/components/base/select/select";
import { Switch } from "@/components/base/switch/switch";
import { Textarea } from "@/components/base/textarea/textarea";
import { Toaster, toast } from "@/components/base/toast/toast";
import { cx } from "@/utils/cx";
import { api, type HistoryItem, type Setting, type Settings, type Status, type Value } from "./api";

type Icon = ComponentType<{ className?: string }>;
const PAGES: { id: string; label: string; icon: Icon; title: string; blurb: string; sections: string[] }[] = [
  { id: "general", label: "General", icon: RiSettings3Line, title: "General",
    blurb: "How recording starts, stops and sounds.", sections: ["recording", "feedback"] },
  { id: "typing", label: "Typing", icon: RiKeyboardBoxLine, title: "Typing",
    blurb: "How text reaches the focused window.", sections: ["typing"] },
  { id: "cleanup", label: "Cleanup", icon: RiSparkling2Line, title: "Cleanup",
    blurb: "The local model behind Insert and End.", sections: ["cleanup"] },
  { id: "words", label: "Word fixes", icon: RiBookOpenLine, title: "Word fixes",
    blurb: "Names and jargon the speech model gets wrong.", sections: [] },
  { id: "history", label: "History", icon: RiHistoryLine, title: "History",
    blurb: "Your last 50 dictations. Kept in memory, cleared on restart.", sections: [] },
  { id: "model", label: "Speech model", icon: RiCpuLine, title: "Speech model",
    blurb: "Changes here take effect after a restart.", sections: ["model"] },
];
const SECTION_TITLES: Record<string, string> = { recording: "Recording", feedback: "Feedback" };

function Group({ title, action, children }: { title?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section>
      {(title || action) && (
        <div className="mb-2 flex h-7 items-end justify-between px-4">
          <h2 className="text-[13px] font-medium text-text-secondary">{title}</h2>
          {action}
        </div>
      )}
      <div className="rows rounded-xl bg-neutral-900 shadow-[0_0_0_1px_rgb(255_255_255/0.05),0_1px_3px_rgb(0_0_0/0.3)]">
        {children}
      </div>
    </section>
  );
}

function Row({ label, help, children, badge }: { label: string; help?: string; children?: ReactNode; badge?: ReactNode }) {
  return (
    <div className="flex min-h-[56px] items-center justify-between gap-8 px-4 py-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-sm text-text-primary">{label}{badge}</div>
        {help && <p className="mt-0.5 text-[12.5px] leading-snug text-pretty text-text-tertiary">{help}</p>}
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
        onSelectionChange={(k) => k != null && onChange(String(k))} className="w-60">
        {s.choices.map((c) => <SelectItem key={c} id={c}>{c || "Full precision"}</SelectItem>)}
      </Select>
    );
  if (typeof s.default === "number")
    return (
      <NumberField aria-label={s.label} value={Number(value)} isDisabled={disabled} className="w-32 tabular-nums"
        formatOptions={{ useGrouping: false, maximumFractionDigits: 2 }}
        minValue={s.min ?? undefined} maxValue={s.max ?? undefined}
        step={s.name === "HOLD_SECONDS" || !Number.isInteger(s.default) ? 0.1 : 1}
        onChange={(v) => !Number.isNaN(v) && v !== value && onChange(v)} />
    );
  return (
    <Input aria-label={s.label} value={draft} onChange={setDraft} isDisabled={disabled} className="w-56"
      placeholder={s.name === "MIC_TARGET" ? "System default" : undefined}
      onBlur={() => draft !== value && onChange(draft)}
      onKeyDown={(e) => e.key === "Enter" && draft !== value && onChange(draft)} />
  );
}

// The LED colours match the waybar indicator for each mode.
const KEYS = [
  { key: "Home", title: "Dictate", text: "Types what you say, minus the ums.", led: ["#ff5555"] },
  { key: "Insert", title: "Clean up", text: "Fixes grammar and self-corrections, formats lists.", led: ["#ff5555", "#e5a04b"] },
  { key: "End", title: "Command", text: "Rewrites the selection the way you ask, or writes something new.", led: ["#e5a04b"] },
];

function Keys() {
  return (
    <section>
      <div className="grid grid-cols-3 gap-3">
        {KEYS.map(({ key, title, text, led }) => (
          <div key={key} className="rounded-2xl bg-neutral-900 p-4 shadow-[0_0_0_1px_rgb(255_255_255/0.05),0_1px_3px_rgb(0_0_0/0.3)]">
            <div className="flex items-start justify-between">
              <kbd className="keycap">{key}</kbd>
              <span className="flex gap-1 pt-1">
                {led.map((c) => <span key={c} className="size-1.5 rounded-full" style={{ background: c, boxShadow: `0 0 6px ${c}` }} />)}
              </span>
            </div>
            <div className="mt-4 text-sm font-medium text-text-primary">{title}</div>
            <p className="mt-1 text-[12.5px] leading-snug text-pretty text-text-tertiary">{text}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 px-4 text-[12.5px] text-text-tertiary">
        Tap to start and tap again to stop, or hold while you talk. Rebind in hyprland.conf.
      </p>
    </section>
  );
}

function Words() {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => { api<{ text: string }>("replacements").then((r) => setText(r.text)); }, []);
  if (text === null) return null;
  return (
    <Group>
      <div className="space-y-3 p-4">
        <p className="text-[12.5px] text-text-tertiary">
          One fix per line, written <code className="text-text-secondary">heard =&gt; meant</code>. Matches whole words
          in any case, and works for snippets too.
        </p>
        <Textarea aria-label="Word fixes" value={text} onChange={setText} rows={14} resize="vertical" fieldClassName="font-mono text-[13px]" />
        <div className="flex justify-end">
          <Button size="small" onClick={() => api("replacements", { method: "PUT", body: { text } })
            .then(() => toast("Word fixes saved", { status: "success", duration: 1800 }))
            .catch((e) => toast("Word fixes not saved", { status: "error", description: String(e.message) }))}>
            Save word fixes
          </Button>
        </div>
      </div>
    </Group>
  );
}

const MODE = { raw: ["Dictate", "#ff5555"], clean: ["Clean up", "#e5a04b"], command: ["Command", "#e5a04b"] } as const;

function History() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  useEffect(() => {
    const load = () => api<HistoryItem[]>("history").then(setItems).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);
  if (!items.length)
    return <Group><p className="px-4 py-10 text-center text-sm text-text-tertiary">Nothing yet. Press Home and start talking.</p></Group>;
  return (
    <Group>
      {items.map((h) => {
        const [label, color] = MODE[h.mode];
        return (
          <div key={h.time} className="flex items-start gap-4 px-4 py-3">
            <div className="w-20 shrink-0 pt-0.5 text-[12.5px] text-text-tertiary tabular-nums">
              {new Date(h.time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              <div className="mt-1 flex items-center gap-1.5"><span className="size-1.5 rounded-full" style={{ background: color }} />{label}</div>
            </div>
            <p className="min-w-0 flex-1 text-sm whitespace-pre-wrap text-pretty text-text-primary">{h.text}</p>
            <Button variant="secondary" size="xs" iconOnly leadingIcon={RiFileCopyLine} aria-label="Copy text"
              onClick={() => navigator.clipboard.writeText(h.text).then(() => toast("Copied", { duration: 1200 }))} />
          </div>
        );
      })}
    </Group>
  );
}

function Light({ on, warn, children }: { on: boolean; warn?: boolean; children: ReactNode }) {
  return (
    <div className="flex items-center gap-2.5 text-[12.5px] text-text-secondary">
      <span className={cx("size-1.5 rounded-full", on ? "bg-[#5fd38d]" : warn ? "bg-neutral-500" : "bg-[#ff5555]")} />
      {children}
    </div>
  );
}

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [needsRestart, setNeedsRestart] = useState(false);
  const [page, setPage] = useState<Key>(new URLSearchParams(location.search).get("tab") ?? "general");
  const [pillY, setPillY] = useState(0);
  const nav = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // react-aria renders the tab collection a pass later, so measure next frame.
    const f = requestAnimationFrame(() => {
      const tab = nav.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
      if (tab) setPillY(tab.offsetTop);
    });
    scroller.current?.scrollTo({ top: 0 });
    return () => cancelAnimationFrame(f);
  }, [page, settings]);

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
        toast(s.restart ? "Saved. Restart to apply." : "Saved", { id: "saved", status: "success", duration: 1500 });
      })
      .catch((e) => toast(`${s.label} not saved`, { status: "error", description: String(e.message) }));
  }, []);

  if (error)
    return (
      <main className="grid min-h-screen place-items-center p-8 text-center">
        <div className="space-y-1">
          <p className="text-sm text-text-primary">speakit isn't reachable ({error}).</p>
          <p className="text-[12.5px] text-text-tertiary">Open settings with speakit-toggle settings.</p>
        </div>
      </main>
    );
  if (!settings) return null;

  const section = (id: string) => (
    <Group key={id} title={SECTION_TITLES[id]}
      action={id === "recording" ? <Button variant="secondary" size="xs" leadingIcon={RiVolumeUpLine}
        onClick={() => api("test-sound", { method: "POST" })}>Play sounds</Button> : undefined}>
      {settings.schema.filter((s) => s.section === id).map((s) => {
        const env = settings.env.includes(s.name);
        return (
          <Row key={s.name} label={s.label} help={env ? `Locked by SPEAKIT_${s.name} in the environment.` : s.help}>
            <Control s={s} value={settings.values[s.name]} disabled={env} onChange={(v) => update(s, v)} />
          </Row>
        );
      })}
    </Group>
  );

  return (
    <Tabs orientation="vertical" selectedKey={page} onSelectionChange={setPage} className="grid h-screen grid-cols-[228px_1fr]">
      <aside className="flex flex-col border-r border-black/40 bg-neutral-950 px-3 py-5">
        <div className="mb-6 flex items-center gap-3 px-2">
          <div className="grid size-8 place-items-center rounded-[9px] bg-linear-to-b from-accent-400 to-accent-600 text-(--on-accent) shadow-[inset_0_1px_0_rgb(255_255_255/0.25),inset_0_-2px_0_rgb(0_0_0/0.2)]">
            <RiMicLine className="size-4" />
          </div>
          <div className="text-[15px] font-semibold tracking-[-0.01em] text-text-primary">speakit</div>
        </div>
        <div ref={nav} className="relative">
          {/* One highlight that glides to the selected item (transform only, so it can be retargeted mid-move). */}
          <div aria-hidden className="nav-pill absolute inset-x-0 top-0 h-9 rounded-lg bg-neutral-800 shadow-[inset_0_1px_0_rgb(255_255_255/0.04)]"
            style={{ transform: `translateY(${pillY}px)` }} />
          <TabList aria-label="Settings" className="relative flex flex-col gap-0.5">
            {PAGES.map(({ id, label, icon: I }) => (
              <Tab key={id} id={id} className={({ isSelected, isFocusVisible }) => cx(
                "flex h-9 cursor-default items-center gap-2.5 rounded-lg px-2.5 text-sm outline-none transition-[color,background-color] duration-150 active:scale-[0.98]",
                isSelected ? "text-text-primary" : "text-text-secondary hover:bg-neutral-900/60 hover:text-text-primary",
                isFocusVisible && "ring-2 ring-accent-500",
              )}>
                {({ isSelected }) => <><I className={cx("size-4 transition-colors duration-200", isSelected ? "text-accent-400" : "text-text-tertiary")} />{label}</>}
              </Tab>
            ))}
          </TabList>
        </div>
        <div className="mt-auto space-y-2 px-2.5">
          {status ? (
            <>
              <Light on={status.state !== "recording"}>{status.state === "recording" ? "Recording" : "Ready to listen"}</Light>
              <Light on={status.model_ready} warn>{status.model_ready ? `Speech model on ${status.device.toUpperCase()}` : "Speech model loading"}</Light>
              <Light on={status.llm}>{status.llm ? "Cleanup model running" : "Cleanup model stopped"}</Light>
            </>
          ) : <Light on={false}>speakit isn't running</Light>}
        </div>
      </aside>

      <div ref={scroller} className="overflow-y-auto">
        {PAGES.map((p) => (
          <TabPanel key={p.id} id={p.id} className="page mx-auto max-w-[680px] px-10 pt-10 pb-16 outline-none">
            <header className="mb-7">
              <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.02em] text-text-primary">{p.title}</h1>
              <p className="mt-1 text-sm text-text-secondary">{p.blurb}</p>
            </header>
            {needsRestart && p.id === "model" && (
              <div className="mb-6 flex items-center justify-between rounded-xl bg-accent-950 px-4 py-3 shadow-[0_0_0_1px_var(--color-accent-800)]">
                <span className="text-sm text-accent-200">Restart speakit to use the new model settings.</span>
                <Button size="small" leadingIcon={RiRestartLine} onClick={() => api("restart", { method: "POST" })
                  .then(() => { setNeedsRestart(false); toast("Restarting speakit", { duration: 2500 }); })}>Restart</Button>
              </div>
            )}
            <div className="page-body space-y-7">
              {p.id === "general" && <Keys />}
              {p.sections.map(section)}
              {p.id === "cleanup" && (
                <Group title="Tone by app">
                  <Row label="Terminals and Claude Code" help="Commands, flags and file paths in backticks." />
                  <Row label="WhatsApp, Slack, Discord, Telegram" help="Casual, short sentences." />
                  <Row label="Gmail, Thunderbird, Outlook" help="Polished paragraphs." />
                </Group>
              )}
              {p.id === "words" && <Words />}
              {p.id === "history" && <History />}
            </div>
          </TabPanel>
        ))}
      </div>
      <Toaster position="bottom-end" />
    </Tabs>
  );
}
