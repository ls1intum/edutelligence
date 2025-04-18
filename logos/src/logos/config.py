"""
Module maintaining and checking config utilities for logos. This includes config files for API-keys and available LLMs
as well as policies.
"""
import os

import yaml
import secrets


class KeyManager:
    USER_GROUPS = {"admin", "user"}

    def __init__(self, users_file="users.yml", profiles_file="profiles.yml"):
        self.users_file = users_file
        self.profiles_file = profiles_file

        self.users = self._load_yaml(self.users_file, root_key="users")
        self.profiles = self._load_yaml(self.profiles_file, root_key="profiles")

    def _load_yaml(self, path, root_key):
        if os.path.exists(path):
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            return data.get(root_key, {})
        return {}

    def _save_yaml(self, path, root_key, data):
        with open(path, "w") as f:
            yaml.safe_dump({root_key: data}, f)

    def save(self):
        self._save_yaml(self.users_file, "users", self.users)
        self._save_yaml(self.profiles_file, "profiles", self.profiles)

    def generate_logos_api_key(self, user: str) -> str:
        """
        Generates a logos API key for a given user.
        The exact procedure has TBD, for now every key starts with "lg", followed by
        "-" followed by the username followed by a "-".
        :param user:
        :return: A logos API-key for a given user.
        """
        return "lg-" + user + "-" + secrets.token_urlsafe(96)

    def get_profile(self, logos_api_key: str) -> str | None:
        for _, data in self.users.items():
            if data["logos_api_key"] == logos_api_key:
                return data["profile"]
        return None

    def get_llm_key(self, logos_api_key: str, provider: str) -> str:
        profile_name = self.get_profile(logos_api_key)
        if not profile_name:
            raise ValueError("No corresponding profile found for provided key")
        profile = self.profiles.get(profile_name, {})
        return profile.get("llm_keys", {}).get(provider, {}).get("api_key")

    def get_rights(self, logos_api_key: str) -> str | None:
        profile_name = self.get_profile(logos_api_key)
        profile = self.profiles.get(profile_name, {})
        if not profile or profile["logos_rights"] not in self.USER_GROUPS:
            raise PermissionError(f"Insufficient Permissions for provided key")
        return profile["logos_rights"]

    def add_llm_key(self, logos_api_key: str, llm_key: str, provider: str) -> None:
        profile_name = self.get_profile(logos_api_key)
        if profile_name is None:
            raise ValueError("Profile does not exist")
        self.profiles[profile_name]["llm_keys"][provider] = {"api_key": llm_key}
        self.save()

    def remove_llm_key(self, logos_api_key: str, provider: str) -> None:
        profile_name = self.get_profile(logos_api_key)
        if profile_name is None:
            raise ValueError("Profile does not exist")
        del self.profiles[profile_name]["llm_keys"][provider]
        self.save()

    def add_user(self, logos_api_key: str, username: str, profile: str, create_profile_if_missing=True) -> str:
        if self.get_rights(logos_api_key) != "admin":
            raise PermissionError(f"Insufficient permissions for provided key")
        if username in self.users:
            raise ValueError(f"User '{username}' already exists.")
        api_key = self.generate_logos_api_key(username)
        self.users[username] = {
            "logos_api_key": api_key,
            "profile": profile
        }

        if create_profile_if_missing and profile not in self.profiles:
            self.profiles[profile] = {
                "llm_keys": {},
                "logos_rights": "user"
            }

        self.save()
        return api_key

    def delete_user(self, logos_api_key: str, username: str, remove_profile=False):
        if self.get_rights(logos_api_key) != "admin":
            raise PermissionError(f"Insufficient permissions for {logos_api_key}")
        user = self.users.pop(username, None)
        if user is None:
            raise ValueError(f"User '{username}' not found.")

        if remove_profile:
            profile = user["profile"]
            self.profiles.pop(profile, None)

        self.save()
