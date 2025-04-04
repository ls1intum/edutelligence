"""
Module maintaining and checking config utilities for logos. This includes config files for API-keys and available LLMs
as well as policies.
"""
import yaml
import bcrypt
from pathlib import Path
from typing import Optional


class KeyManager:
    def __init__(self, yaml_path):
        self.yaml_path = Path(yaml_path)
        self.users = {}
        self.load_keys()

    def load_keys(self):
        if not self.yaml_path.exists():
            raise FileNotFoundError(f"Key file not found: {self.yaml_path}")
        with open(self.yaml_path, "r") as file:
            data = yaml.safe_load(file)
            self.users = {user['name']: user['keys'] for user in data.get('users', [])}

    def get_key(self, user: str, model: str, pwd: Optional[str] = None) -> Optional[str]:
        """
        Returns the active key for a given user, password and model.
        :param user: The user
        :param pwd: The passwort of the given user
        :param model: The LLM requested
        :return: The API-Key for the given user and password or None if the user or model could not be found.
        :raises PermissionError: If the password is wrong or missing
        """
        user_keys = self.users.get(user)
        if not user_keys:
            return None
        for key_info in user_keys:
            if key_info['model'] == model:
                if key_info.get('private', True):
                    if pwd is None:
                        raise PermissionError("The requested model is private. Please provide a password")
                    if not bcrypt.checkpw(pwd, key_info["pwd"]):
                        raise PermissionError("Wrong username or password")
                return key_info['key']
        return None
