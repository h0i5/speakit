//! speakit: native settings window for the speakit daemon.
mod api;
mod theme;
mod widgets;

use api::{Api, Item, Saved, Settings, Stats, Status, Words};
use gpui::prelude::*;
use gpui::{
    AnyElement, App, ClickEvent, ClipboardItem, Context, Entity, Focusable, FontWeight, SharedString, StyledText, Subscription, TextRun, Window, WindowBounds,
    WindowOptions, div, font, px, size,
};
use gpui_component::input::{Input, InputEvent, InputState, Textarea, TextareaState};
use gpui_component::scroll::ScrollableElement;
use gpui_component::select::{Select, SelectEvent, SelectItem, SelectState};
use gpui_component::{ActiveTheme, Root};
use serde::de::DeserializeOwned;
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::time::{Duration, Instant};
use theme::*;
use widgets::*;

struct Page {
    id: &'static str,
    label: &'static str,
    icon: &'static str,
    blurb: &'static str,
    sections: &'static [&'static str],
}

const PAGES: [Page; 6] = [
    Page { id: "general", label: "General", icon: "settings", blurb: "How recording starts, stops and sounds.", sections: &["recording", "feedback"] },
    Page { id: "typing", label: "Typing", icon: "keyboard", blurb: "How text reaches the focused window.", sections: &["typing"] },
    Page { id: "cleanup", label: "Cleanup", icon: "sparkling", blurb: "The local model behind Insert and End.", sections: &["cleanup"] },
    Page { id: "words", label: "Word fixes", icon: "book", blurb: "Names and jargon the speech model gets wrong.", sections: &[] },
    Page { id: "history", label: "History", icon: "history", blurb: "Your recent dictations, and what talking has saved you.", sections: &["history"] },
    Page { id: "model", label: "Speech model", icon: "cpu", blurb: "Changes here take effect after a restart.", sections: &["model"] },
];
const WORDS: usize = 3;
const HISTORY: usize = 4;
const MODEL: usize = 5;

// (key, title, text, LEDs); the LED colours match the waybar indicator.
const KEYS: [(&str, &str, &str, &[fn() -> gpui::Hsla]); 3] = [
    ("Home", "Dictate", "Types what you say, minus the ums.", &[red]),
    ("Insert", "Clean up", "Fixes grammar and self-corrections, formats lists.", &[red, gold]),
    ("End", "Command", "Rewrites the selection the way you ask, or writes something new.", &[gold]),
];
const TONES: [(&str, &str); 3] = [
    ("Terminals and Claude Code", "Commands, flags and file paths in backticks."),
    ("WhatsApp, Slack, Discord, Telegram", "Casual, short sentences."),
    ("Gmail, Thunderbird, Outlook", "Polished paragraphs."),
];

/// cubic-bezier(0.2, 0, 0, 1), the web UI's motion curve.
fn ease(x: f32) -> f32 {
    let x = x.clamp(0.0, 1.0);
    let (mut lo, mut hi) = (0.0f32, 1.0f32);
    for _ in 0..24 {
        let s = (lo + hi) / 2.0;
        let xs = 3.0 * (1.0 - s).powi(2) * s * 0.2 + s.powi(3);
        if xs < x { lo = s } else { hi = s }
    }
    let s = (lo + hi) / 2.0;
    3.0 * (1.0 - s) * s * s + s.powi(3)
}

fn progress(now: Instant, start: Instant, delay_ms: u64, ms: u64) -> f32 {
    let t = now.saturating_duration_since(start).as_secs_f32() - delay_ms as f32 / 1000.0;
    ease(t / (ms as f32 / 1000.0))
}

/// The sidebar pill's y: retargets from wherever it is mid-move.
struct Glide {
    from: f32,
    to: f32,
    at: Instant,
}

impl Glide {
    fn value(&self, now: Instant, ms: u64) -> f32 {
        self.from + (self.to - self.from) * progress(now, self.at, 0, ms)
    }
}


/// Hover/focus fade, like the web UI's 150 ms transition.
const RING_MS: u64 = 150;

#[derive(Clone, Copy, PartialEq)]
enum Tone {
    Neutral,
    Success,
    Error,
}

struct Toast {
    title: SharedString,
    description: Option<SharedString>,
    tone: Tone,
    at: Instant,
    duration: Duration,
}

/// A dropdown entry; the empty choice reads "Full precision".
#[derive(Clone)]
struct Choice(SharedString);

impl SelectItem for Choice {
    type Value = SharedString;

    fn title(&self) -> SharedString {
        if self.0.is_empty() { "Full precision".into() } else { self.0.clone() }
    }

    fn value(&self) -> &SharedString {
        &self.0
    }
}

type Dropdown = Entity<SelectState<Vec<Choice>>>;

struct SettingsWindow {
    api: Api,
    page: usize,
    settings: Option<Settings>,
    status: Option<Status>,
    down: bool,
    inputs: HashMap<String, Entity<InputState>>,
    selects: HashMap<String, Dropdown>,
    words: Option<Entity<TextareaState>>,
    history: Vec<Item>,
    stats: Option<Stats>,
    needs_restart: bool,
    toast: Option<Toast>,
    pill: Glide,
    page_at: Instant,
    ticks: u32,
    subscriptions: Vec<Subscription>,
    /// Hover/focus level per element (0 idle, 1 hover, 2 focus), eased between levels.
    rings: HashMap<SharedString, Glide>,
    hovered: std::collections::HashSet<SharedString>,
    /// Key-card easter egg: a tapped keycap latches like a recording.
    latched: [bool; 3],
    key_at: [Instant; 3],
}

