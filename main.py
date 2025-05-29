# main.py
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
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.logger import Logger
import time

# Platform-specific paths
IS_MOBILE = os.path.exists("/sdcard/")
if IS_MOBILE:
    BASE_DIR = "/storage/emulated/0/Download/Syncer"
    VAULT_DIR = "/sdcard/Obsidian-Vault"
    STORAGE_PATHS = ["/sdcard/", "/storage/emulated/0/"]
else:
    BASE_DIR = os.path.join(os.path.expanduser("~"), ".syncer")
    VAULT_DIR = os.path.join(os.path.expanduser("~"), "Obsidian-Vault")
    STORAGE_PATHS = [os.path.expanduser("~")]
CACHE_FILE = os.path.join(BASE_DIR, ".cache.json")
TEMP_BACKUP = os.path.join(BASE_DIR, "backup.zip")

def ensure_directories():
    for dir_path in [BASE_DIR]:
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

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

def create_readme():
    readme_content = """# Syncer App

Sync your Obsidian Vault to a GitHub repository using a Kivy-based app on mobile (Android via Pydroid 3) or desktop (Linux/Windows).

## Features
- Sync local vault folder to GitHub repo.
- Select or create custom branches (defaults to `main`).
- Remote backup to `backup` branch.
- Restore from latest remote backup.
- Auto-merge pull requests.
- Validates inputs and handles errors.

## Requirements
- **Python**: 3.13.2
- **Kivy**: 2.3.1 (`pip install kivy==2.3.1`)
- **Requests**: (`pip install requests`)
- **GitHub PAT**: With `repo`, `workflow`, `admin:repo_hook` scopes (github.com/settings/tokens)
- **GitHub Repo**: With `.github/workflows/git-sync.yml` (see repo for template)

## Installation

### Mobile (Pydroid 3, Android)
1. Install Pydroid 3 from Google Play.
2. Grant storage permissions:
   ```bash
   ls /sdcard/
   ```
3. Install dependencies:
   ```bash
   pip install kivy==2.3.1 requests
   ```
4. Create app directory:
   ```bash
   mkdir -p /storage/emulated/0/Download/Syncer
   ```
5. Save `main.py` and `gitconfig.kv` to `/storage/emulated/0/Download/Syncer/`.
6. Create vault:
   ```bash
   mkdir -p /sdcard/Obsidian-Vault
   echo "Test note" > /sdcard/Obsidian-Vault/test.md
   ```

### Desktop (Linux/Windows)
1. Install Python 3.13.2.
2. Install dependencies:
   ```bash
   pip install kivy==2.3.1 requests
   ```
3. Create app directory:
   ```bash
   mkdir -p ~/.syncer
   ```
4. Save `main.py` and `gitconfig.kv` to `~/.syncer/`.
5. Create vault:
   ```bash
   mkdir -p ~/Obsidian-Vault
   echo "Test note" > ~/Obsidian-Vault/test.md
   ```

## Usage
1. **Run App**:
   - Mobile:
     ```bash
     cd /storage/emulated/0/Download/Syncer
     python main.py
     ```
   - Desktop:
     ```bash
     cd ~/.syncer
     python main.py
     ```
2. **Fill Fields**:
   - **GitHub PAT**: Your personal access token.
   - **Git Email**: Your GitHub email (e.g., user@example.com).
   - **Repository Link**: e.g., https://github.com/DEV-Users/Syncer
   - **Commit Message**: Optional, defaults to "Auto sync".
   - **Local Vault Link**: Select vault folder (e.g., `/sdcard/Obsidian-Vault` or `~/Obsidian-Vault`) via 📁.
   - **Branch Name**: Optional, defaults to `main`.
3. **Actions**:
   - **Fetch Branches**: List repo branches.
   - **Run Git Commands**: Sync vault to repo.
   - **Remote Backup**: Save vault zip to `backup` branch.
   - **Restore Remote**: Restore from latest backup.
   - **Clear Cache**: Reset fields and cache.

## Troubleshooting
- **Folder Picker Fails**: Ensure storage permissions (mobile) or folder access (desktop).
- **Sync Fails**: Check PAT scopes, repo URL, and workflow file.
- **Backup/Restore Fails**: Verify `backup` branch and PAT write access.
- **Logs**:
  - Mobile: `/storage/emulated/0/Download/Syncer/.kivy/logs/kivy_*.txt`
  - Desktop: `~/.config/kivy/logs/kivy_*.txt`

## Notes
- Source: github.com/DEV-Users/Syncer
- PAT stored in cache (encrypted in future updates).
- Workflow auto-creates PRs, merged automatically.

"""
    return base64.b64encode(readme_content.encode("utf-8")).decode("utf-8")

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

        default_branch = repo_info.json().get("default_branch", "main")
        branch_check = requests.get(f"https://api.github.com/repos/{owner}/{repo}/branches/main", headers=headers)
        if branch_check.status_code != 200:
            initial_content = base64.b64encode("Initial commit".encode("utf-8")).decode("utf-8")
            commit_data = {
                "message": "Initialize repository",
                "content": initial_content,
                "branch": "main"
            }
            create_file = requests.put(
                f"https://api.github.com/repos/{owner}/{repo}/contents/.init",
                headers=headers,
                json=commit_data
            )
            if create_file.status_code not in (200, 201):
                raise ValueError(f"Error creating main branch: {create_file.json().get('message', 'Unknown error')}")
            update_repo = requests.patch(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers,
                json={"default_branch": "main"}
            )
            if update_repo.status_code != 200:
                raise ValueError(f"Error setting main as default: {update_repo.json().get('message', 'Unknown error')}")
            default_branch = "main"
        return owner, repo, default_branch
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

