import requests
import getpass
import sys
from typing import List, Dict, Any, Optional

from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import checkboxlist_dialog, message_dialog, input_dialog
from prompt_toolkit.styles import Style

# --- Configuration ---
API_BASE_URL = "https://api.modrinth.com/v2"

# --- TUI Styling ---
style = Style.from_dict(
    {
        "dialog": "bg:#333333",
        "dialog.body": "bg:#444444 #ffffff",
        "dialog shadow": "bg:#222222",
        "dialog.border": "bg:#333333 #888888",
        "button": "bg:#005588 #ffffff",
        "button.arrow": "#000000",
        "checkbox": "#dddddd",
        "checkbox-selected": "bg:#00aa00",
        "checkbox-checked": "#ffff00",
        "dialog.body label": "#ffffff",
    }
)

# --- API Helper Functions ---


def get_authenticated_user(token: str) -> Optional[Dict[str, Any]]:
    """Validates token and fetches the user associated with it."""
    headers = {"Authorization": token}
    try:
        response = requests.get(f"{API_BASE_URL}/user", headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        error_message = f"Authentication failed. Please check your token. Details: {e}"
        if e.response is not None:
            error_message += f"\nResponse: {e.response.text}"
        message_dialog(title="Error", text=error_message, style=style).run()
        return None


def get_user_projects(user_id: str, token: str) -> List[Dict[str, Any]]:
    """Fetches all projects for a given user ID."""
    headers = {"Authorization": token}
    try:
        response = requests.get(f"{API_BASE_URL}/user/{user_id}/projects", headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        message_dialog(title="Error", text=f"Failed to fetch projects: {e}", style=style).run()
        return []


def get_latest_project_version(project_id: str, token: str) -> Optional[Dict[str, Any]]:
    """Fetches the list of versions for a project and returns the latest one."""
    headers = {"Authorization": token}
    try:
        response = requests.get(f"{API_BASE_URL}/project/{project_id}/version", headers=headers)
        response.raise_for_status()
        versions = response.json()
        if not versions:
            return None
        return versions[0]  # The API returns versions sorted by creation date descending
    except requests.RequestException:
        # Errors will be handled per-project in the main loop
        return None


def update_version_compatibility(version_id: str, game_version: str, token: str) -> bool:
    """Adds a game version to a version's compatibility list."""
    headers = {"Authorization": token, "Content-Type": "application/json"}
    # First, get the current game versions to append the new one
    try:
        get_response = requests.get(f"{API_BASE_URL}/version/{version_id}", headers=headers)
        get_response.raise_for_status()
        current_version_data = get_response.json()

        current_game_versions = current_version_data.get("game_versions", [])
        if game_version in current_game_versions:
            print(f"  - Game version '{game_version}' already exists for this release. Skipping.")
            return True  # Already compatible

        new_game_versions = current_game_versions + [game_version]

        payload = {"game_versions": new_game_versions}

        patch_response = requests.patch(f"{API_BASE_URL}/version/{version_id}", json=payload, headers=headers)
        patch_response.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"  - Failed to update version {version_id}: {e}")
        if e.response is not None:
            print(f"  - Response body: {e.response.text}")
        return False


# --- Main Application Logic ---


def main():
    """Main function to run the TUI application."""
    print("Modrinth Project Updater")
    print("========================")

    # 1. Get Authentication Token
    try:
        token = getpass.getpass("Please enter your Modrinth API token: ")
        if not token:
            print("\nToken cannot be empty. Exiting.")
            sys.exit(1)
    except (EOFError, KeyboardInterrupt):
        print("\nOperation cancelled. Exiting.")
        sys.exit(0)

    # 2. Authenticate and get user info
    user = get_authenticated_user(token)
    if not user:
        sys.exit(1)

    user_id = user["id"]
    username = user["username"]
    print(f"\nSuccessfully authenticated as user: {username} ({user_id})")

    # 3. Fetch user's projects
    print("Fetching your projects...")
    projects = get_user_projects(user_id, token)
    if not projects:
        message_dialog(title="No Projects Found", text="Could not find any projects for your account.", style=style).run()
        sys.exit(0)

    print(f"Found {len(projects)} projects.")

    # 4. Project Selection TUI
    project_choices = [(p["slug"], f"{p['title']} (ID: {p['slug']})") for p in projects]

    try:
        selected_projects_slugs = checkboxlist_dialog(title="Select Projects to Update", text="Use arrow keys to move, spacebar to select/deselect, and enter to confirm.", values=project_choices, style=style).run()
    except (EOFError, KeyboardInterrupt):
        print("\nOperation cancelled. Exiting.")
        sys.exit(0)

    if not selected_projects_slugs:
        print("No projects selected. Exiting.")
        sys.exit(0)

    # 5. Get Target Game Version
    try:
        game_version = input_dialog(title="Game Version", text="Enter the game version to mark as compatible (e.g., '1.21', 'fabric-1.20.4'):", style=style).run()
    except (EOFError, KeyboardInterrupt):
        print("\nOperation cancelled. Exiting.")
        sys.exit(0)

    if not game_version:
        print("No game version entered. Exiting.")
        sys.exit(0)

    # 6. Process selected projects
    print(f"\nUpdating {len(selected_projects_slugs)} projects to be compatible with '{game_version}'...")

    success_count = 0
    fail_count = 0

    for slug in selected_projects_slugs:
        project_title = next((p["title"] for p in projects if p["slug"] == slug), slug)
        print(f"\nProcessing '{project_title}':")

        latest_version = get_latest_project_version(slug, token)

        if not latest_version:
            print("  - No releases found for this project. Skipping.")
            fail_count += 1
            continue

        version_id = latest_version["id"]
        version_number = latest_version["version_number"]
        print(f"  - Found latest release: '{version_number}' (ID: {version_id})")

        if update_version_compatibility(version_id, game_version, token):
            print(f"  - Successfully marked '{version_number}' as compatible with '{game_version}'.")
            success_count += 1
        else:
            print(f"  - An error occurred while updating '{version_number}'.")
            fail_count += 1

    # 7. Final Report
    summary_text = f"Update process finished.\n\n" f"Successfully updated: {success_count}\n" f"Failed or skipped: {fail_count}"
    message_dialog(title="Update Complete", text=summary_text, style=style).run()


if __name__ == "__main__":
    main()