impl SettingsWindow {
    fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let page = std::env::args().nth(1).and_then(|a| PAGES.iter().position(|p| p.id == a)).unwrap_or(0);
        let past = Instant::now() - Duration::from_secs(1);
        let this = Self {
            api: Api::new(),
            page,
            settings: None,
            status: None,
            down: false,
            inputs: HashMap::new(),
            selects: HashMap::new(),
            words: None,
            history: Vec::new(),
            stats: None,
            needs_restart: false,
            toast: None,
            pill: Glide { from: 0.0, to: page as f32 * 34.0, at: past },
            page_at: past,
            ticks: 0,
            subscriptions: Vec::new(),
            rings: HashMap::new(),
            hovered: Default::default(),
            latched: [false; 3],
            key_at: [past; 3],
        };
        this.load_status(window, cx);
        this.load_settings(window, cx);
        this.load_page(window, cx);
        cx.spawn_in(window, async move |this, cx| {
            loop {
                cx.background_executor().timer(Duration::from_secs(1)).await;
                if this.update_in(cx, |this, window, cx| this.tick(window, cx)).is_err() {
                    break;
                }
            }
        })
        .detach();
        this
    }

    /// Runs a blocking API call off the main thread, then `done` back on it.
    fn request<T: DeserializeOwned + Send + 'static>(
        &self,
        method: &'static str,
        path: &'static str,
        body: Option<Value>,
        window: &mut Window,
        cx: &mut Context<Self>,
        done: impl FnOnce(&mut Self, Result<T, String>, &mut Window, &mut Context<Self>) + 'static,
    ) {
        let api = self.api.clone();
        let call = cx.background_executor().spawn(async move { api.call::<T>(method, path, body) });
        cx.spawn_in(window, async move |this, cx| {
            let result = call.await;
            this.update_in(cx, |this, window, cx| {
                done(this, result, window, cx);
                cx.notify();
            })
            .ok();
        })
        .detach();
    }

    fn tick(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.ticks += 1;
        if self.ticks % 2 == 0 {
            self.load_status(window, cx);
        }
        if self.page == HISTORY && self.ticks % 3 == 0 {
            self.load_page(window, cx);
        }
    }

    fn load_status(&self, window: &mut Window, cx: &mut Context<Self>) {
        self.request("GET", "status", None, window, cx, |this, r: Result<Status, String>, window, cx| match r {
            Ok(s) => {
                this.status = Some(s);
                if std::mem::take(&mut this.down) || this.settings.is_none() {
                    this.load_settings(window, cx);
                    this.load_page(window, cx);
                }
            }
            Err(_) => {
                this.status = None;
                this.down = true;
            }
        });
    }

    fn load_settings(&self, window: &mut Window, cx: &mut Context<Self>) {
        self.request("GET", "settings", None, window, cx, |this, r: Result<Settings, String>, window, cx| match r {
            Ok(s) => {
                this.settings = Some(s);
                this.build_controls(window, cx);
                this.sync(window, cx);
            }
            Err(_) => this.down = true,
        });
    }

    /// Word fixes and history load when their page opens (history also polls).
    fn load_page(&self, window: &mut Window, cx: &mut Context<Self>) {
        match self.page {
            WORDS => self.request("GET", "replacements", None, window, cx, |this, r: Result<Words, String>, window, cx| {
                let Ok(w) = r else { return };
                match &this.words {
                    Some(state) => state.update(cx, |s, cx| s.set_value(w.text, window, cx)),
                    None => this.words = Some(cx.new(|cx| TextareaState::new(window, cx).default_value(w.text))),
                }
            }),
            HISTORY => {
                self.request("GET", "history", None, window, cx, |this, r: Result<Vec<Item>, String>, _, _| {
                    if let Ok(items) = r {
                        this.history = items;
                    }
                });
                self.request("GET", "stats", None, window, cx, |this, r: Result<Stats, String>, _, _| {
                    this.stats = r.ok();
                });
            }
            _ => {}
        }
    }

    /// One text field per string/number setting and one dropdown per choice setting.
    fn build_controls(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(settings) = &self.settings else { return };
        for s in settings.schema.clone() {
            let name = s.name.clone();
            if !s.choices.is_empty() {
                if self.selects.contains_key(&name) {
                    continue;
                }
                let choices: Vec<Choice> = s.choices.iter().map(|c| Choice(c.clone().into())).collect();
                let state = cx.new(|cx| SelectState::new(choices, None, window, cx));
                self.subscriptions.push(cx.subscribe_in(&state, window, move |this, _, e: &SelectEvent<Vec<Choice>>, window, cx| {
                    if let SelectEvent::Confirm(Some(v)) = e {
                        this.save(name.clone(), Value::String(v.to_string()), window, cx);
                    }
                }));
                self.selects.insert(s.name, state);
            } else if (s.default.is_number() || s.default.is_string()) && !self.inputs.contains_key(&name) {
                let placeholder = if name == "MIC_TARGET" { "System default" } else { "" };
                let state = cx.new(|cx| InputState::new(window, cx).placeholder(placeholder));
                self.subscriptions.push(cx.subscribe_in(&state, window, move |this, _, e: &InputEvent, window, cx| {
                    if matches!(e, InputEvent::PressEnter { .. } | InputEvent::Blur) {
                        this.commit(&name, window, cx);
                    }
                }));
                self.inputs.insert(s.name, state);
            }
        }
    }

    /// Shows the daemon's values in every field that isn't being edited.
    fn sync(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(settings) = &self.settings else { return };
        for (name, state) in &self.inputs {
            if state.read(cx).focus_handle(cx).is_focused(window) {
                continue;
            }
            let shown = display(&settings.values[name]);
            if state.read(cx).value() != shown {
                state.update(cx, |s, cx| s.set_value(shown, window, cx));
            }
        }
        for (name, state) in &self.selects {
            let v: SharedString = settings.values[name].as_str().unwrap_or("").to_string().into();
            state.update(cx, |s, cx| s.set_selected_value(&v, window, cx));
        }
    }

    fn setting(&self, name: &str) -> Option<(&api::Setting, &Value)> {
        let s = self.settings.as_ref()?;
        Some((s.schema.iter().find(|x| x.name == name)?, s.values.get(name)?))
    }

    /// A typed number, clamped and rounded to the setting's type.
    fn number(&self, name: &str, raw: f64) -> Option<Value> {
        let (s, _) = self.setting(name)?;
        let v = raw.clamp(s.min.unwrap_or(f64::MIN), s.max.unwrap_or(f64::MAX));
        Some(if s.default.is_f64() { Value::from((v * 100.0).round() / 100.0) } else { Value::from(v.round() as i64) })
    }

    /// Enter or focus loss in a text field: save it if it changed, else restore it.
    fn commit(&mut self, name: &str, window: &mut Window, cx: &mut Context<Self>) {
        let (Some(state), Some((s, current))) = (self.inputs.get(name), self.setting(name)) else { return };
        let draft = state.read(cx).value().to_string();
        let value = if s.default.is_number() { draft.trim().parse().ok().and_then(|f| self.number(name, f)) } else { Some(Value::String(draft)) };
        match value {
            Some(v) if v != *current => self.save(name.to_string(), v, window, cx),
            _ => self.sync(window, cx),
        }
    }

    fn step(&mut self, name: &str, delta: f64, window: &mut Window, cx: &mut Context<Self>) {
        let Some((_, current)) = self.setting(name) else { return };
        let current = current.clone();
        let typed = self.inputs.get(name).and_then(|s| s.read(cx).value().trim().parse::<f64>().ok());
        if let Some(v) = self.number(name, typed.or(current.as_f64()).unwrap_or(0.0) + delta).filter(|v| *v != current) {
            self.save(name.to_string(), v, window, cx);
        }
    }

    fn save(&mut self, name: String, value: Value, window: &mut Window, cx: &mut Context<Self>) {
        let (label, restart) = self.setting(&name).map(|(s, _)| (s.label.clone(), s.restart)).unwrap_or_default();
        let body = Value::Object(Map::from_iter([(name, value)]));
        self.request("PUT", "settings", Some(body), window, cx, move |this, r: Result<Saved, String>, window, cx| {
            match r {
                Ok(saved) => {
                    if let Some(s) = &mut this.settings {
                        s.values = saved.values;
                    }
                    this.needs_restart |= restart;
                    this.notify(if restart { "Saved. Restart to apply." } else { "Saved" }, None, Tone::Success, 1500, window, cx);
                }
                Err(e) => this.notify(format!("{label} not saved"), Some(e), Tone::Error, 5000, window, cx),
            }
            this.sync(window, cx);
        });
    }

    fn notify(&mut self, title: impl Into<SharedString>, description: Option<String>, tone: Tone, ms: u64, window: &mut Window, cx: &mut Context<Self>) {
        let at = Instant::now();
        self.toast = Some(Toast { title: title.into(), description: description.map(Into::into), tone, at, duration: Duration::from_millis(ms) });
        cx.spawn_in(window, async move |this, cx| {
            cx.background_executor().timer(Duration::from_millis(ms)).await;
            this.update(cx, |this, cx| {
                if this.toast.as_ref().is_some_and(|t| t.at == at) {
                    this.toast = None;
                    cx.notify();
                }
            })
            .ok();
        })
        .detach();
        cx.notify();
    }

    fn ring(&self, key: &str, now: Instant) -> f32 {
        self.rings.get(key).map_or(0., |g| g.value(now, RING_MS))
    }

    fn hover(&self, key: SharedString, cx: &mut Context<Self>) -> impl Fn(&bool, &mut Window, &mut App) + 'static {
        cx.listener(move |this, on: &bool, _, cx| {
            if *on { this.hovered.insert(key.clone()) } else { this.hovered.remove(&key) };
            cx.notify();
        })
    }

    /// Eases every hover/focus level towards its target; true while any is moving.
    fn retarget(&mut self, now: Instant, window: &Window, cx: &App) -> bool {
        // Every key with a level too: one that just lost hover must still fade back to 0.
        let keys: Vec<SharedString> =
            self.inputs.keys().map(|k| SharedString::from(k.clone())).chain(self.hovered.iter().cloned()).chain(self.rings.keys().cloned()).collect();
        for k in keys {
            let focused = self.inputs.get(k.as_ref()).is_some_and(|s| s.read(cx).focus_handle(cx).is_focused(window));
            let to = if focused { 2. } else if self.hovered.contains(&k) { 1. } else { 0. };
            let g = self.rings.entry(k).or_insert(Glide { from: 0., to: 0., at: now });
            if g.to != to {
                *g = Glide { from: g.value(now, RING_MS), to, at: now };
            }
        }
        self.rings.values().any(|g| now.saturating_duration_since(g.at) < Duration::from_millis(RING_MS + 20))
    }

    /// Easter egg: tapping a keycap works like the real key. First tap latches it (start thock,
    /// LEDs blink like waybar's REC); the next releases it (stop thock).
    fn tap_key(&mut self, i: usize, window: &mut Window, cx: &mut Context<Self>) {
        self.latched[i] = !self.latched[i];
        self.key_at[i] = Instant::now();
        let sounds = self.setting("SOUNDS").is_none_or(|(_, v)| v.as_bool() != Some(false));
        if sounds && let Some(dir) = std::env::var_os("XDG_RUNTIME_DIR") {
            let wav = std::path::Path::new(&dir).join(if self.latched[i] { "speakit-start.wav" } else { "speakit-stop.wav" });
            std::thread::spawn(move || std::process::Command::new("pw-play").arg(wav).status());
        }
        if self.latched[i] {
            // Blink at the LED's own pace: one repaint per flip, not every frame.
            cx.spawn_in(window, async move |this, cx| {
                loop {
                    cx.background_executor().timer(Duration::from_millis(600)).await;
                    let on = this.update(cx, |this, cx| {
                        cx.notify();
                        this.latched[i]
                    });
                    if !on.unwrap_or(false) {
                        break;
                    }
                }
            })
            .detach();
        }
        cx.notify();
    }

    /// The key cards. Their keycaps are the easter egg (see `tap_key`).
    fn keys(&self, cx: &mut Context<Self>) -> impl IntoElement + use<> {
        let now = Instant::now();
        let cards = KEYS.iter().enumerate().map(|(i, &(key, title, text_, leds))| {
            let latched = self.latched[i];
            let rest = if latched { 0.5 } else { 0. };
            // After a tap the cap springs back from fully down to rest (half down while latched).
            let sink = rest + (1. - rest) * (1. - progress(now, self.key_at[i], 0, 220));
            // waybar's REC blink: lit for 51% of each 1.2 s.
            let lit = !latched || now.saturating_duration_since(self.key_at[i]).as_millis() % 1200 < 612;
            let leds = leds.iter().map(move |c| {
                let c = c();
                match (latched, lit) {
                    (true, true) => led(c).shadow(vec![shadow(0., 0., 12., 2., c, false)]),
                    (_, true) => led(c),
                    (_, false) => dot(c.opacity(0.25)),
                }
            });
            let hk = SharedString::from(format!("cap-{i}"));
            let cap = keycap(key, sink)
                .bg(vgrad(blend(n700(), n500(), 0.15 * self.ring(&hk, now)), n800()))
                .id(("cap", i))
                .on_hover(self.hover(hk, cx))
                .active(|s| s.bg(vgrad(n700(), n800())).top(px(2.)).shadow(keycap_shadow(1.)))
                .on_click(cx.listener(move |this, _: &ClickEvent, window, cx| this.tap_key(i, window, cx)));
            card()
                .flex_1()
                .min_w_0()
                .p(px(14.))
                .child(div().flex().items_start().justify_between().child(cap).child(div().flex().gap(px(4.)).pt(px(4.)).children(leds)))
                .child(text(title, 13., 19.5, n50()).font_weight(FontWeight::MEDIUM).mt(px(12.)))
                .child(text(text_, 12., 16.5, n600()).mt(px(2.)))
        });
        div()
            .flex()
            .flex_col()
            .gap(px(8.))
            .child(div().flex().gap(px(8.)).children(cards))
            .child(text("Tap to start and tap again to stop, or hold while you talk. Esc cancels a recording, or undoes a cleanup right after. Rebind in hyprland.conf.", 12., 18., n600()).px(px(14.)))
    }

    /// "Made by Harsh" at the foot of the sidebar (which never scrolls, so it
    /// can't sit on top of page content); the name links to harshiyer.in.
    fn credit(&self, now: Instant, cx: &mut Context<Self>) -> impl IntoElement + use<> {
        let t = self.ring("credit", now);
        div()
            .mt(px(14.))
            .pt(px(12.))
            .px(px(8.))
            .border_t_1()
            .border_color(white(0.06))
            .flex()
            .gap(px(3.))
            .child(text("Made by", 12., 16., n600()))
            .child(
                text("Harsh", 12., 16., blend(n500(), a400(), t))
                    .id("credit")
                    .cursor_pointer()
                    .on_hover(self.hover("credit".into(), cx))
                    .on_click(|_: &ClickEvent, _, cx| cx.open_url("https://harshiyer.in")),
            )
    }

    fn nav(&mut self, i: usize, window: &mut Window, cx: &mut Context<Self>) {
        if i == self.page {
            return;
        }
        let now = Instant::now();
        self.pill = Glide { from: self.pill.value(now, 260), to: i as f32 * 34.0, at: now };
        self.page_at = now;
        self.page = i;
        // Elements on the old page never get their hover-out; keep only the sidebar's.
        self.hovered.retain(|k| k.starts_with("nav-"));
        self.load_page(window, cx);
        cx.notify();
    }

    fn sidebar(&self, now: Instant, cx: &mut Context<Self>) -> impl IntoElement + use<> {
        let items = PAGES.iter().enumerate().map(|(i, p)| {
            let on = i == self.page;
            let key = SharedString::from(format!("nav-{i}"));
            let t = if on { 0. } else { self.ring(&key, now) };
            div()
                .id(("nav", i))
                .h(px(32.))
                .px(px(8.))
                .flex()
                .items_center()
                .gap(px(8.))
                .rounded(px(6.))
                .text_size(px(13.))
                .line_height(px(19.5))
                .text_color(if on { n50() } else { blend(n500(), n50(), t) })
                .bg(n900().opacity(0.6 * t))
                .on_hover(self.hover(key, cx))
                .on_click(cx.listener(move |this, _: &ClickEvent, window, cx| this.nav(i, window, cx)))
                .child(icon(p.icon, 16., if on { a400() } else { n600() }))
                .child(p.label)
        });
        let pill = div()
            .absolute()
            .top(px(self.pill.value(now, 260)))
            .left_0()
            .right_0()
            .h(px(32.))
            .rounded(px(6.))
            .bg(n800())
            .shadow(vec![shadow(0., 1., 0., 0., white(0.04), true)]);
        let lights: Vec<(gpui::Hsla, String)> = match &self.status {
            Some(s) => {
                let rec = s.state == "recording";
                vec![
                    (if rec { red() } else { green() }, if rec { "Recording" } else { "Ready" }.into()),
                    (if s.model_ready { green() } else { n500() }, if s.model_ready { format!("Speech on {}", s.device.to_uppercase()) } else { "Speech loading".into() }),
                    (if s.llm { green() } else { red() }, if s.llm { "Cleanup running" } else { "Cleanup stopped" }.into()),
                ]
            }
            None => vec![(red(), "speakit isn't running".into())],
        };
        let lights = lights.into_iter().map(|(c, label)| {
            div().flex().items_center().gap(px(8.)).child(div().size(px(16.)).flex().items_center().justify_center().child(dot(c))).child(text(label, 12., 18., n500()))
        });
        div()
            .w(px(176.))
            .h_full()
            .flex_shrink_0()
            .flex()
            .flex_col()
            .py(px(16.))
            .px(px(8.))
            .bg(n950())
            .border_r_1()
            .border_color(black(0.4))
            .child(
                div()
                    .h(px(32.))
                    .px(px(8.))
                    .mb(px(20.))
                    .flex()
                    .items_center()
                    .gap(px(8.))
                    .child(logo())
                    .child(text("speakit", 18., 18., n50()).font_weight(FontWeight::SEMIBOLD)),
            )
            .child(div().relative().child(pill).child(div().flex().flex_col().gap(px(2.)).children(items)))
            .child(div().mt_auto().px(px(8.)).flex().flex_col().gap(px(6.)).children(lights))
            .child(self.credit(now, cx))
    }

    fn content(&self, now: Instant, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement + use<> {
        let p = &PAGES[self.page];
        let h = progress(now, self.page_at, 0, 260);
        let b = progress(now, self.page_at, 50, 300);
        let header = div()
            .relative()
            .top(px(6. * (1. - h)))
            .opacity(h)
            .mb(px(20.))
            .child(text(p.label, 20., 25., n50()).font_weight(FontWeight::SEMIBOLD))
            .child(text(p.blurb, 13., 20., n500()).mt(px(2.)));
        let banner = (self.needs_restart && self.page == MODEL).then(|| {
            div()
                .mb(px(24.))
                .px(px(16.))
                .py(px(12.))
                .flex()
                .items_center()
                .justify_between()
                .rounded(px(12.))
                .bg(a950())
                .shadow(vec![shadow(0., 0., 0., 1., a800(), false)])
                .child(text("Restart speakit to use the new model settings.", 14., 20., a200()))
                .child(primary_button("restart", Some("restart"), "Restart", self.ring("restart", now)).on_hover(self.hover("restart".into(), cx)).on_click(cx.listener(|this, _: &ClickEvent, window, cx| {
                    this.needs_restart = false;
                    this.notify("Restarting speakit", None, Tone::Neutral, 2500, window, cx);
                    this.request("POST", "restart", None, window, cx, |_, _: Result<Value, String>, _, _| {});
                })))
        });
        let mut body: Vec<AnyElement> = Vec::new();
        if p.id == "general" {
            body.push(self.keys(cx).into_any_element());
        }
        for sec in p.sections {
            body.push(self.section(sec, window, cx).into_any_element());
        }
        match self.page {
            2 => body.push(group(Some("Tone by app"), None, TONES.iter().map(|(l, h)| row(*l, *h, None).into_any_element()).collect()).into_any_element()),
            WORDS => body.extend(self.words_page(cx)),
            HISTORY => {
                body.extend(self.stats_card());
                body.push(self.history_page(cx).into_any_element());
            }
            _ => {}
        }
        div()
            // Keyed by page, so each page opens scrolled to the top.
            .id(("content", self.page))
            .flex_1()
            .h_full()
            .min_w_0()
            .overflow_y_scrollbar()
            .child(
                div()
                    .px(px(24.))
                    .pt(px(20.))
                    .pb(px(32.))
                    .child(header)
                    .children(banner)
                    .child(div().relative().top(px(6. * (1. - b))).opacity(b).flex().flex_col().gap(px(20.)).children(body)),
            )
    }

    fn section(&self, sec: &'static str, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement + use<> {
        let Some(s) = &self.settings else { return div() };
        let rows = s
            .schema
            .iter()
            .filter(|x| x.section == sec)
            .map(|x| {
                let locked = s.env.contains(&x.name);
                let help = if locked { format!("Locked by SPEAKIT_{} in the environment.", x.name) } else { x.help.clone() };
                row(x.label.clone(), help, Some(self.control(x, &s.values[&x.name], locked, window, cx))).into_any_element()
            })
            .collect();
        let (title, action) = match sec {
            "recording" => (
                Some("Recording"),
                Some(
                    xs_button("test-sound", "volume", "Play sounds", self.ring("test-sound", Instant::now()))
                        .on_hover(self.hover("test-sound".into(), cx))
                        .on_click(cx.listener(|this, _: &ClickEvent, window, cx| this.request("POST", "test-sound", None, window, cx, |_, _: Result<Value, String>, _, _| {})))
                        .into_any_element(),
                ),
            ),
            "feedback" => (Some("Feedback"), None),
            "history" => (Some("Storage"), None),
            _ => (None, None),
        };
        group(title, action, rows)
    }

    fn control(&self, s: &api::Setting, value: &Value, locked: bool, _: &mut Window, cx: &mut Context<Self>) -> AnyElement {
        let name = s.name.clone();
        if s.default.is_boolean() {
            let on = value.as_bool().unwrap_or(false);
            return toggle(SharedString::from(name.clone()), on, !locked)
                .when(!locked, |d| d.on_click(cx.listener(move |this, _: &ClickEvent, window, cx| this.save(name.clone(), Value::Bool(!on), window, cx))))
                .into_any_element();
        }
        if let Some(state) = self.selects.get(&name) {
            return Select::new(state)
                .w(px(224.))
                .h(px(38.))
                .px(px(11.))
                .rounded(px(10.))
                .border_color(n700())
                .text_size(px(14.))
                .font_weight(FontWeight::MEDIUM)
                .menu_width(px(224.))
                .disabled(locked)
                .into_any_element();
        }
        let Some(state) = self.inputs.get(&name) else { return div().into_any_element() };
        let l = self.ring(&name, Instant::now());
        let key = SharedString::from(name.clone());
        let field = div()
            .id(SharedString::from(format!("field-{name}")))
            .h(px(36.))
            .pl(px(2.))
            .flex()
            .items_center()
            .rounded(px(10.))
            .bg(if locked { n800().opacity(0.3) } else { n800() })
            .text_size(px(14.))
            .when(l > 0.001, |d| d.shadow(vec![shadow(0., 0., 0., 2., blend(n500(), n600(), (l - 1.).clamp(0., 1.)).opacity(l.min(1.)), false)]))
            .when(!locked, |d| d.on_hover(self.hover(key, cx)))
            .child(div().flex_1().min_w_0().child(Input::new(state).appearance(false).disabled(locked)));
        if !s.default.is_number() {
            return field.w(px(320.)).into_any_element();
        }
        let current = value.as_f64().unwrap_or(0.0);
        let step = if name == "HOLD_SECONDS" || s.default.as_f64().unwrap_or(0.0).fract() != 0.0 { 0.1 } else { 1.0 };
        let (minus, plus) = (!locked && s.min.is_none_or(|m| current > m), !locked && s.max.is_none_or(|m| current < m));
        let (n1, n2) = (name.clone(), name.clone());
        field
            .w(px(112.))
            .pr(px(4.))
            .child(
                div()
                    .flex()
                    .gap(px(2.))
                    .child(stepper(SharedString::from(format!("minus-{name}")), "minus", minus, self.ring(&format!("minus-{name}"), Instant::now())).when(minus, |d| {
                        d.on_hover(self.hover(format!("minus-{name}").into(), cx))
                    }).when(minus, |d| {
                        d.on_click(cx.listener(move |this, _: &ClickEvent, window, cx| this.step(&n1, -step, window, cx)))
                    }))
                    .child(stepper(SharedString::from(format!("plus-{name}")), "plus", plus, self.ring(&format!("plus-{name}"), Instant::now())).when(plus, |d| {
                        d.on_hover(self.hover(format!("plus-{name}").into(), cx))
                    }).when(plus, |d| {
                        d.on_click(cx.listener(move |this, _: &ClickEvent, window, cx| this.step(&n2, step, window, cx)))
                    })),
            )
            .into_any_element()
    }

    fn words_page(&self, cx: &mut Context<Self>) -> Option<AnyElement> {
        let state = self.words.as_ref()?;
        let (lead, code, tail) = ("One fix per line, written ", "heard => meant", ". Matches whole words in any case, and works for snippets too.");
        let run = |len: usize, family: SharedString, color| TextRun { len, font: font(family), color, background_color: None, underline: None, strikethrough: None };
        let mono = cx.theme().mono_font_family.clone();
        let intro = StyledText::new(format!("{lead}{code}{tail}")).with_runs(vec![
            run(lead.len(), FONT.into(), n600()),
            run(code.len(), mono, n500()),
            run(tail.len(), FONT.into(), n600()),
        ]);
        let save = primary_button("save-words", None, "Save word fixes", self.ring("save-words", Instant::now())).on_hover(self.hover("save-words".into(), cx)).on_click(cx.listener(|this, _: &ClickEvent, window, cx| {
            let Some(words) = &this.words else { return };
            let text = words.read(cx).value().to_string();
            this.request("PUT", "replacements", Some(json!({ "text": text })), window, cx, |this, r: Result<Value, String>, window, cx| match r {
                Ok(_) => this.notify("Word fixes saved", None, Tone::Success, 1800, window, cx),
                Err(e) => this.notify("Word fixes not saved", Some(e), Tone::Error, 5000, window, cx),
            });
        }));
        let editor = div().h(px(296.)).pl(px(2.)).rounded(px(10.)).bg(n800()).text_size(px(13.)).child(Textarea::new(state).appearance(false).line_height(px(20.)).h_full());
        let body = div()
            .p(px(14.))
            .flex()
            .flex_col()
            .gap(px(12.))
            .child(div().text_size(px(12.5)).line_height(px(21.)).child(intro))
            .child(editor)
            .child(div().flex().justify_end().child(save));
        Some(group(None, None, vec![body.into_any_element()]).into_any_element())
    }

    /// Totals across saved history (Flow-style): words, speed, typing time saved.
    fn stats_card(&self) -> Option<AnyElement> {
        let s = self.stats.as_ref().filter(|s| s.dictations > 0)?;
        let cell = |value: String, label: &'static str| {
            div().flex_1().min_w_0().px(px(14.)).py(px(12.)).child(text(value, 20., 25., n50()).font_weight(FontWeight::SEMIBOLD)).child(text(label, 12., 16., n600()))
        };
        let saved = if s.minutes_saved >= 120 { format!("{}h", s.minutes_saved / 60) } else { format!("{}m", s.minutes_saved) };
        let cells = div()
            .flex()
            .child(cell(s.words.to_string(), "words"))
            .child(cell(s.today.to_string(), "today"))
            .child(cell(s.wpm.to_string(), "words / min"))
            .child(cell(saved, "saved vs typing"));
        Some(group(None, None, vec![cells.into_any_element()]).into_any_element())
    }

    fn history_page(&self, cx: &mut Context<Self>) -> impl IntoElement + use<> {
        if self.history.is_empty() {
            let empty = div().py(px(40.)).px(px(16.)).flex().justify_center().child(text("Nothing yet. Press Home and start talking.", 14., 20., n600()));
            return group(None, None, vec![empty.into_any_element()]);
        }
        let rows = self.history.iter().enumerate().map(|(i, h)| {
            let (label, color) = match h.mode.as_str() {
                "raw" => ("Dictate", red()),
                "clean" => ("Clean up", gold()),
                _ => ("Command", gold()),
            };
            let meta = div()
                .mt(px(4.))
                .flex()
                .items_center()
                .gap(px(12.))
                .text_size(px(12.))
                .line_height(px(16.))
                .text_color(n600())
                .child(div().flex().items_center().gap(px(6.)).child(dot(color)).child(label))
                .children(h.app.clone().filter(|a| !a.is_empty()))
                .child(clock(h.time));
            let copied = h.text.clone();
            let ck = SharedString::from(format!("copy-{i}"));
            let rk = SharedString::from(format!("row-{i}"));
            let copy = icon_button(("copy", i), "copy", self.ring(&ck, Instant::now())).on_hover(self.hover(ck, cx)).opacity(self.ring(&rk, Instant::now())).on_click(cx.listener(
                move |this, _: &ClickEvent, window, cx| {
                    cx.write_to_clipboard(ClipboardItem::new_string(copied.clone()));
                    this.notify("Copied", None, Tone::Neutral, 1200, window, cx);
                },
            ));
            div()
                .id(("row", i))
                .on_hover(self.hover(rk, cx))
                .flex()
                .items_start()
                .gap(px(16.))
                .px(px(14.))
                .py(px(12.))
                .child(div().flex_1().min_w_0().child(text(h.text.clone(), 13., 20., n50())).child(meta))
                .child(copy)
                .into_any_element()
        });
        group(None, None, rows.collect())
    }

    fn toast(&self, t: &Toast, now: Instant, cx: &mut Context<Self>) -> impl IntoElement + use<> {
        let (bg, fg, ic) = match t.tone {
            Tone::Success => (gpui::rgba(0x3d630080).into(), gpui::rgb(0xbbf451).into(), "success"),
            Tone::Error => (gpui::rgba(0xa5003680).into(), gpui::rgb(0xffa1ad).into(), "error"),
            Tone::Neutral => (n700(), n500(), "bell"),
        };
        let left = (1. - now.saturating_duration_since(t.at).as_secs_f32() / t.duration.as_secs_f32()).clamp(0., 1.);
        div()
            .absolute()
            .right(px(24.))
            .bottom(px(24.))
            .w(px(400.))
            .flex()
            .items_start()
            .gap(px(12.))
            .p(px(16.))
            .pr(px(44.))
            .rounded(px(16.))
            .border_1()
            .border_color(n700())
            .bg(n800())
            .shadow(vec![shadow(0., 4., 12., 0., black(0.25), false)])
            .overflow_hidden()
            .child(div().size(px(40.)).flex_shrink_0().rounded_full().flex().items_center().justify_center().bg::<gpui::Hsla>(bg).child(icon(ic, 20., fg)))
            .child(
                div()
                    .flex_1()
                    .min_w_0()
                    .flex()
                    .flex_col()
                    .gap(px(4.))
                    .child(text(t.title.clone(), 14., 20., n50()).font_weight(FontWeight::MEDIUM))
                    .children(t.description.clone().map(|d| text(d, 14., 20., n500()))),
            )
            .child(
                div()
                    .id("toast-close")
                    .absolute()
                    .top(px(12.))
                    .right(px(12.))
                    .size(px(24.))
                    .flex()
                    .items_center()
                    .justify_center()
                    .rounded(px(6.))
                    .bg(n700().opacity(self.ring("toast-close", now)))
                    .on_hover(self.hover("toast-close".into(), cx))
                    .on_click(cx.listener(|this, _: &ClickEvent, _, cx| {
                        this.toast = None;
                        cx.notify();
                    }))
                    .child(icon("close", 16., n500())),
            )
            .child(div().absolute().left_0().bottom_0().h(px(3.)).w(px(398. * left)).bg(a600()))
    }
}

