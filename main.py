import os
import json
import base64
try:
    import requests
except ImportError:
    print("Error: 'requests' module not found. Run: pip install requests")
    exit(1)
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import StringProperty
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.logger import Logger
import time

def load_cached_data():
    cache_file = "/storage/emulated/0/Download/Syncer/.cache.json"
    defaults = {"username": "", "email": "", "repo_link": "", "commit_message": "", "local_vault_link": ""}
    try:
        if os.path.exists(cache_file) and os.access(cache_file, os.R_OK):
            with open(cache_file, 'r') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                Logger.error(f"Cache file {cache_file} contains invalid data")
                return defaults
            defaults.update(data)
            Logger.info(f"Loaded cache: {cache_file}")
        else:
            Logger.info(f"Cache file {cache_file} not found or not readable")
        return defaults
    except Exception as e:
        Logger.error(f"Error loading cache: {e}")
        return defaults

def save_cached_data(data):
    cache_file = "/storage/emulated/0/Download/Syncer/.cache.json"
    try:
        cache_dir = os.path.dirname(cache_file)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        if not os.access(cache_dir, os.W_OK):
            Logger.error(f"No write permissions for {cache_dir}")
            return False
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=4)
        Logger.info(f"Saved cache: {cache_file}")
        return True
    except Exception as e:
        Logger.error(f"Error saving cache: {e}")
        return False

def get_repo_info(repo_link):
    try:
        if not repo_link.startswith("https://github.com/"):
            return None, None
        parts = repo_link.rstrip("/").split("/")
        return parts[-2], parts[-1]
    except Exception as e:
        Logger.error(f"Error parsing repo link: {e}")
        return None, None

def upload_files_to_github(directory, token, owner, repo, branch="temp-sync"):
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

        repo_info = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        if repo_info.status_code != 200:
            output.append(f"Error getting repo info: {repo_info.json().get('message', 'Unknown error')} (Status: {repo_info.status_code})")
            return output, uploaded_files
        default_branch = repo_info.json().get("default_branch", "main")

        ref = requests.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{default_branch}", headers=headers)
        if ref.status_code != 200:
            output.append(f"Error getting {default_branch} ref: {ref.json().get('message', 'Unknown error')} (Status: {ref.status_code})")
            return output, uploaded_files
        sha = ref.json().get("object", {}).get("sha")
        if not sha:
            output.append(f"Error: No SHA found for {default_branch}")
            return output, uploaded_files

        create_branch = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": sha}
        )
        if create_branch.status_code != 201:
            output.append(f"Error creating branch: {create_branch.json().get('message', 'Unknown error')} (Status: {create_branch.status_code})")
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
                        output.append(f"Error uploading {rel_path}: {upload.json().get('message', 'Unknown error')} (Status: {upload.status_code})")
                    else:
                        output.append(f"Uploaded {rel_path}")
                        uploaded_files.append(rel_path)
                except Exception as e:
                    output.append(f"Error processing {rel_path}: {e}")
        return output, uploaded_files
    except Exception as e:
        output.append(f"Unexpected error uploading files: {e}")
        return output, uploaded_files

