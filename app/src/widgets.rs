//! Building blocks: text, icons, groups and rows, and the hand-drawn controls.
use crate::theme::*;
use gpui::prelude::*;
use gpui::{AnyElement, BoxShadow, Div, ElementId, FontWeight, Hsla, SharedString, Stateful, Svg, div, img, linear_color_stop, linear_gradient, point, px, svg};

/// Text with an explicit CSS-style line box.
pub fn text(s: impl Into<SharedString>, size: f32, line: f32, color: Hsla) -> Div {
    div().text_size(px(size)).line_height(px(line)).text_color(color).child(s.into())
}

pub fn icon(name: &str, size: f32, color: Hsla) -> Svg {
    svg().path(SharedString::from(format!("remix/{name}.svg"))).size(px(size)).flex_shrink_0().text_color(color)
}

pub fn logo() -> impl IntoElement {
    img("speakit.svg").size(px(19.)).mt(px(1.))
}

pub fn shadow(x: f32, y: f32, blur: f32, spread: f32, color: Hsla, inset: bool) -> BoxShadow {
    BoxShadow { color, offset: point(px(x), px(y)), blur_radius: px(blur), spread_radius: px(spread), inset }
}

/// Top-to-bottom gradient, like CSS `linear-gradient(to bottom, a, b)`.
pub fn vgrad(top: Hsla, bottom: Hsla) -> gpui::Background {
    linear_gradient(180., linear_color_stop(top, 0.), linear_color_stop(bottom, 1.))
}

/// Linear blend of two colours (eased hover/focus states).
pub fn blend(a: Hsla, b: Hsla, t: f32) -> Hsla {
    let l = |x: f32, y: f32| x + (y - x) * t;
    Hsla { h: l(a.h, b.h), s: l(a.s, b.s), l: l(a.l, b.l), a: l(a.a, b.a) }
}

pub fn dot(color: Hsla) -> Div {
    div().size(px(6.)).flex_shrink_0().rounded_full().bg(color)
}

/// Cards and groups: neutral-900, hairline ring, soft shadow.
pub fn card() -> Div {
    div().bg(n900()).rounded(px(12.)).shadow(vec![shadow(0., 0., 0., 1., white(0.05), false), shadow(0., 1., 3., 0., black(0.3), false)])
}

/// Optional 12px header (with an action at the controls' right edge), then a card of rows
/// split by hairlines inset 14px from the left.
pub fn group(title: Option<&'static str>, action: Option<AnyElement>, rows: Vec<AnyElement>) -> Div {
    let rows = rows.into_iter().enumerate().map(|(i, r)| {
        div().relative().child(r).when(i > 0, |d| d.child(div().absolute().top_0().left(px(14.)).right_0().h(px(1.)).bg(white(0.06))))
    });
    let card = card().flex().flex_col().children(rows);
    if title.is_none() && action.is_none() {
        return card;
    }
    let header = div()
        .h(px(28.))
        .px(px(14.))
        .mb(px(6.))
        .flex()
        .items_end()
        .justify_between()
        .child(text(title.unwrap_or(""), 12., 18., n500()).font_weight(FontWeight::MEDIUM))
        .children(action);
    div().flex().flex_col().child(header).child(card)
}

/// Label + help on the left, the control on the right.
pub fn row(label: impl Into<SharedString>, help: impl Into<SharedString>, control: Option<AnyElement>) -> Div {
    div()
        .flex()
        .items_center()
        .justify_between()
        .gap(px(24.))
        .min_h(px(48.))
        .px(px(14.))
        .py(px(10.))
        .child(div().flex_1().min_w_0().child(text(label, 13., 20., n50())).child(text(help, 12., 16., n600()).mt(px(2.))))
        .children(control.map(|c| div().flex_shrink_0().child(c)))
}

