import requests
import os
import time
import json
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
import apprise

# Load custom group and project names from YAML configuration
with open('names_config.yaml', 'r') as names_file:
    custom_names = yaml.safe_load(names_file)

# Discord webhook URL
discord_url = os.getenv('DISCORD_WEBHOOK_URL')

# Number of retries and delay between retries
RETRY_COUNT = 3
RETRY_DELAY = 5

# Load message type configuration
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

def check_rate_limit():
    try:
        response = requests.get("https://api.github.com/rate_limit")
        response.raise_for_status()
        rate_limit = response.json()
        remaining = rate_limit['rate']['remaining']
        reset_time = rate_limit['rate']['reset']

        if remaining == 0:
            sleep_time = reset_time - int(time.time())
            print(f"Rate limit exceeded. Sleeping for {sleep_time} seconds.")
            time.sleep(sleep_time)
    except requests.exceptions.RequestException as e:
        print(f"Error checking rate limit: {e}")
        time.sleep(RETRY_DELAY)

def check_account_status(username):
    for attempt in range(RETRY_COUNT):
        try:
            response = requests.get(f"https://api.github.com/users/{username}")
            if response.status_code == 404:
                return username, "Suspended"
            response.raise_for_status()
            return username, "Active"
        except requests.exceptions.HTTPError as http_err:
            if response.status_code == 403:
                print(f"HTTP 403 Forbidden: Rate limit or access forbidden for {username}")
                check_rate_limit()
            elif response.status_code == 404:
                print(f"HTTP 404 Not Found: User {username} does not exist or is suspended")
            elif response.status_code == 500:
                print(f"HTTP 500 Internal Server Error: Server issue while checking {username}")
            else:
                print(f"HTTP error occurred for {username}: {http_err}")
            if attempt < RETRY_COUNT - 1:
                print(f"Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                return username, "Error"
        except requests.exceptions.RequestException as req_err:
            print(f"Request exception occurred for {username}: {req_err}")
            if attempt < RETRY_COUNT - 1:
                print(f"Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                return username, "Error"

def send_discord_message(message):
    try:
        apprise_instance = apprise.Apprise()
        apprise_instance.add(discord_url)
        apprise_instance.notify(body=message, title='GitHub Account Status')
    except Exception as e:
        print(f"Failed to send message to Discord: {e}")

def main():
    suspended_accounts = {}

    with ThreadPoolExecutor() as executor:
        futures = []
        for group, group_details in custom_names.items():
            group_name = group_details["name"]
            for project, project_details in group_details["projects"].items():
                project_name = project_details["name"]
                for username in project_details["Github Username"]:
                    futures.append(executor.submit(check_account_status, username))

        results = {}
        for future in as_completed(futures):
            username, status = future.result()
            results[username] = status

        for group, group_details in custom_names.items():
            group_name = group_details["name"]
            for project, project_details in group_details["projects"].items():
                project_name = project_details["name"]
                for username in project_details["Github Username"]:
                    if results[username] == "Suspended":
                        if group_name not in suspended_accounts:
                            suspended_accounts[group_name] = {}
                        if project_name not in suspended_accounts[group_name]:
                            suspended_accounts[group_name][project_name] = []
                        suspended_accounts[group_name][project_name].append(username)

    if suspended_accounts and config['message_types'].get('AlertWithDetails', False):
        message_lines = ["🚨 Suspended Accounts Alert! 🚨"]
        for group_name, projects in suspended_accounts.items():
            message_lines.append(f"\n{group_name}:")
            for project_name, usernames in projects.items():
                message_lines.append(f"- {project_name}: {', '.join(usernames)}")
        message = "\n".join(message_lines)
        send_discord_message(message)

if __name__ == "__main__":
    main()