def remote_backup_vault(vault_path, token, owner, repo, default_branch):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    output = []
    try:
        zip_result = create_zip(vault_path, TEMP_BACKUP)
        if "Error" in zip_result:
            return [zip_result]
        output.append(zip_result)

        backup_ref = requests.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/backup", headers=headers)
        if backup_ref.status_code != 200:
            default_ref = requests.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{default_branch}", headers=headers)
            if default_ref.status_code != 200:
                output.append(f"Error getting {default_branch} ref: {default_ref.json().get('message', 'Unknown error')}")
                return output
            create_backup = requests.post(
                f"https://api.github.com/repos/{owner}/{repo}/git/refs",
                headers=headers,
                json={"ref": "refs/heads/backup", "sha": default_ref.json()["object"]["sha"]}
            )
            if create_backup.status_code != 201:
                output.append(f"Error creating backup branch: {create_backup.json().get('message', 'Unknown error')}")
                return output
            output.append("Created backup branch")

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
        output.append("Uploaded remote backup")
        os.remove(TEMP_BACKUP)

        pr_output = auto_merge_pull_requests(token, owner, repo)
        output.extend(pr_output)
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
        contents = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents?ref=backup", headers=headers)
        if contents.status_code != 200:
            output.append(f"Error accessing backup branch: {contents.json().get('message', 'Unknown error')}")
            return output
        backups = [item for item in contents.json() if item["name"].endswith(".zip")]
        if not backups:
            output.append("Error: No backups found in backup branch")
            return output
        latest_backup = max(backups, key=lambda x: x["name"])
        download_url = latest_backup["download_url"]

        response = requests.get(download_url)
        if response.status_code != 200:
            output.append(f"Error downloading backup: {response.status_code}")
            return output
        with open(TEMP_BACKUP, "wb") as f:
            f.write(response.content)
        output.append(f"Downloaded backup: {latest_backup['name']}")

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