impl Render for SettingsWindow {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let root = div().size_full().relative().flex().bg(n925()).font_family(FONT).text_color(n50());
        if self.down {
            let msg = div()
                .flex()
                .flex_col()
                .items_center()
                .gap(px(4.))
                .child(text("speakit isn't running.", 14., 20., n50()))
                .child(text("Start it with systemctl --user start speakit.", 12.5, 18., n600()));
            return root.items_center().justify_center().child(msg);
        }
        if self.settings.is_none() {
            return root;
        }
        let now = Instant::now();
        let busy = |at: Instant| now.saturating_duration_since(at) < Duration::from_millis(360);
        let keys_busy = self.key_at.iter().any(|&at| busy(at));
        if self.retarget(now, window, cx) || keys_busy || busy(self.pill.at) || busy(self.page_at) || self.toast.is_some() {
            window.request_animation_frame();
        }
        let toast = self.toast.as_ref().map(|t| self.toast(t, now, cx));
        root.child(self.sidebar(now, cx)).child(self.content(now, window, cx)).children(toast)
    }
}


/// No thousands separators, at most two decimals: 0.4, 120, 8766; strings as-is.
fn display(v: &Value) -> String {
    match v.as_f64() {
        Some(f) => format!("{f:.2}").trim_end_matches('0').trim_end_matches('.').to_string(),
        None => v.as_str().unwrap_or("").to_string(),
    }
}

