"""
Central Manager for all Database-related actions for Logos
"""
import secrets
from typing import Dict, Any, Optional

import sqlalchemy.exc
import yaml
from sqlalchemy import Table, MetaData
from sqlalchemy import text

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

    def fetch_llm_key(self, logos_key):
        sql = text("""
                SELECT api_key, providers.name as name, base_url
                FROM providers, model_api_keys, profiles, process
                WHERE process.logos_key = :logos_key
                    and process.profile_id = profiles.id 
                    and profiles.id = model_api_keys.profile_id 
                    and model_api_keys.provider_id = providers.id
            """)

        result = self.session.execute(sql, {
            "logos_key": logos_key
        }).fetchone()
        print(sql)
        if result:
            return {
                "api_key": result.api_key,
                "provider_name": result.name,
                "base_url": result.base_url
            }
        return None

    def __exec_init(self):
        with self.engine.connect() as conn:
            with open("./db/init.sql", "r", encoding="utf-8") as file:
                sql = file.read()
                for statement in sql.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        try:
                            conn.execute(text(stmt))
                        except sqlalchemy.exc.ProgrammingError:
                            pass

            conn.commit()

    def setup(self) -> dict:
        """
        Sets up the initial database. Creates a root-user.
        :return: Initial API-Key
        """
        # Check if database already exists
        self.__exec_init()
        try:
            sql = text("""
                        SELECT *
                        FROM process
                    """)
            if self.session.execute(sql).fetchone() is not None:
                return {"error": "Database already initialized"}
        except sqlalchemy.exc.ProgrammingError:
            pass

        self.create_all()
        # Create user
        user_id = self.insert("users", {"username": "root", "prename": "postgres", "name": "root"})
        # Create process
        api_key = generate_logos_api_key("root")
        _ = self.insert("process", {"logos_key": api_key, "user_id": user_id, "name": "root"})
        return {"api_key": api_key}

    def add_provider(self, logos_key: str, provider_name: str, base_url: str, api_key: str) -> dict:
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}
        pk = self.insert("providers", {"name": provider_name, "base_url": base_url})
        pk_api = self.insert("model_api_keys", {"api_key": api_key, "provider_id": pk})
        return {"result": f"Created Provider. API-ID: {pk_api}"}

    def add_process_connection(self, root_key: str, profile_name: str, process_id: int, api_id: int):
        if not self.__check_authorization(root_key):
            return {"error": "Database changes only allowed for root user."}
        pk = self.insert("profiles", {"name": profile_name})
        sql = text("""
                    UPDATE process
                    SET profile_id = :pk
                    WHERE id = :process_id
                """)
        self.session.execute(sql, {
            "pk": pk,
            "process_id": process_id
        })
        sql = text("""
                    UPDATE model_api_keys
                    SET profile_id = :pk
                    WHERE id = :api_id
                """)
        self.session.execute(sql, {
            "pk": pk,
            "api_id": api_id
        })
        return {"result": f"Created Profile. ID: {pk}"}

    def get_process_id(self, logos_key: str):
        sql = text("""
                    SELECT id
                    FROM process
                    WHERE logos_key = :logos_key
        """)
        exc = self.session.execute(sql, {"logos_key": logos_key}).fetchone()
        if exc is None:
            return {"error": "Key not found"}
        return {"result": f"Process ID: {exc[0]}"}

    def __check_authorization(self, logos_key: str):
        sql = text("""
                                SELECT *
                                FROM process, users
                                WHERE logos_key = :logos_key
                                    and process.user_id = users.id
                                    and users.name = 'root'
                            """)
        return self.session.execute(sql, {"logos_key": logos_key}).fetchone() is not None

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
    """
    DB-Creation Steps:
    1. Setup: Set up database. Creates an entry in "users" with "root" user and a process entry with an initial api key.
    2. Add Provider. Add a provider and a corresponding api-key
    3. Connect logos-user/service with profiles
    """
    pass
