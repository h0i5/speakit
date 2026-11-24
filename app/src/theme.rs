//! Palette, fonts, bundled assets, and gpui-component's theme set to match.
use gpui::{App, AssetSource, Hsla, Result, SharedString, rgb};
use gpui_component::{Theme, ThemeMode};
use std::borrow::Cow;

fn hex(h: u32) -> Hsla {
    rgb(h).into()
}

pub fn n50() -> Hsla { hex(0xf8f4f1) }
pub fn n100() -> Hsla { hex(0xece9e5) }
pub fn n500() -> Hsla { hex(0x95928e) }
pub fn n600() -> Hsla { hex(0x7d7a76) }
pub fn n700() -> Hsla { hex(0x423f3c) }
pub fn n800() -> Hsla { hex(0x302d2b) }
pub fn n900() -> Hsla { hex(0x22201d) }
pub fn n925() -> Hsla { hex(0x1b1916) }
pub fn n950() -> Hsla { hex(0x161311) }
pub fn a200() -> Hsla { hex(0xf6d0a3) }
pub fn a400() -> Hsla { hex(0xeaa443) }
pub fn a500() -> Hsla { hex(0xdc9322) }
pub fn a600() -> Hsla { hex(0xc88100) }
pub fn a800() -> Hsla { hex(0x744700) }
pub fn a950() -> Hsla { hex(0x351e00) }
pub fn on_accent() -> Hsla { hex(0x25170c) }
pub fn red() -> Hsla { hex(0xff5555) }
pub fn gold() -> Hsla { hex(0xe5a04b) }
pub fn green() -> Hsla { hex(0x5fd38d) }
pub fn white(a: f32) -> Hsla { gpui::white().opacity(a) }
pub fn black(a: f32) -> Hsla { gpui::black().opacity(a) }

pub const FONT: &str = "TASA Orbiter";

macro_rules! files {
    ($($name:literal),*) => {
        &[("speakit.svg", include_bytes!("../assets/speakit.svg")), $((concat!("remix/", $name, ".svg"), include_bytes!(concat!("../assets/icons/", $name, ".svg")))),*]
    };
}
const FILES: &[(&str, &[u8])] =
    files!("settings", "keyboard", "sparkling", "book", "history", "cpu", "volume", "copy", "restart", "plus", "minus", "success", "error", "bell", "close");

/// Our SVGs (Remix icons, the logo) first, then gpui-component's own icons.
pub struct Assets;

impl AssetSource for Assets {
    fn load(&self, path: &str) -> Result<Option<Cow<'static, [u8]>>> {
        match FILES.iter().find(|(p, _)| *p == path) {
            Some((_, bytes)) => Ok(Some(Cow::Borrowed(bytes))),
            None => gpui_kit_assets::Assets.load(path),
        }
    }

    fn list(&self, path: &str) -> Result<Vec<SharedString>> {
        gpui_kit_assets::Assets.list(path)
    }
}

/// Bundled fonts, then gpui-component's dark theme re-tinted to the palette
/// (it styles the text inputs, dropdowns and scrollbar).
pub fn init(cx: &mut App) {
    cx.text_system()
        .add_fonts(vec![
            Cow::Borrowed(include_bytes!("../assets/TASAOrbiter-400.ttf")),
            Cow::Borrowed(include_bytes!("../assets/TASAOrbiter-500.ttf")),
            Cow::Borrowed(include_bytes!("../assets/TASAOrbiter-600.ttf")),
        ])
        .expect("bundled fonts load");
    Theme::change(ThemeMode::Dark, None, cx);
    let t = Theme::global_mut(cx);
    t.font_family = FONT.into();
    t.font_size = gpui::px(14.);
    t.radius = gpui::px(8.);
    t.radius_lg = gpui::px(10.);
    t.shadow = false;
    t.focus_ring = false;
    t.background = n925();
    t.foreground = n50();
    t.muted_foreground = n500();
    t.border = n700();
    t.input = n800();
    t.ring = n600();
    t.caret = n50();
    t.selection = a600().opacity(0.45);
    t.popover = n800();
    t.popover_foreground = n50();
    t.accent = n700();
    t.accent_foreground = n50();
    t.list_hover = n700();
    t.list_active = n700();
    t.scrollbar = gpui::transparent_black();
    t.scrollbar_thumb = n700();
    t.scrollbar_thumb_hover = n600();
}
