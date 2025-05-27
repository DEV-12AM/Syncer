import os
import subprocess
import json
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
import tkinter.font as tkfont

def load_cached_data():
    cache_file = os.path.expanduser("~/.git_config_cache.json")
    defaults = {"username": "", "email": "", "repo_link": "", "commit_message": "", "local_vault_link": "", "onedrive_vault_link": ""}
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    print(f"Error: Cache file {cache_file} contains invalid data, using defaults")
                    return defaults
                defaults.update(data)
                return defaults
        else:
            print(f"Cache file {cache_file} does not exist, using defaults")
            return defaults
    except json.JSONDecodeError:
        print(f"Error: Cache file {cache_file} contains invalid JSON, using defaults")
        return defaults
    except PermissionError:
        print(f"Error: Permission denied accessing cache file {cache_file}, using defaults")
        return defaults
    except Exception as e:
        print(f"Unexpected error loading cache file {cache_file}: {e}, using defaults")
        return defaults

def save_cached_data(data):
    cache_file = os.path.expanduser("~/.git_config_cache.json")
    try:
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=2)
    except PermissionError:
        print(f"Error: Permission denied writing to cache file {cache_file}")
    except Exception as e:
        print(f"Unexpected error saving cache file {cache_file}: {e}")

def check_remote_exists(directory):
    try:
        result = subprocess.run(["git", "remote", "-v"], cwd=directory, check=True, capture_output=True, text=True)
        return "origin" in result.stdout
    except subprocess.CalledProcessError:
        return False

def has_uncommitted_changes(directory):
    try:
        result = subprocess.run(["git", "status", "--porcelain"], cwd=directory, check=True, capture_output=True, text=True)
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False

