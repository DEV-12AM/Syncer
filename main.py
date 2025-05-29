import os
import json
import base64
import zipfile
import shutil
import re
from datetime import datetime
try:
    import requests
except ImportError:
    print("Error: 'requests' module not found. Run: pip install requests")
    exit(1)
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.properties import StringProperty
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.logger import Logger
import time

# Mobile paths
BASE_DIR = "/storage/emulated/0/Download/Syncer"
CACHE_FILE = os.path.join(BASE_DIR, ".cache.json")
TEMP_BACKUP = os.path.join(BASE_DIR, "backup.zip")
LOCAL_BACKUP_DIR = os.path.join(BASE_DIR, "backups")

def ensure_directories():
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)
    if not os.path.exists(LOCAL_BACKUP_DIR):
        os.makedirs(LOCAL_BACKUP_DIR)

def load_cached_data():
    defaults = {"username": "", "email": "", "repo_link": "", "commit_message": "", "local_vault": "", "branch_name": ""}
    try:
        if os.path.exists(CACHE_FILE) and os.access(CACHE_FILE, os.R_OK):
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                Logger.error(f"Cache file {CACHE_FILE} contains invalid data")
                return defaults
            defaults.update(data)
            Logger.info(f"Loaded cache: {CACHE_FILE}")
        return defaults
    except Exception as e:
        Logger.error(f"Error loading cache: {e}")
        return defaults

def save_cached_data(data):
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        Logger.info(f"Saved cache: {CACHE_FILE}")
        return True
    except Exception as e:
        Logger.error(f"Error saving cache: {e}")
        return False

def validate_repo_url(repo_link):
    repo_link = repo_link.strip().rstrip('/')
    if repo_link.endswith(".git"):
        repo_link = repo_link[:-4]
    if not re.match(r'^https?://github\.com/[^/]+/[^/]+$', repo_link):
        raise ValueError("Invalid repo URL. Use: https://github.com/owner/repo")
    return repo_link

def get_repo_info(repo_link, token):
    try:
        repo_link = validate_repo_url(repo_link)
        parts = repo_link.rstrip("/").split('/')
        owner, repo = parts[-2], parts[-1]
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        repo_info = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        if repo_info.status_code == 401:
            raise ValueError("Invalid PAT or insufficient scopes")
        if repo_info.status_code == 403:
            raise ValueError("API rate limit exceeded or access denied")
        if repo_info.status_code != 200:
            raise ValueError(f"Repo not found: {repo_info.json().get('message', 'Unknown error')}")
        return owner, repo, repo_info.json().get("default_branch", "main")
    except requests.RequestException as e:
        raise ValueError(f"Network error: {e}")
    except Exception as e:
        raise ValueError(f"Error parsing repo: {e}")

