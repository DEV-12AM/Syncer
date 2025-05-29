import os
import json
import base64
import requests
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import StringProperty
from kivy.uix.filechooser import FileChooserListView
from kivy.logger import Logger
import time

def load_cached_data():
    cache_file = os.path.expanduser("~/.git_config_cache.json")
    defaults = {"username": "", "email": "", "repo_link": "", "commit_message": "", "local_vault_link": ""}
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                Logger.error(f"Cache file {cache_file} contains invalid data")
                return defaults
            defaults.update(data)
        return defaults
    except Exception as e:
        Logger.error(f"Error loading cache: {e}")
        return defaults

def save_cached_data(data):
    cache_file = os.path.expanduser("~/.git_config_cache.json")
    try:
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        Logger.error(f"Error saving cache: {e}")

def get_repo_info(repo_link):
    """Extract owner and repo name from GitHub repo link."""
    try:
        if not repo_link.startswith("https://github.com/"):
            return None, None
        parts = repo_link.strip("/").split("/")
        return parts[2], parts[3]
    except Exception as e:
        Logger.error(f"Error parsing repo link: {e}")
        return None, None

def upload_files_to_github(directory, token, owner, repo, branch="temp-sync"):
    """Upload files from directory to a temporary branch."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    output = []
    try:
        if not os.path.isdir(directory):
            output.append(f"Error: {directory} does not exist")
            return output

        # Create a temporary branch
        ref = requests.get(f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/master.json", headers=headers)
        if ref.status_code != 200:
            output.append(f"Error getting master ref: {ref.json().get('message', 'Unknown error')}")
            return output
        sha = ref.json()["object"]["sha"]

        create_branch = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch}", "sha": sha}
        )
        if create_branch.status_code != 201:
            output.append(f"Error creating branch: {create_branch.json().get('message', 'Unknown error')}")
            return output
        output.append(f"Created temporary branch: {branch}")

        # Upload files
        for root, _, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, directory)
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
        return output
    except Exception as e:
        output.append(f"Unexpected error uploading files: {e}")
        return output

def trigger_github_workflow(token, owner, repo, branch, username, email, commit_message):
    """Trigger a GitHub Actions workflow to run Git commands."""
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
                "commit_message": commit_message or "Auto commit"
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
        output.append("Triggered GitHub Actions workflow")

        # Poll workflow status
        for _ in range(10):  # Try for ~2 minutes
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
                if status == "completed":
                    if conclusion == "success":
                        output.append("Workflow completed successfully")
                    else:
                        output.append(f"Workflow failed: {conclusion}")
                    return output
            time.sleep(15)  # Wait before polling again
        output.append("Workflow status: Timed out")
        return output
    except Exception as e:
        output.append(f"Unexpected error in workflow: {e}")
        return output

class GitConfigLayout(BoxLayout):
    output_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        cached_data = load_cached_data()
        self.ids.username.text = cached_data["username"]
        self.ids.email.text = cached_data["email"]
        self.ids.repo_link.text = cached_data["repo_link"]
        self.ids.commit_message.text = cached_data["commit_message"]
        self.ids.local_vault_link.text = cached_data["local_vault_link"]
        self.output_text = "*Enter your GitHub details to sync.*\n\n" + \
                          "How to setup:\n1. Create a GitHub Personal Access Token (PAT) with 'repo' and 'workflow' scopes:\n   See: https://docs.github.com/en/authentication\n" + \
                          "2. Add a workflow file (.github/workflows/git-sync.yml) to your repo (see app instructions).\n" + \
                          "3. Fill in the fields and click 'Run Git Commands'.\n\n" + \
                          "Note:\nThis project is open source: https://github.com/DEV-12AM/Syncer.git\n" + \
                          "We are NOT stealing any data from you <3"

    def select_local_vault(self):
        try:
            self.file_chooser = FileChooserListView(path='/sdcard/', dirselect=True, filters=['*'])
            self.file_chooser.bind(on_submit=self.set_local_vault)
            self.add_widget(self.file_chooser)
        except Exception as e:
            self.output_text = f"Error opening file chooser: {e}\n"

    def set_local_vault(self, instance, selection, *args):
        if selection and os.path.isdir(selection[0]):
            self.ids.local_vault_link.text = selection[0]
        else:
            self.output_text = "Error: Please select a valid directory.\n"
        if hasattr(self, 'file_chooser'):
            self.remove_widget(self.file_chooser)
            del self.file_chooser

    def run_commands(self):
        Logger.info("Run Git Commands button pressed")
        self.output_text = "Button pressed, starting Git commands...\n\n"
        try:
            username = self.ids.username.text.strip()
            email = self.ids.email.text.strip()
            repo_link = self.ids.repo_link.text.strip()
            commit_message = self.ids.commit_message.text.strip()
            local_vault_link = self.ids.local_vault_link.text.strip()

            if not all([username, email, repo_link, local_vault_link]):
                self.output_text = "Error: Username, Email, Repository Link, and Local Vault Link are required.\n"
                return

            if not os.path.isdir(local_vault_link):
                self.output_text = f"Error: Directory {local_vault_link} does not exist.\n"
                return

            # Get PAT from environment or prompt user (for testing, assume input)
            token = os.getenv("GITHUB_TOKEN") or self.ids.username.text.strip()  # Replace with secure input if needed
            owner, repo = get_repo_info(repo_link)
            if not owner or not repo:
                self.output_text = "Error: Invalid repository link. Use format: https://github.com/owner/repo\n"
                return

            save_cached_data({
                "username": username,
                "email": email,
                "repo_link": repo_link,
                "commit_message": commit_message,
                "local_vault_link": local_vault_link
            })

            self.output_text += "Uploading files to GitHub...\n\n"
            output = upload_files_to_github(local_vault_link, token, owner, repo)
            if any("Error" in line for line in output):
                self.output_text = "\n\n".join(output)
                return

            self.output_text += "\n\nTriggering GitHub Actions workflow...\n\n"
            output.extend(trigger_github_workflow(token, owner, repo, "temp-sync", username, email, commit_message))
            self.output_text = "\n\n".join(output)
        except Exception as e:
            self.output_text = f"Error in run_commands: {e}\n"
            Logger.error(f"run_commands failed: {e}")

    def clear_cache(self):
        cache_file = os.path.expanduser("~/.git_config_cache.json")
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
                self.output_text = "Cache cleared.\n"
            except Exception as e:
                self.output_text = f"Error clearing cache: {e}\n"
        else:
            self.output_text = "Cache file does not exist.\n"
        self.ids.username.text = ""
        self.ids.email.text = ""
        self.ids.repo_link.text = ""
        self.ids.commit_message.text = ""
        self.ids.local_vault_link.text = ""

class GitConfigApp(App):
    def build(self):
        return GitConfigLayout()

if __name__ == "__main__":
    GitConfigApp().run()