/// Local wall-clock time like "12:05 AM".
fn clock(secs: f64) -> String {
    let t = secs as libc::time_t;
    let mut tm: libc::tm = unsafe { std::mem::zeroed() };
    unsafe { libc::localtime_r(&t, &mut tm) };
    format!("{}:{:02} {}", (tm.tm_hour + 11) % 12 + 1, tm.tm_min, if tm.tm_hour < 12 { "AM" } else { "PM" })
}

/// Hybrid laptops (NVIDIA + an AMD/Intel iGPU): render on the iGPU, which drives the
/// compositor. Letting gpui pick the NVIDIA card wakes it (~2 s when asleep) and adds a
/// cross-GPU copy; on the iGPU the first frame lands in ~95 ms instead of ~290.
/// Set SPEAKIT_GPU=any to keep gpui's own choice.
fn prefer_igpu() {
    use std::{env, fs, path::Path};
    let mesa = "/usr/share/glvnd/egl_vendor.d/50_mesa.json";
    let vendors: Vec<String> = fs::read_dir("/sys/class/drm").into_iter().flatten().flatten().filter_map(|e| fs::read_to_string(e.path().join("device/vendor")).ok()).collect();
    let has = |id: &str| vendors.iter().any(|v| v.trim() == id);
    let user_set = ["SPEAKIT_GPU", "__EGL_VENDOR_LIBRARY_FILENAMES", "VK_ICD_FILENAMES", "VK_DRIVER_FILES"].iter().any(|k| env::var_os(k).is_some());
    if user_set || !has("0x10de") || !(has("0x1002") || has("0x8086")) || !Path::new(mesa).exists() {
        return;
    }
    // The iGPU's Vulkan driver if installed (vulkan-radeon / vulkan-intel); else no Vulkan, so gpui uses GL on Mesa.
    let vk: Vec<String> = fs::read_dir("/usr/share/vulkan/icd.d").into_iter().flatten().flatten().map(|e| e.path().display().to_string()).filter(|p| p.contains("radeon") || p.contains("intel")).collect();
    // SAFETY: first thing in main, before any other thread exists.
    unsafe {
        env::set_var("__EGL_VENDOR_LIBRARY_FILENAMES", mesa);
        env::set_var("VK_ICD_FILENAMES", if vk.is_empty() { "/nonexistent".into() } else { vk.join(":") });
    }
}