def get_branches(owner, repo, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/branches", headers=headers)
        if response.status_code != 200:
            return []
        return [branch["name"] for branch in response.json()]
    except requests.RequestException:
        return []

def create_zip(vault_path, zip_path):
    try:
        if not os.path.isdir(vault_path):
            return f"Error: Vault {vault_path} not found"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(vault_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, vault_path)
                    zf.write(file_path, os.path.join("Obsidian-Vault", rel_path))
        return f"Created zip: {zip_path}"
    except Exception as e:
        return f"Zip creation failed: {e}"

def local_backup_vault(vault_path):
    output = []
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(LOCAL_BACKUP_DIR, f"backup_{timestamp}.zip")
        zip_result = create_zip(vault_path, backup_path)
        if "Error" in zip_result:
            return [zip_result]
        output.append(zip_result)
        return output
    except Exception as e:
        output.append(f"Local backup error: {e}")
        return output

def restore_local_vault(vault_path):
    output = []
    try:
        if not os.path.exists(LOCAL_BACKUP_DIR):
            output.append(f"Error: No local backups found in {LOCAL_BACKUP_DIR}")
            return output
        backups = [f for f in os.listdir(LOCAL_BACKUP_DIR) if f.startswith("backup_") and f.endswith(".zip")]
        if not backups:
            output.append(f"Error: No local backups found in {LOCAL_BACKUP_DIR}")
            return output
        latest_backup = max(backups, key=lambda x: os.path.getctime(os.path.join(LOCAL_BACKUP_DIR, x)))
        backup_path = os.path.join(LOCAL_BACKUP_DIR, latest_backup)

        if os.path.exists(vault_path):
            shutil.rmtree(vault_path)
        os.makedirs(vault_path)
        with zipfile.ZipFile(backup_path, 'r') as zf:
            zf.extractall(vault_path)
        output.append(f"Restored vault from {latest_backup}")
        return output
    except Exception as e:
        output.append(f"Local restore error: {e}")
        return output

def remote_backup_vault(vault_path, token, owner, repo, default_branch):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    output = []
    try:
        # Create zip
        zip_result = create_zip(vault_path, TEMP_BACKUP)
        if "Error" in zip_result:
            return [zip_result]
        output.append(zip_result)

        # Check if backup branch exists
        backup_ref = requests.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/backup", headers=headers)
        if backup_ref.status_code == 200:
            # Move backup to old-backup
            old_backup_ref = requests.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/old-backup", headers=headers)
            if old_backup_ref.status_code == 200:
                update_ref = requests.patch(
                    f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/old-backup",
                    headers=headers,
                    json={"sha": backup_ref.json()["object"]["sha"]}
                )
                if update_ref.status_code != 200:
                    output.append(f"Error updating old-backup: {update_ref.json().get('message', 'Unknown error')}")
                    return output
                output.append("Moved existing backup to old-backup")
            else:
                create_old_backup = requests.post(
                    f"https://api.github.com/repos/{owner}/{repo}/git/refs",
                    headers=headers,
                    json={"ref": "refs/heads/old-backup", "sha": backup_ref.json()["object"]["sha"]}
                )
                if create_old_backup.status_code != 201:
                    output.append(f"Error creating old-backup: {create_old_backup.json().get('message', 'Unknown error')}")
                    return output
                output.append("Created old-backup branch")

        # Create or update backup branch
        default_ref = requests.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{default_branch}", headers=headers)
        if default_ref.status_code != 200:
            output.append(f"Error getting {default_branch} ref: {default_ref.json().get('message', 'Unknown error')}")
            return output
        base_sha = default_ref.json()["object"]["sha"]

        if backup_ref.status_code != 200:
            create_backup = requests.post(
                f"https://api.github.com/repos/{owner}/{repo}/git/refs",
                headers=headers,
                json={"ref": "refs/heads/backup", "sha": base_sha}
            )
            if create_backup.status_code != 201:
                output.append(f"Error creating backup branch: {create_backup.json().get('message', 'Unknown error')}")
                return output
            output.append("Created backup branch")

        # Upload backup zip
        with open(TEMP_BACKUP, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data = {
            "message": f"Remote backup {timestamp}",
            "content": content,
            "branch": "backup"
        }
        upload = requests.put(
            f"https://api.github.com/repos/{owner}/{repo}/contents/backup_{timestamp}.zip",
            headers=headers,
            json=data
        )
        if upload.status_code not in (200, 201):
            output.append(f"Error uploading backup: {upload.json().get('message', 'Unknown error')}")
            return output
        output.append(f"Uploaded backup_{timestamp}.zip")
        os.remove(TEMP_BACKUP)
        return output
    except requests.RequestException as e:
        output.append(f"Network error: {e}")
        return output
    except Exception as e:
        output.append(f"Remote backup error: {e}")
        return output

def restore_remote_vault(vault_path, token, owner, repo):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    output = []
    try:
        # Get latest backup from backup branch
        contents = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents?ref=backup", headers=headers)
        if contents.status_code != 200:
            output.append(f"Error accessing backup branch: {contents.json().get('message', 'Unknown error')}")
            return output
        backups = [item for item in contents.json() if item["name"].endswith(".zip")]
        if not backups:
            output.append("Error: No backups found in backup branch")
            return output
        latest_backup = max(backups, key=lambda x: x["name"])  # Latest by filename
        download_url = latest_backup["download_url"]

        # Download zip
        response = requests.get(download_url)
        if response.status_code != 200:
            output.append(f"Error downloading backup: {response.status_code}")
            return output
        with open(TEMP_BACKUP, "wb") as f:
            f.write(response.content)
        output.append(f"Downloaded backup: {latest_backup['name']}")

        # Restore
        if os.path.exists(vault_path):
            shutil.rmtree(vault_path)
        os.makedirs(vault_path)
        with zipfile.ZipFile(TEMP_BACKUP, 'r') as zf:
            zf.extractall(vault_path)
        output.append(f"Restored vault from {latest_backup['name']}")
        os.remove(TEMP_BACKUP)
        return output
    except requests.RequestException as e:
        output.append(f"Network error: {e}")
        return output
    except Exception as e:
        output.append(f"Restore error: {e}")
        return output

def upload_files_to_github(directory, token, owner, repo, branch, default_branch):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    output = []
    uploaded_files = []
    try:
        if not os.path.isdir(directory):
            output.append(f"Error: Folder {directory} does not exist")
            return output, uploaded_files

        ref = requests.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{branch}", headers=headers)
        if ref.status_code == 200:
            base_sha = ref.json()["object"]["sha"]
            output.append(f"Branch {branch} exists, updating")
        else:
            ref = requests.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{default_branch}", headers=headers)
            if ref.status_code != 200:
                output.append(f"Error getting {default_branch} ref: {ref.json().get('message', 'Unknown error')}")
                return output, uploaded_files
            base_sha = ref.json()["object"]["sha"]
            create_branch = requests.post(
                f"https://api.github.com/repos/{owner}/{repo}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch}", "sha": base_sha}
            )
            if create_branch.status_code != 201:
                output.append(f"Error creating branch: {create_branch.json().get('message', 'Unknown error')}")
                return output, uploaded_files
            output.append(f"Created branch: {branch}")

        for root, _, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, directory)
                try:
                    with open(file_path, "rb") as f:
                        content = base64.b64encode(f.read()).decode("utf-8")
                    data = {
                        "message": f"Add {rel_path}",
                        "content": content,
                        "branch": branch
                    }
                    upload = requests.put(
                        f"https://api.github.com/repos/{owner}/{repo}/contents/{rel_path}",
                        headers=headers,
                        json=data
                    )
                    if upload.status_code not in (200, 201):
                        output.append(f"Error uploading {rel_path}: {upload.json().get('message', 'Unknown error')}")
                    else:
                        output.append(f"Uploaded {rel_path}")
                        uploaded_files.append(rel_path)
                except Exception as e:
                    output.append(f"Error processing {rel_path}: {e}")
        return output, uploaded_files
    except requests.RequestException as e:
        output.append(f"Network error uploading files: {e}")
        return output, uploaded_files
    except Exception as e:
        output.append(f"Unexpected error uploading files: {e}")
        return output, uploaded_files

