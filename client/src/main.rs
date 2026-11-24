//! speakit-toggle: send one command (default "toggle") to the speakit daemon
//! and print its reply. Bound to Hyprland keys, so it must start instantly:
//! std only, no config parsing beyond what a command needs.

use std::io::{Read, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::{Command, ExitCode, Stdio};
use std::time::Duration;

fn runtime_dir() -> PathBuf {
    std::env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(format!("/tmp/speakit-{}", unsafe { libc_getuid() })))
}

unsafe extern "C" {
    #[link_name = "getuid"]
    fn libc_getuid() -> u32;
}

fn send(cmd: &str) -> Option<String> {
    let mut s = UnixStream::connect(runtime_dir().join("speakit.sock")).ok()?;
    // Transcription happens before the daemon replies.
    s.set_read_timeout(Some(Duration::from_secs(60))).ok()?;
    s.write_all(cmd.as_bytes()).ok()?;
    let mut buf = [0u8; 4096];
    let n = s.read(&mut buf).unwrap_or(0);
    Some(String::from_utf8_lossy(&buf[..n]).into_owned())
}

/// The native settings app (installed next to this binary) or, if it isn't
/// there, the web UI in a Chrome app window.
fn open_settings() -> bool {
    let spawn = |cmd: &mut Command| cmd.stdout(Stdio::null()).stderr(Stdio::null()).spawn().is_ok();
    if let Some(app) = std::env::current_exe().ok().and_then(|p| Some(p.parent()?.join("speakit"))) {
        if app.exists() && spawn(&mut Command::new(app)) {
            return true;
        }
    }
    let Ok(token) = std::fs::read_to_string(runtime_dir().join("speakit-ui.token")) else {
        return false;
    };
    // Token in the fragment: never sent to the server or stored in history.
    let url = format!("http://127.0.0.1:8766/#token={}", token.trim());
    spawn(Command::new("google-chrome-stable").arg(format!("--app={url}")))
        || spawn(Command::new("xdg-open").arg(url))
}

fn main() -> ExitCode {
    let cmd = std::env::args().nth(1).unwrap_or_else(|| "toggle".into());
    if cmd == "settings" {
        return if open_settings() { ExitCode::SUCCESS } else { ExitCode::FAILURE };
    }
    match send(&cmd) {
        Some(reply) => {
            println!("{reply}");
            ExitCode::SUCCESS
        }
        None => {
            eprintln!("no-daemon (systemctl --user start speakit)");
            ExitCode::FAILURE
        }
    }
}
