"""
Central Manager for all Database-related actions for Logos
"""
import secrets
from typing import Dict, Any, Optional

import yaml
from sqlalchemy import Table, MetaData

from logos.dbmodules import *


def load_postgres_env_vars_from_compose(file_path="docker-compose.yaml"):
    with open(file_path, "r", encoding="utf-8") as f:
        compose = yaml.safe_load(f)

    env = compose.get("services", {}).get("db", {}).get("environment", {})
    return {
        "user": env.get("POSTGRES_USER"),
        "password": env.get("POSTGRES_PASSWORD"),
        "db": env.get("POSTGRES_DB"),
        "host": env.get("POSTGRES_HOST"),
        "port": compose.get("services", {}).get("db", {}).get("ports", 5432)[0].split(":")[0]
    }


def generate_logos_api_key(process: str) -> str:
    """
    Generates a logos API key for a given process.
    Every key starts with "lg", followed by
    "-" followed by the process name followed by a "-".
    :return: A logos API-key for a given user.
    """
    return "lg-" + process + "-" + secrets.token_urlsafe(96)


class DBManager:
    def __init__(self):
        pass

    def create_all(self):
        Base.metadata.create_all(self.engine)

    def drop_all(self):
        Base.metadata.drop_all(self.engine)

    def add_user(self, username, prename, name):
        user = User(username=username, prename=prename, name=name)
        self.session.add(user)
        self.session.commit()
        return user

    def get_users(self):
        return self.session.query(User).all()

    def close(self):
        self.session.close()

    def insert(self, table: str, data: Dict[str, Any]) -> int:
        table = Table(table, self.metadata, autoload_with=self.engine)
        insert_stmt = table.insert().values(**data)
        result = self.session.execute(insert_stmt)
        self.session.commit()
        return result.inserted_primary_key[0]

    def update(self, table_name: str, record_id: int, data: Dict[str, Any]) -> None:
        table = Table(table_name, self.metadata, autoload_with=self.engine)
        update_stmt = table.update().where(table.c.id == record_id).values(**data)
        self.session.execute(update_stmt)
        self.session.commit()

    def delete(self, table_name: str, record_id: int) -> None:
        table = Table(table_name, self.metadata, autoload_with=self.engine)
        delete_stmt = table.delete().where(table.c.id == record_id)
        self.session.execute(delete_stmt)
        self.session.commit()

    def delete_user(self, username: str) -> None:
        table = Table("users", self.metadata, autoload_with=self.engine)
        delete_stmt = table.delete().where(table.c.username == username)
        self.session.execute(delete_stmt)
        self.session.commit()

    def fetch_by_id(self, table_name: str, record_id: int) -> Optional[Dict[str, Any]]:
        table = Table(table_name, self.metadata, autoload_with=self.engine)
        result = self.session.execute(table.select().where(table.c.id == record_id)).mappings().first()
        return dict(result) if result else None

    def fetch_all(self, table_name: str) -> list[Dict[str, Any]]:
        table = Table(table_name, self.metadata, autoload_with=self.engine)
        result = self.session.execute(table.select()).mappings().all()
        return [dict(row) for row in result]

    def fetch_llm_key(self, provider, logos_key):
        process_table = Table("process", self.metadata, autoload_with=self.engine)
        process_entry = self.session.execute(
            process_table.select().where(process_table.c.logos_key == logos_key)
        ).mappings().first()

        if not process_entry:
            return None
        profile_id = process_entry["profile_id"]

        profile = Table("process", self.metadata, autoload_with=self.engine)
        profile_entry = self.session.execute(
            process_table.select().where(profile.c.id == profile_id)
        ).mappings().first()
        profile_id = profile_entry["id"]

        provider_table = Table("process", self.metadata, autoload_with=self.engine)
        profile_entry = self.session.execute(
            process_table.select().where(provider_table.c.id == profile_id)
        ).mappings().first()
        profile_id = profile_entry["id"]

        # 2. Finde API-Key in model_api_keys mit passender profile_id und provider
        model_api_keys = Table("model_api_keys", self.metadata, autoload_with=self.engine)
        result = self.session.execute(
            model_api_keys.select().where(
                (model_api_keys.c.profile_id == profile_id) &
                (model_api_keys.c.provider == provider)
            )
        ).mappings().first()

        if result:
            return result["api_key"]
        return None

    def setup(self) -> str:
        """
        Sets up the initial database. Creates a root-user.
        :return: Initial API-Key
        """
        self.create_all()
        # Create user
        user_id = self.insert("users", {"username": "root", "prename": "postgres", "name": "root"})
        # Create profile
        profile_id = self.insert("profiles", {"name": "root"})
        # Create process
        api_key = generate_logos_api_key("root")
        _ = self.insert("process", {"logos_key": api_key, "user_id": user_id, "profile_id": profile_id, "name": "root"})
        print(f"Successfully created database. API-Key: {api_key}")
        # Insert data for supported providers
        self.insert("providers", {"name": "openai", "base_url": "https://api.openai.com/v1"})
        self.insert("providers", {"name": "azure", "base_url": "https://ase-se01.openai.azure.com/openai/deployments"})
        return api_key

    def __enter__(self):
        conf = load_postgres_env_vars_from_compose()
        db_url = f"postgresql://{conf['user']}:{conf['password']}@{conf['host']}:{conf['port']}/{conf['db']}"
        self.engine = create_engine(db_url)
        self.metadata = MetaData()
        self.metadata.reflect(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.session.close()


if __name__ == "__main__":
    with DBManager() as man:
        man.setup()
