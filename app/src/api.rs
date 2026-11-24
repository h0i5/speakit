//! The daemon's JSON API (src/speakit/server.py). Blocking ureq calls, run on
//! gpui's background executor.
use serde::Deserialize;
use serde::de::DeserializeOwned;
use serde_json::{Map, Value};
use std::path::PathBuf;
use std::time::Duration;

#[derive(Debug, Clone, Deserialize)]
pub struct Setting {
    pub name: String,
    pub section: String,
    pub default: Value,
    pub label: String,
    pub help: String,
    pub restart: bool,
    pub choices: Vec<String>,
    pub min: Option<f64>,
    pub max: Option<f64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Settings {
    pub schema: Vec<Setting>,
    pub values: Map<String, Value>,
    pub env: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Status {
    pub state: String,
    pub device: String,
    pub model_ready: bool,
    pub llm: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Item {
    pub time: f64,
    pub mode: String,
    pub app: Option<String>,
    pub text: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Saved {
    pub values: Map<String, Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Words {
    pub text: String,
}

#[derive(Clone)]
pub struct Api {
    agent: ureq::Agent,
    base: String,
}

fn runtime_dir() -> PathBuf {
    std::env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| format!("/tmp/speakit-{}", unsafe { libc::getuid() }).into())
}

/// SPEAKIT_UI_PORT, else [model] ui_port in config.toml, else 8766 (same order as the daemon).
fn port() -> u16 {
    let config = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".config"))
        .join("speakit/config.toml");
    let from_file = || {
        let text = std::fs::read_to_string(config).ok()?;
        let mut in_model = false;
        for line in text.lines().map(str::trim) {
            if line.starts_with('[') {
                in_model = line == "[model]";
            } else if let Some((k, v)) = line.split_once('=') {
                if in_model && k.trim() == "ui_port" {
                    return v.trim().parse().ok();
                }
            }
        }
        None
    };
    std::env::var("SPEAKIT_UI_PORT").ok().and_then(|p| p.parse().ok()).or_else(from_file).unwrap_or(8766)
}

impl Api {
    pub fn new() -> Self {
        let agent = ureq::Agent::config_builder()
            .timeout_global(Some(Duration::from_secs(3)))
            .http_status_as_error(false)
            .build()
            .into();
        Self { agent, base: format!("http://127.0.0.1:{}/api/", port()) }
    }

    /// GET without a body, PUT with one; POST for the bodiless actions.
    /// ponytail: the token is re-read on every call (one tiny tmpfs read), so a
    /// daemon restart's new token is picked up without a 401 retry dance.
    pub fn call<T: DeserializeOwned>(&self, method: &str, path: &str, body: Option<Value>) -> Result<T, String> {
        let token = std::fs::read_to_string(runtime_dir().join("speakit-ui.token")).map_err(|_| "speakit isn't running")?;
        let url = format!("{}{path}", self.base);
        let token = token.trim();
        let res = match (method, body) {
            ("GET", _) => self.agent.get(&url).header("X-Speakit-Token", token).call(),
            (_, Some(body)) => self.agent.put(&url).header("X-Speakit-Token", token).send_json(body),
            _ => self.agent.post(&url).header("X-Speakit-Token", token).send_empty(),
        };
        let mut res = res.map_err(|e| e.to_string())?;
        let ok = res.status().is_success();
        let value: Value = res.body_mut().read_json().map_err(|e| e.to_string())?;
        if !ok {
            return Err(value["error"].as_str().unwrap_or("request failed").to_string());
        }
        serde_json::from_value(value).map_err(|e| e.to_string())
    }
}