def run_git_commands(directory, username, email, repo_link, commit_message):
    output = []
    commit_msg = commit_message.strip() if commit_message.strip() else "Auto commit"
    try:
        if not os.path.isdir(directory):
            output.append(f"Error: Directory {directory} does not exist")
            return output
        os.chdir(directory)
        output.append(f"Changed to directory: {directory}")

        subprocess.run(["git", "config", "user.name", username], check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", email], check=True, capture_output=True, text=True)
        output.append(f"Successfully configured Git user: {username} <{email}>")

        if check_remote_exists(directory):
            subprocess.run(["git", "remote", "set-url", "origin", repo_link], check=True, capture_output=True, text=True)
            output.append(f"Successfully updated remote origin to {repo_link}")
        else:
            subprocess.run(["git", "remote", "add", "origin", repo_link], check=True, capture_output=True, text=True)
            output.append(f"Successfully added remote origin to {repo_link}")

        try:
            result = subprocess.run(["git", "fetch", "origin"], check=True, capture_output=True, text=True)
            output.append("Successfully fetched Git repository")
        except subprocess.CalledProcessError as e:
            output.append(f"Failed to fetch Git repository: {e}\n{e.stderr}")
            return output

        if has_uncommitted_changes(directory):
            subprocess.run(["git", "add", "."], check=True, capture_output=True, text=True)
            try:
                subprocess.run(["git", "commit", "-m", commit_msg], check=True, capture_output=True, text=True)
                output.append(f"Successfully committed local changes before merge with message '{commit_msg}'")
            except subprocess.CalledProcessError as e:
                output.append(f"Failed to commit pre-merge changes: {e}\n{e.stderr}")
                return output
        else:
            output.append("No local changes to commit before merge")

        try:
            subprocess.run(["git", "merge", "origin/master", "--no-edit"], check=True, capture_output=True, text=True)
            output.append("Successfully merged with origin/master")
        except subprocess.CalledProcessError:
            output.append("Standard merge failed, attempting with --allow-unrelated-histories...")
            try:
                subprocess.run(["git", "merge", "origin/master", "--no-edit", "--allow-unrelated-histories"], check=True, capture_output=True, text=True)
                output.append("Successfully merged with --allow-unrelated-histories")
            except subprocess.CalledProcessError as e:
                output.append(f"Failed to merge with --allow-unrelated-histories: {e}\n{e.stderr}")
                return output

        if has_uncommitted_changes(directory):
            subprocess.run(["git", "add", "."], check=True, capture_output=True, text=True)
            try:
                subprocess.run(["git", "commit", "-m", commit_msg], check=True, capture_output=True, text=True)
                output.append(f"Successfully committed changes after merge with message '{commit_msg}'")
            except subprocess.CalledProcessError as e:
                output.append(f"Failed to commit after merge: {e}\n{e.stderr}")
                return output
        else:
            output.append("No changes to commit after merge")

        try:
            subprocess.run(["git", "push", "origin", "master"], check=True, capture_output=True, text=True)
            output.append(f"Successfully pushed to origin/master")
        except subprocess.CalledProcessError as e:
            output.append(f"Failed to push to origin/master: {e}\n{e.stderr}")
            return output

        output.append(f"Git operations completed successfully in {directory}")

    except subprocess.CalledProcessError as e:
        output.append(f"Error executing Git command in {directory}: {e}\n{e.stderr}")
    except FileNotFoundError:
        output.append(f"Directory {directory} not found")
    except Exception as e:
        output.append(f"Unexpected error in {directory}: {e}")
    return output

def create_app():
    window = tk.Tk()
    window.title("Syncer App")
    window.geometry("600x800")
    window.configure(bg="#f0f0f0")

    # Define custom font
    custom_font = tkfont.Font(family="Arial", size=10)

    # Load cached data
    cached_data = load_cached_data()
    if cached_data is None:
        cached_data = {"username": "", "email": "", "repo_link": "", "commit_message": "", "local_vault_link": "", "onedrive_vault_link": ""}

    # Form frame
    form_frame = ttk.Frame(window, padding="10")
    form_frame.grid(row=0, column=0, sticky="nsew")
    form_frame.option_add("*Font", custom_font)

    # Username
    ttk.Label(form_frame, text="Git Username").grid(row=0, column=0, sticky="w", pady=2)
    username_entry = ttk.Entry(form_frame, width=50)
    username_entry.insert(0, cached_data["username"])
    username_entry.grid(row=1, column=0, sticky="ew", pady=2)

    # Email
    ttk.Label(form_frame, text="Git Email").grid(row=2, column=0, sticky="w", pady=2)
    email_entry = ttk.Entry(form_frame, width=50)
    email_entry.insert(0, cached_data["email"])
    email_entry.grid(row=3, column=0, sticky="ew", pady=2)

    # Repo Link
    ttk.Label(form_frame, text="Repository Link").grid(row=4, column=0, sticky="w", pady=2)
    repo_entry = ttk.Entry(form_frame, width=50)
    repo_entry.insert(0, cached_data["repo_link"])
    repo_entry.grid(row=5, column=0, sticky="ew", pady=2)

    # Commit Message (Optional)
    ttk.Label(form_frame, text="Commit Message (Optional)").grid(row=6, column=0, sticky="w", pady=2)
    commit_message_entry = ttk.Entry(form_frame, width=50)
    commit_message_entry.insert(0, cached_data["commit_message"])
    commit_message_entry.grid(row=7, column=0, sticky="ew", pady=2)

    # Local Vault Link
    ttk.Label(form_frame, text="Local Vault Link").grid(row=8, column=0, sticky="w", pady=2)
    local_vault_frame = ttk.Frame(form_frame)
    local_vault_frame.grid(row=9, column=0, sticky="ew", pady=2)
    local_vault_frame.option_add("*Font", custom_font)
    local_vault_entry = ttk.Entry(local_vault_frame, width=45)
    local_vault_entry.insert(0, cached_data["local_vault_link"])
    local_vault_entry.grid(row=0, column=0, sticky="ew")
    def browse_local_vault():
        path = filedialog.askdirectory()
        if path:
            local_vault_entry.delete(0, tk.END)
            local_vault_entry.insert(0, path)
    ttk.Button(local_vault_frame, text="📁", command=browse_local_vault, width=3).grid(row=0, column=1, padx=5)

    # OneDrive Vault Link (Optional)
    ttk.Label(form_frame, text="OneDrive Vault Link (Optional)").grid(row=10, column=0, sticky="w", pady=2)
    onedrive_vault_frame = ttk.Frame(form_frame)
    onedrive_vault_frame.grid(row=11, column=0, sticky="ew", pady=2)
    onedrive_vault_frame.option_add("*Font", custom_font)
    onedrive_vault_entry = ttk.Entry(onedrive_vault_frame, width=45)
    onedrive_vault_entry.insert(0, cached_data["onedrive_vault_link"])
    onedrive_vault_entry.grid(row=0, column=0, sticky="ew")
    def browse_onedrive_vault():
        path = filedialog.askdirectory()
        if path:
            onedrive_vault_entry.delete(0, tk.END)
            onedrive_vault_entry.insert(0, path)
    ttk.Button(onedrive_vault_frame, text="📁", command=browse_onedrive_vault, width=3).grid(row=0, column=1, padx=5)

    # Output area
    output_text = scrolledtext.ScrolledText(window, width=70, height=20, wrap=tk.WORD, font=custom_font)
    output_text.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

    # Configure text tags for colors
    output_text.tag_configure("error", foreground="red", font=custom_font)
    output_text.tag_configure("success", foreground="green", font=custom_font)

    # Initial instructions
    initial_message = """*You must install and login to Git bash before using this app.*

How to install:
1. Download and install Git from https://git-scm.com/downloads

How to login:
1. Open Git bash and type "git config --global user.name "your_username" to set your username.
2. Type "git config --global user.email "your_email" to set your email.
3. For authentication, create a Personal Access Token (PAT) on GitHub and use it instead of a password. See https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token
   Note: The command "git config --global user.password" is not recommended. Use a PAT or SSH key.

How to use:
1. Create a new repository on your GitHub account, e.g., "Notes", and make it private.
2. Copy the link of the repository and paste it into the text box.
3. Fill the missing data and click the "Run Git Commands" button.

Note:
This project is open source and free to edit <3
We are NOT stealing any data from you <3
Repository link:
https://github.com/DEV-12AM/Syncer.git
"""
    output_text.delete(1.0, tk.END)
    output_text.insert(tk.END, initial_message)

    def run_commands():
        username = username_entry.get().strip()
        email = email_entry.get().strip()
        repo_link = repo_entry.get().strip()
        commit_message = commit_message_entry.get().strip()
        local_vault_link = local_vault_entry.get().strip()
        onedrive_vault_link = onedrive_vault_entry.get().strip()

        if not all([username, email, repo_link, local_vault_link]):
            output_text.delete(1.0, tk.END)
            output_text.insert(tk.END, "Error: Username, Email, Repository Link, and Local Vault Link are required.\n", "error")
            return

        if onedrive_vault_link and os.path.normpath(local_vault_link) == os.path.normpath(onedrive_vault_link):
            output_text.delete(1.0, tk.END)
            output_text.insert(tk.END, "Error: Local Vault Link and OneDrive Vault Link must be different.\n", "error")
            return

        if not os.path.isdir(local_vault_link):
            output_text.delete(1.0, tk.END)
            output_text.insert(tk.END, f"Error: Local Vault Link directory {local_vault_link} does not exist.\n", "error")
            return
        if onedrive_vault_link and not os.path.isdir(onedrive_vault_link):
            output_text.delete(1.0, tk.END)
            output_text.insert(tk.END, f"Error: OneDrive Vault Link directory {onedrive_vault_link} does not exist.\n", "error")
            return

        save_cached_data({
            "username": username,
            "email": email,
            "repo_link": repo_link,
            "commit_message": commit_message,
            "local_vault_link": local_vault_link,
            "onedrive_vault_link": onedrive_vault_link
        })

        output_text.delete(1.0, tk.END)
        output_text.insert(tk.END, "Processing...\n\n")

        output = ["Processing Local Vault..."]
        output.extend(run_git_commands(local_vault_link, username, email, repo_link, commit_message))

        if onedrive_vault_link:
            output.append("\nProcessing OneDrive Vault...")
            output.extend(run_git_commands(onedrive_vault_link, username, email, repo_link, commit_message))

        output.append("\nAll operations completed.")

        output_text.delete(1.0, tk.END)
        for line in output:
            if line.startswith(("Error", "Failed")):
                output_text.insert(tk.END, line + "\n\n", "error")
            elif line.startswith(("Successfully", "Git operations completed")):
                output_text.insert(tk.END, line + "\n\n", "success")
            else:
                output_text.insert(tk.END, line + "\n\n")

    def clear_cache():
        cache_file = os.path.expanduser("~/.git_config_cache.json")
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
                output_text.delete(1.0, tk.END)
                output_text.insert(tk.END, "Cache cleared.\n", "success")
            except Exception as e:
                output_text.delete(1.0, tk.END)
                output_text.insert(tk.END, f"Error clearing cache: {e}\n", "error")
        else:
            output_text.delete(1.0, tk.END)
            output_text.insert(tk.END, "Cache file does not exist.\n", "error")
        username_entry.delete(0, tk.END)
        email_entry.delete(0, tk.END)
        repo_entry.delete(0, tk.END)
        commit_message_entry.delete(0, tk.END)
        local_vault_entry.delete(0, tk.END)
        onedrive_vault_entry.delete(0, tk.END)

    # Buttons
    button_frame = ttk.Frame(window)
    button_frame.grid(row=2, column=0, pady=10)
    button_frame.option_add("*Font", custom_font)
    ttk.Button(button_frame, text="Run Git Commands", command=run_commands).grid(row=0, column=0, padx=5)
    ttk.Button(button_frame, text="Clear Cache", command=clear_cache).grid(row=0, column=1, padx=5)

    # Configure grid weights
    window.columnconfigure(0, weight=1)
    window.rowconfigure(1, weight=1)
    form_frame.columnconfigure(0, weight=1)
    local_vault_frame.columnconfigure(0, weight=1)
    onedrive_vault_frame.columnconfigure(0, weight=1)

    window.mainloop()

if __name__ == "__main__":
    create_app()