def auto_merge_pull_requests(token, owner, repo):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    output = []
    try:
        pulls = requests.get(f"https://api.github.com/repos/{owner}/{repo}/pulls", headers=headers)
        if pulls.status_code != 200:
            output.append(f"Error fetching PRs: {pulls.json().get('message', 'Unknown error')}")
            return output
        for pr in pulls.json():
            pr_number = pr["number"]
            merge = requests.put(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/merge",
                headers=headers,
                json={"merge_method": "squash"}
            )
            if merge.status_code == 200:
                output.append(f"Merged PR #{pr_number}")
            else:
                output.append(f"Error merging PR #{pr_number}: {merge.json().get('message', 'Unknown error')}")
        return output
    except requests.RequestException as e:
        output.append(f"Network error merging PRs: {e}")
        return output
    except Exception as e:
        output.append(f"Error merging PRs: {e}")
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
            output.append(f"Error: Folder {directory} not found")
            return output, uploaded_files

        readme_check = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents/readme.md?ref={branch}", headers=headers)
        if readme_check.status_code == 404:
            readme_content = create_readme()
            data = {
                "message": "Add README.md",
                "content": readme_content,
                "branch": branch
            }
            readme_upload = requests.put(
                f"https://api.github.com/repos/{owner}/{repo}/contents/README.md",
                headers=headers,
                json=data
            )
            if readme_upload.status_code in (200, 201):
                output.append("Uploaded README.md")
                uploaded_files.append("README.md")
            else:
                output.append(f"Error uploading README: {readme_upload.json().get('message', 'Unknown error')}")

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
                    if upload.status_code in (200, 201):
                        output.append(f"Uploaded: {rel_path}")
                        uploaded_files.append(rel_path)
                    else:
                        output.append(f"Error uploading {rel_path}: {upload.json().get('message', 'Unknown error')}")
                except Exception as e:
                    output.append(f"Error processing {rel_path}: {e}")
        return output, uploaded_files
    except requests.RequestException as e:
        output.append(f"Network error: {e}")
        return output, uploaded_files
    except Exception as e:
        output.append(f"Unexpected error: {e}")
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
                          "Steps:\n1. Get a PAT (repo, workflow, admin:repo_hook scopes): github.com/settings/tokens\n" + \
                          "2. Add .github/workflows/git-sync.yml to github.com/DEV-Users/Syncer\n" + \
                          "3. Fill fields, hit 'Run Git Commands'.\n\n" + \
                          "Open source: github.com/DEV-Users/Syncer\nNo sketchy stuff! <3\n"
        self.parent_scroll = ScrollView(
            size_hint=(1, 1),
            pos=(0, 0),
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=4,
            bar_color=(0.25, 0.55, 1, 1),
            bar_inactive_color=(0.8, 0.8, 0.85, 1)
        )
        self.parent_scroll.add_widget(self)
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
            self.output_text += f"Error loading settings: {e}\n"
            Logger.error(f"Error loading cached data: {e}")

    def fetch_branches(self, instance):
        try:
            token = self.ids.username.text.strip()
            repo_link = self.ids.repo_link.text.strip()
            if not token or not repo_link:
                self.output_text = "Error: Enter PAT and repo URL to fetch branches.\n"
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

    def remote_backup(self, instance):
        try:
            vault_path = self.ids.local_vault_link.text.strip()
            token = self.ids.username.text.strip()
            repo_link = self.ids.repo_link.text.strip()
            if not all([vault_path, token, repo_link]):
                self.output_text = "Error: Vault folder, PAT, and repo URL are required.\n"
                return
            owner, repo, default_branch = get_repo_info(repo_link, token)
            output = remote_backup_vault(vault_path, token, owner, repo, default_branch)
            self.output_text = "\n".join(output) + "\n"
        except ValueError as e:
            self.output_text = f"Error: {e}\n"
        except Exception as e:
            self.output_text = f"Remote backup error: {e}\n"

    def restore_remote(self, instance):
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

    def select_local_vault(self, instance=None):
        try:
            base_path = None
            for path in STORAGE_PATHS:
                if os.path.exists(path) and os.access(path, os.R_OK):
                    base_path = path
                    break
            if not base_path:
                self.output_text = "Error: No storage access. Grant permissions.\n"
                Logger.error("No accessible storage path")
                return

            content = BoxLayout(orientation='vertical')
            self.file_chooser = FileChooserListView(
                path=base_path,
                dirselect=True,
                filters=['*'],
                size_hint=(1, 0.8)
            )
            button_layout = BoxLayout(size_hint=(1, 0.2), spacing=10, padding=[10, 10])
            select_button = Button(text='Select This Folder', background_color=(0.25, 0.55, 1, 1))
            close_button = Button(text='Close', background_color=(1, 0.35, 0.35, 1))
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

            pr_output = auto_merge_pull_requests(token, owner, repo)
            self.output_text += "\n".join(pr_output) + "\n"
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
        layout = GitConfigLayout()
        return layout.parent_scroll

if __name__ == "__main__":
    GitConfigApp().run()