def trigger_github_workflow(token, owner, repo, branch, username, email, commit_message, default_branch):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    output = []
    try:
        workflow_data = {
            "ref": branch,
            "inputs": {
                "username": username,
                "email": email,
                "commit_message": commit_message or "Auto sync",
                "default_branch": default_branch
            }
        }
        response = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/git-sync.yml/dispatches",
            headers=headers,
            json=workflow_data
        )
        if response.status_code != 204:
            output.append(f"Error triggering workflow: {response.json().get('message', 'Unknown error')}")
            return output
        output.append("Triggered workflow")

        for _ in range(12):
            runs = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/actions/runs",
                headers=headers,
                params={"branch": branch}
            )
            if runs.status_code != 200:
                output.append(f"Error checking workflow status: {runs.json().get('message', 'Unknown error')}")
                return output
            runs_data = runs.json().get("workflow_runs", [])
            if runs_data:
                latest_run = runs_data[0]
                status = latest_run["status"]
                conclusion = latest_run["conclusion"]
                run_id = latest_run["id"]
                if status == "completed":
                    if conclusion == "success":
                        output.append("Workflow completed successfully")
                    else:
                        jobs = requests.get(f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/jobs", headers=headers)
                        if jobs.status_code == 200:
                            for job in jobs.json().get("jobs", []):
                                if job["conclusion"] == "failure":
                                    output.append(f"Workflow failed: {job['name']}")
                                    output.append(f"Logs: {job['html_url']}")
                        output.append(f"Workflow failed: {conclusion}")
                    return output
            time.sleep(15)
        output.append("Workflow timed out")
        return output
    except requests.RequestException as e:
        output.append(f"Network error in workflow: {e}")
        return output
    except Exception as e:
        output.append(f"Workflow error: {e}")
        return output

class GitConfigLayout(BoxLayout):
    output_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.output_text = "*Sync your vault to GitHub!*\n\n" + \
                          "Steps:\n1. Get a PAT (repo, workflow scopes): github.com/settings/tokens\n" + \
                          "2. Add .github/workflows/git-sync.yml to github.com/DEV-12AM/Syncer\n" + \
                          "3. Set default branch (main/master).\n" + \
                          "4. Fill fields, hit 'Run Git Commands'.\n\n" + \
                          "Open source: github.com/DEV-12AM/Syncer\nNo sketchy stuff!\n"
        Clock.schedule_once(self._load_cached_data, 0.1)

    def _load_cached_data(self, dt):
        cached_data = load_cached_data()
        try:
            self.ids.username.text = cached_data["username"]
            self.ids.email.text = cached_data["email"]
            self.ids.repo_link.text = cached_data["repo_link"]
            self.ids.commit_message.text = cached_data["commit_message"]
            self.ids.local_vault_link.text = cached_data["local_vault"]
            self.ids.branch_name.text = cached_data["branch_name"]
            self.output_text += "Loaded saved settings.\n"
            Logger.info("Loaded cached data")
        except Exception as e:
            self.output_text = f"Error loading settings: {e}\n"
            Logger.error(f"Error loading cached data: {e}")

    def fetch_branches(self):
        try:
            token = self.ids.username.text.strip()
            repo_link = self.ids.repo_link.text.strip()
            if not token or not repo_link:
                self.output_text = "Error: Enter PAT and repo URL.\n"
                return
            owner, repo, _ = get_repo_info(repo_link, token)
            branches = get_branches(owner, repo, token)
            if branches:
                self.output_text = f"Available branches: {', '.join(branches)}\n"
            else:
                self.output_text = "No branches found or error fetching branches.\n"
        except ValueError as e:
            self.output_text = f"Error: {e}\n"
        except Exception as e:
            self.output_text = f"Error fetching branches: {e}\n"

    def remote_backup(self):
        try:
            vault_path = self.ids.local_vault_link.text.strip()
            token = self.ids.username.text.strip()
            repo_link = self.ids.repo_link.text.strip()
            if not all([vault_path, token, repo_link]):
                self.output_text = "Error: Vault, PAT, and repo URL required.\n"
                return
            owner, repo, default_branch = get_repo_info(repo_link, token)
            output = remote_backup_vault(vault_path, token, owner, repo, default_branch)
            self.output_text = "\n".join(output) + "\n"
        except ValueError as e:
            self.output_text = f"Error: {e}\n"
        except Exception as e:
            self.output_text = f"Remote backup error: {e}\n"

    def restore_remote(self):
        try:
            vault_path = self.ids.local_vault_link.text.strip()
            token = self.ids.username.text.strip()
            repo_link = self.ids.repo_link.text.strip()
            if not all([vault_path, token, repo_link]):
                self.output_text = "Error: Vault, PAT, and repo URL required.\n"
                return
            owner, repo, _ = get_repo_info(repo_link, token)
            output = restore_remote_vault(vault_path, token, owner, repo)
            self.output_text = "\n".join(output) + "\n"
        except ValueError as e:
            self.output_text = f"Error: {e}\n"
        except Exception as e:
            self.output_text = f"Restore remote error: {e}\n"

    def local_backup(self):
        try:
            vault_path = self.ids.local_vault_link.text.strip()
            if not vault_path:
                self.output_text = "Error: Vault path required.\n"
                return
            output = local_backup_vault(vault_path)
            self.output_text = "\n".join(output) + "\n"
        except Exception as e:
            self.output_text = f"Local backup error: {e}\n"

    def restore_local(self):
        try:
            vault_path = self.ids.local_vault_link.text.strip()
            if not vault_path:
                self.output_text = "Error: Vault path required.\n"
                return
            output = restore_local_vault(vault_path)
            self.output_text = "\n".join(output) + "\n"
        except Exception as e:
            self.output_text = f"Local restore error: {e}\n"

    def select_local_vault(self):
        try:
            base_paths = ["/sdcard/", "/storage/emulated/0/"]
            base_path = None
            for path in base_paths:
                if os.path.isdir(path) and os.access(path, os.R_OK):
                    base_path = path
                    break
            if not base_path:
                self.output_text = "Error: No accessible storage path. Grant storage permissions in Pydroid 3.\n"
                Logger.error("No accessible storage path")
                return

            content = BoxLayout(orientation='vertical')
            self.file_chooser = FileChooserListView(
                path=base_path,
                dirselect=True,
                filters=['.*'],
                size_hint=(1, 0.8)
            )
            button_layout = BoxLayout(size_hint=(1, None), height=50, padding=[10, 10], spacing=10)
            select_button = Button(text='Select Folder', background_color=(0.2, 0.5, 1, 1))
            close_button = Button(text='Close', background_color=(1, 0.3, 0.3, 1))
            button_layout.add_widget(select_button)
            button_layout.add_widget(close_button)
            content.add_widget(self.file_chooser)
            content.add_widget(button_layout)

            self.popup = Popup(title='Choose Vault Folder', content=content, size_hint=(0.9, 0.9))
            select_button.bind(on_press=self.select_current_folder)
            close_button.bind(on_press=self.popup.dismiss)
            self.file_chooser.bind(on_submit=self.set_local_vault)
            self.popup.open()
            Logger.info(f"Opened folder picker at {base_path}")
        except PermissionError:
            self.output_text = "Error: Storage permission denied. Enable in Pydroid 3 settings.\n"
            Logger.error("PermissionError: Storage access denied")
        except Exception as e:
            self.output_text = f"Error opening folder picker: {e}\n"
            Logger.error(f"Error in select_local_vault: {e}")

    def select_current_folder(self, instance):
        try:
            path = self.file_chooser.path
            if os.path.isdir(path):
                self.ids.local_vault_link.text = path
                self.output_text = f"Selected folder: {path}\n"
                Logger.info(f"Selected folder: {path}")
            else:
                self.output_text = f"Error: {path} is not a folder.\n"
                Logger.error(f"Invalid folder: {path}")
            self.popup.dismiss()
        except Exception as e:
            self.output_text = f"Error selecting folder: {e}\n"
            Logger.error(f"Error in select_current_folder: {e}")

    def set_local_vault(self, instance, selection, *args):
        try:
            if selection:
                path = selection[0]
                if os.path.isfile(path):
                    path = os.path.dirname(path)
                if os.path.isdir(path):
                    self.ids.local_vault_link.text = path
                    self.output_text = f"Selected folder: {path}\n"
                    Logger.info(f"Selected folder: {path}")
                else:
                    self.output_text = f"Error: {path} is not a valid folder.\n"
                    Logger.error(f"Invalid folder: {path}")
            else:
                self.output_text = "Error: No folder selected.\n"
                Logger.error("No selection")
            self.popup.dismiss()
        except Exception as e:
            self.output_text = f"Error setting folder: {e}\n"
            Logger.error(f"Error in set_local_vault: {e}")

    def run_commands(self):
        self.output_text = "Starting sync...\n"
        try:
            token = self.ids.username.text.strip()
            email = self.ids.email.text.strip()
            repo_link = self.ids.repo_link.text.strip()
            commit_message = self.ids.commit_message.text.strip()
            local_vault = self.ids.local_vault_link.text.strip()
            branch_name = self.ids.branch_name.text.strip() or "main"

            if not all([token, email, repo_link, local_vault]):
                self.output_text = "Error: Fill all required fields.\n"
                return
            if "@" not in email:
                self.output_text = "Error: Valid email required.\n"
                return
            if not os.path.isdir(local_vault):
                self.output_text = f"Error: Folder {local_vault} not found.\n"
                return

            owner, repo, default_branch = get_repo_info(repo_link, token)
            self.output_text += f"Validated repo: {owner}/{repo} (default: {default_branch})\n"

            files = []
            for root, _, fs in os.walk(local_vault):
                for f in fs:
                    files.append(os.path.relpath(os.path.join(root, f), local_vault))
            if not files:
                self.output_text += f"No files in {local_vault}.\n"
                return
            self.output_text += f"Found {len(files)} file(s).\n"

            if save_cached_data({
                "username": token,
                "email": email,
                "repo_link": repo_link,
                "commit_message": commit_message,
                "local_vault": local_vault,
                "branch_name": branch_name
            }):
                self.output_text += "Settings saved.\n"
            else:
                self.output_text += "Warning: Failed to save settings.\n"

            self.output_text += "Uploading files...\n"
            output, uploaded_files = upload_files_to_github(local_vault, token, owner, repo, branch_name, default_branch)
            self.output_text += "\n".join(output) + "\n"
            if not uploaded_files:
                self.output_text += "Error: No files uploaded. Check folder.\n"
                return
            if any("Error" in line for line in output):
                return

            self.output_text += "Running workflow...\n"
            output = trigger_github_workflow(token, owner, repo, branch_name, token, email, commit_message or "Auto sync", default_branch)
            self.output_text += "\n".join(output) + "\n"
        except ValueError as e:
            self.output_text = f"Error: {e}\n"
        except Exception as e:
            self.output_text = f"Sync error: {e}\n"

    def clear_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                os.remove(CACHE_FILE)
                self.output_text = "Cache cleared.\n"
            except Exception as e:
                self.output_text = f"Error clearing cache: {e}\n"
        else:
            self.output_text = "No cache found.\n"
        try:
            self.ids.username.text = ""
            self.ids.email.text = ""
            self.ids.repo_link.text = ""
            self.ids.commit_message.text = ""
            self.ids.local_vault_link.text = ""
            self.ids.branch_name.text = ""
        except Exception as e:
            self.output_text = f"Error resetting fields: {e}\n"

class GitConfigApp(App):
    def build(self):
        ensure_directories()
        return GitConfigLayout()

if __name__ == "__main__":
    GitConfigApp().run()