fn main() {
    prefer_igpu();
    gpui_platform::application().with_assets(Assets).run(|cx: &mut App| {
        gpui_component::init(cx);
        theme::init(cx);
        let options = WindowOptions {
            window_bounds: Some(WindowBounds::Windowed(gpui::Bounds::centered(None, size(px(1100.), px(860.)), cx))),
            window_min_size: Some(size(px(1000.), px(860.))),
            titlebar: Some(gpui::TitlebarOptions { title: Some("speakit".into()), ..Default::default() }),
            app_id: Some("speakit".into()),
            ..Default::default()
        };
        cx.open_window(options, |window, cx| {
            let view = cx.new(|cx| SettingsWindow::new(window, cx));
            cx.new(|cx| Root::new(view, window, cx))
        })
        .expect("open the settings window");
        cx.activate(true);
    });
}

#[cfg(test)]
mod tests {
    #[test]
    fn numbers_and_easing() {
        use serde_json::json;
        assert_eq!(super::display(&json!(120.0)), "120");
        assert_eq!(super::display(&json!(0.4)), "0.4");
        assert_eq!(super::display(&json!(8766)), "8766");
        assert_eq!(super::display(&json!("x")), "x");
        assert!(super::ease(0.0).abs() < 1e-3);
        assert!((super::ease(1.0) - 1.0).abs() < 1e-3);
        assert!(super::ease(0.5) > 0.8, "decelerating curve");
    }
}
