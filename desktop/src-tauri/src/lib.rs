use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, State};

#[derive(Clone, Deserialize, Serialize)]
struct EngineEndpoint {
    host: String,
    port: u16,
    token: String,
}

struct EngineRuntime {
    child: Child,
    endpoint: EngineEndpoint,
}

#[derive(Default)]
struct EngineProcess(Mutex<Option<EngineRuntime>>);

impl Drop for EngineProcess {
    fn drop(&mut self) {
        if let Ok(runtime) = self.0.get_mut() {
            if let Some(runtime) = runtime.as_mut() {
                let _ = runtime.child.kill();
                let _ = runtime.child.wait();
            }
        }
    }
}

fn packaged_engine_path() -> Result<PathBuf, String> {
    if let Ok(path) = std::env::var("PHOTO_FIT_PICKER_ENGINE") {
        return Ok(PathBuf::from(path));
    }
    let executable = std::env::current_exe().map_err(|error| error.to_string())?;
    let mut engine = executable
        .parent()
        .ok_or_else(|| "无法定位应用程序目录".to_string())?
        .join("photo-engine");
    if cfg!(target_os = "windows") {
        engine.set_extension("exe");
    }
    Ok(engine)
}

fn development_command(data_root: &Path, token: &str) -> Command {
    let project_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("desktop project must live inside the repository");
    let python = std::env::var("PHOTO_FIT_PICKER_PYTHON")
        .unwrap_or_else(|_| "python3".to_string());
    let mut command = Command::new(python);
    command
        .current_dir(project_root)
        .env("PYTHONPATH", project_root.join("src"))
        .args(["-m", "photo_fit_picker.bridge", "serve", "--port", "0", "--token"])
        .arg(token)
        .arg("--data-root")
        .arg(data_root);
    command
}

fn release_command(data_root: &Path, token: &str) -> Result<Command, String> {
    let mut command = Command::new(packaged_engine_path()?);
    command
        .args(["serve", "--port", "0", "--token"])
        .arg(token)
        .arg("--data-root")
        .arg(data_root);
    Ok(command)
}

#[tauri::command]
fn start_engine(
    app: tauri::AppHandle,
    state: State<'_, EngineProcess>,
) -> Result<EngineEndpoint, String> {
    let mut runtime = state.0.lock().map_err(|_| "引擎状态不可用".to_string())?;
    if let Some(existing) = runtime.as_ref() {
        return Ok(existing.endpoint.clone());
    }

    let data_root = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&data_root).map_err(|error| error.to_string())?;
    let token = uuid::Uuid::new_v4().simple().to_string();
    let mut command = if cfg!(debug_assertions) {
        development_command(&data_root, &token)
    } else {
        release_command(&data_root, &token)?
    };
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("无法启动图片引擎：{error}"))?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "无法读取图片引擎输出".to_string())?;
    let mut reader = BufReader::new(stdout);
    let mut ready_line = String::new();
    reader
        .read_line(&mut ready_line)
        .map_err(|error| format!("图片引擎没有响应：{error}"))?;
    let endpoint: EngineEndpoint = serde_json::from_str(&ready_line)
        .map_err(|error| format!("图片引擎返回了无效响应：{error}"))?;
    if endpoint.token != token || endpoint.host != "127.0.0.1" {
        let _ = child.kill();
        return Err("图片引擎身份校验失败".to_string());
    }

    std::thread::spawn(move || {
        for line in reader.lines().map_while(Result::ok) {
            eprintln!("photo-engine: {line}");
        }
    });
    if let Some(stderr) = child.stderr.take() {
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                eprintln!("photo-engine error: {line}");
            }
        });
    }
    *runtime = Some(EngineRuntime {
        child,
        endpoint: endpoint.clone(),
    });
    Ok(endpoint)
}

#[tauri::command]
fn demo_folder(app: tauri::AppHandle) -> Result<String, String> {
    let bundled = app
        .path()
        .resource_dir()
        .map_err(|error| error.to_string())?
        .join("demo-photos");
    if bundled.is_dir() {
        return Ok(bundled.to_string_lossy().into_owned());
    }
    let development = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("desktop project must live inside the repository")
        .join("demo-photos");
    Ok(development.to_string_lossy().into_owned())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(EngineProcess::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![start_engine, demo_folder])
        .run(tauri::generate_context!())
        .expect("error while running Photo Fit Picker");
}