/// BoardUI's md pill switch: amber gradient when on, a white thumb with a chip.
pub fn toggle(id: impl Into<ElementId>, on: bool, enabled: bool) -> Stateful<Div> {
    let dim = |c: Hsla| if enabled { c } else { c.opacity(0.5) };
    let chip = div().size(px(7.5)).rounded_full().border(px(0.5)).map(|d| {
        if on { d.bg(vgrad(a600(), a500())).border_color(a600()) } else { d.bg(n800()).border_color(n700().opacity(0.5)) }
    });
    let thumb = div()
        .absolute()
        .top(px(3.))
        .left(px(if on { 21. } else { 3. }))
        .size(px(18.))
        .rounded_full()
        .flex()
        .items_center()
        .justify_center()
        .bg(vgrad(dim(gpui::white()), dim(n100())))
        .shadow(vec![shadow(0., 1., 2., 0., black(0.25), false)])
        .child(chip);
    div()
        .id(id)
        .relative()
        .w(px(42.))
        .h(px(24.))
        .rounded_full()
        .map(|d| {
            if on {
                d.bg(vgrad(dim(a500()), dim(a600())))
                    .shadow(vec![shadow(0., 1.5, 0., 0., white(0.25), true), shadow(0., 0., 0., 0.75, a500(), true)])
            } else {
                d.bg(dim(n800()))
            }
        })
        .child(thumb)
}

/// Secondary xs button: 28px tall, 14px icon, 12px medium label.
pub fn xs_button(id: impl Into<ElementId>, ic: &str, label: &'static str, t: f32) -> Stateful<Div> {
    div()
        .id(id)
        .h(px(28.))
        .px(px(10.))
        .flex()
        .items_center()
        .gap(px(4.))
        .rounded(px(8.))
        .bg(blend(n800(), n700(), 0.6 * t))
        .border_1()
        .border_color(blend(n700(), n500(), t))
        .shadow(vec![shadow(0., 1., 2., 0., black(0.18), false)])
        .child(icon(ic, 14., n50()))
        .child(text(label, 12., 16., n50()).font_weight(FontWeight::MEDIUM))
}

/// Square secondary xs icon button (history copy).
pub fn icon_button(id: impl Into<ElementId>, ic: &str, t: f32) -> Stateful<Div> {
    div()
        .id(id)
        .size(px(28.))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(8.))
        .bg(blend(n800(), n700(), 0.6 * t))
        .border_1()
        .border_color(blend(n700(), n500(), t))
        .shadow(vec![shadow(0., 1., 2., 0., black(0.18), false)])
        .child(icon(ic, 14., n50()))
}

/// Primary small button: 32px tall, amber gradient, 14px medium label, optional 18px icon.
pub fn primary_button(id: impl Into<ElementId>, ic: Option<&str>, label: &'static str, t: f32) -> Stateful<Div> {
    div()
        .id(id)
        .h(px(32.))
        .px(px(10.))
        .flex()
        .items_center()
        .gap(px(4.))
        .rounded(px(8.))
        .bg(vgrad(blend(a500(), a400(), t), blend(a600(), a500(), t)))
        .shadow(vec![shadow(0., 1., 2., 0., black(0.18), false)])
        .children(ic.map(|i| icon(i, 18., on_accent())))
        .child(text(label, 14., 20., on_accent()).font_weight(FontWeight::MEDIUM))
}

/// Number field minus/plus.
pub fn stepper(id: impl Into<ElementId>, ic: &str, enabled: bool, t: f32) -> Stateful<Div> {
    div()
        .id(id)
        .size(px(24.))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(6.))
        .when(enabled, |d| d.bg(n700().opacity(t)))
        .child(icon(ic, 16., if enabled { n500() } else { n500().opacity(0.4) }))
}

/// Keycap shading; `sink` 0 = at rest, 1 = pressed (skirt and drop shadow flatten).
pub fn keycap_shadow(sink: f32) -> Vec<BoxShadow> {
    let l = |a: f32, b: f32| a + (b - a) * sink;
    vec![
        shadow(0., 1., 0., 0., white(l(0.10, 0.06)), true),
        shadow(0., l(-3., -1.), 0., 0., black(0.28), true),
        shadow(0., 0., 0., 1., black(0.35), false),
        shadow(0., l(2., 0.), l(4., 0.), 0., black(l(0.25, 0.)), false),
    ]
}

/// Keycap: sculpted gradient face, darker 3px skirt, faint top highlight; sinks up to 2px.
pub fn keycap(label: &'static str, sink: f32) -> Div {
    div()
        .relative()
        .top(px(2. * sink))
        .h(px(36.))
        .min_w(px(52.))
        .px(px(11.))
        .pb(px(3.))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(8.))
        .bg(vgrad(n700(), n800()))
        .shadow(keycap_shadow(sink))
        .child(text(label, 12., 18., n100()).font_weight(FontWeight::MEDIUM))
}

pub fn led(c: Hsla) -> Div {
    dot(c).shadow(vec![shadow(0., 0., 6., 0., c, false)])
}