def trigger_github_workflow(token, owner, repo, branch, username, email, commit_message):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    output = []
    try:
        repo_info = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        if repo_info.status_code != 200:
            output.append(f"Error getting repo info: {repo_info.json().get('message', 'Unknown error')} (Status: {repo_info.status_code})")
            return output
        default_branch = repo_info.json().get("default_branch", "main")

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
            output.append(f"Error triggering workflow: {response.json().get('message', 'Unknown error')} (Status: {response.status_code})")
            return output
        output.append("Triggered workflow")

        for _ in range(12):
            runs = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/actions/runs",
                headers=headers,
                params={"branch": branch}
            )
            if runs.status_code != 200:
                output.append(f"Error checking workflow status: {runs.json().get('message', 'Unknown error')} (Status: {runs.status_code})")
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
                          "4. Fill fields, hit 'Sync Now'.\n\n" + \
                          "Open source: github.com/DEV-12AM/Syncer\nNo sketchy stuff! <3\n"
        Clock.schedule_once(self._load_cached_data, 0.1)

    def _load_cached_data(self, dt):
        cached_data = load_cached_data()
        try:
            if 'username' in self.ids:
                self.ids.username.text = cached_data["username"]
            if 'email' in self.ids:
                self.ids.email.text = cached_data["email"]
            if 'repo_link' in self.ids:
                self.ids.repo_link.text = cached_data["repo_link"]
            if 'commit_message' in self.ids:
                self.ids.commit_message.text = cached_data["commit_message"]
            if 'local_vault_link' in self.ids:
                self.ids.local_vault_link.text = cached_data["local_vault_link"]
            Logger.info("Loaded cached data")
            self.output_text += "Loaded saved settings.\n"
        except Exception as e:
            self.output_text = f"Error loading settings: {e}\n"
            Logger.error(f"Error loading cached data: {e}")

    def select_local_vault(self):
        try:
            base_path = '/sdcard/'
            if not os.path.exists(base_path) or not os.access(base_path, os.R_OK):
                self.output_text = "Error: No storage permissions or /sdcard/ inaccessible. Check app settings.\n"
                Logger.error("Storage permissions missing")
                return

            content = BoxLayout(orientation='vertical')
            self.file_chooser = FileChooserListView(
                path=base_path,
                dirselect=True,
                filters=['*'],
                size_hint=(1, 0.8)
            )
            button_layout = BoxLayout(
                size_hint=(1, 0.2),
                spacing=6,
                padding=[6, 6]
            )
            select_button = Button(
                text='Select This Folder',
                background_color=(0.25, 0.55, 1, 1)
            )
            close_button = Button(
                text='Close',
                background_color=(1, 0.35, 0.35, 1)
            )
            button_layout.add_widget(select_button)
            button_layout.add_widget(close_button)
            content.add_widget(self.file_chooser)
            content.add_widget(button_layout)

            self.popup = Popup(
                title='Choose Vault Folder',
                content=content,
                size_hint=(0.95, 0.95)
            )
            select_button.bind(on_press=self.select_current_folder)
            close_button.bind(on_press=self.popup.dismiss)
            self.file_chooser.bind(on_submit=self.set_local_vault)
            self.popup.open()
            Logger.info("Opened folder picker")
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

    def set_local_vault(self, instance, selection):
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
        Logger.info("Sync Now pressed")
        self.output_text = "Starting sync...\n\n"
        try:
            username = self.ids.username.text.strip()  # PAT
            email = self.ids.email.text.strip()
            repo_link = self.ids.repo_link.text.strip()
            commit_message = self.ids.commit_message.text.strip()
            local_vault_link = self.ids.local_vault_link.text.strip()

            if not all([username, email, repo_link, local_vault_link]):
                self.output_text = "Error: Fill all required fields.\n"
                return

            if not os.path.isdir(local_vault_link):
                self.output_text = f"Error: Folder {local_vault_link} not found.\n"
                return

            owner, repo = get_repo_info(repo_link)
            if not owner or not repo:
                self.output_text = "Error: Invalid repo URL. Use: https://github.com/owner/repo\n"
                return

            self.output_text += "Checking files...\n\n"
            files = []
            for root, _, fs in os.walk(local_vault_link):
                for f in fs:
                    files.append(os.path.relpath(os.path.join(root, f), local_vault_link))
            if not files:
                self.output_text = f"Error: No files in {local_vault_link}.\n"
                return
            self.output_text += f"Found {len(files)} file(s).\n\n"

            self.output_text += "Saving settings...\n\n"
            if save_cached_data({
                "username": username,
                "email": email,
                "repo_link": repo_link,
                "commit_message": commit_message,
                "local_vault_link": local_vault_link
            }):
                self.output_text += "Settings saved.\n\n"
            else:
                self.output_text += "Warning: Failed to save settings.\n\n"

            self.output_text += "Uploading files...\n\n"
            output, uploaded_files = upload_files_to_github(local_vault_link, username, owner, repo)
            if not uploaded_files:
                output.append("Error: No files uploaded. Check folder.")
                self.output_text = "\n\n".join(output)
                return

            if any("Error" in line for line in output):
                self.output_text = "\n\n".join(output)
                return

            self.output_text += "\n\nRunning workflow...\n\n"
            output.extend(trigger_github_workflow(username, owner, repo, "temp-sync", username, email, commit_message))
            self.output_text = "\n\n".join(output)
        except Exception as e:
            self.output_text = f"Sync error: {e}\n"
            Logger.error(f"run_commands failed: {e}")

    def clear_cache(self):
        cache_file = "/storage/emulated/0/Download/Syncer/.cache.json"
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
                self.output_text = "Cache cleared.\n"
                Logger.info(f"Cache deleted: {cache_file}")
            except Exception as e:
                self.output_text = f"Error clearing cache: {e}\n"
                Logger.error(f"Error clearing cache: {e}")
        else:
            self.output_text = "No cache found.\n"
        try:
            self.ids.username.text = ""
            self.ids.email.text = ""
            self.ids.repo_link.text = ""
            self.ids.commit_message.text = ""
            self.ids.local_vault_link.text = ""
        except Exception as e:
            self.output_text = f"Error resetting fields: {e}\n"
            Logger.error(f"Error clearing UI: {e}")

class GitConfigApp(App):
    def build(self):
        return GitConfigLayout()

if __name__ == "__main__":
    GitConfigApp().run()
