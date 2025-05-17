"""
Central Manager for all Database-related actions for Logos
"""
import json
import os
import secrets
from typing import Dict, Any, Optional, Tuple, Union

import sqlalchemy.exc
import yaml
from sqlalchemy import Table, MetaData
from sqlalchemy import text

from logos.dbmodules import *


def load_postgres_env_vars_from_compose(file_path="./logos/docker-compose.yaml"):
    with open(file_path, "r", encoding="utf-8") as f:
        compose = yaml.safe_load(f)

    env = compose.get("services", {}).get("logos-db", {}).get("environment", {})
    return {
        "user": env.get("POSTGRES_USER"),
        "password": env.get("POSTGRES_PASSWORD"),
        "db": env.get("POSTGRES_DB"),
        "host": env.get("POSTGRES_HOST"),
        "port": 5432    # compose.get("services", {}).get("logos-db", {}).get("ports", ['5432:5432'])[0].split(":")[0]
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

    def fetch_llm_key(self, logos_key: str):
        sql = text("""
                SELECT api_key, 
                    providers.name as name, 
                    base_url, 
                    model_api_keys.id as api_id, 
                    providers.id as provider_id,
                    providers.auth_name as auth_name,
                    providers.auth_format as auth_format
                FROM providers, model_api_keys, profiles, process
                WHERE process.logos_key = :logos_key
                    and process.profile_id = profiles.id 
                    and profiles.id = model_api_keys.profile_id 
                    and model_api_keys.provider_id = providers.id
            """)

        result = self.session.execute(sql, {
            "logos_key": logos_key
        }).fetchone()
        if result:
            return {
                "api_key": result.api_key,
                "provider_name": result.name,
                "base_url": result.base_url,
                "api_id": result.api_id,
                "provider_id": result.provider_id,
                "auth_name": result.auth_name,
                "auth_format": result.auth_format
            }
        return None

    def __exec_init(self):
        with self.engine.connect() as conn:
            with open("./logos/db/init.sql", "r", encoding="utf-8") as file:
                sql = file.read()
                for statement in sql.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        try:
                            conn.execute(text(stmt))
                        except sqlalchemy.exc.ProgrammingError:
                            pass
            conn.commit()

    @staticmethod
    def is_initialized():
        return os.path.exists("./logos/db/.env")

    def setup(self) -> dict:
        """
        Sets up the initial database. Creates a root-user.
        :return: Initial API-Key
        """
        # Check if database already exists
        if os.path.exists("./logos/db/.env"):
            return {"error": "Database already initialized"}
        self.__exec_init()

        self.create_all()
        # Create user
        user_id = self.insert("users", {"username": "root", "prename": "postgres", "name": "root"})
        # Create process
        api_key = generate_logos_api_key("root")
        _ = self.insert("process", {"logos_key": api_key, "user_id": user_id, "name": "root"})
        with open("./logos/db/.env", "w") as file:
            file.write("Setup Completed")
            file.write("\n")
        return {"result": f"Created root user. ID: {user_id}", "api_key": api_key}

    def add_provider(self, logos_key: str, provider_name: str, base_url: str,
                     api_key: str, auth_name: str, auth_format: str) -> Tuple[dict, int]:
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("providers", {"name": provider_name, "base_url": base_url,
                                       "auth_name": auth_name, "auth_format": auth_format})
        pk_api = self.insert("model_api_keys", {"api_key": api_key, "provider_id": pk})
        return {"result": f"Created Provider. API-ID: {pk_api}"}, 200

    def add_profile(self, logos_key: str, profile_name: str, process_id: int):
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("profiles", {"name": profile_name})
        sql = text("""
                    UPDATE process
                    SET profile_id = :pk
                    WHERE id = :process_id
                """)
        self.session.execute(sql, {
            "pk": pk,
            "process_id": int(process_id)
        })
        self.session.commit()
        return {"result": f"Added profile. Profile-ID: {pk}"}, 200

    def add_model(self, logos_key: str, name: str, endpoint: str):
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("models", {"name": name, "endpoint": endpoint})
        return {"result": f"Created Model. ID: {pk}"}, 200

    def add_service(self, logos_key: str, name: str):
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("services", {"name": name})
        api_key = generate_logos_api_key(name)
        ppk = self.insert("process", {"logos_key": api_key, "service_id": pk, "name": name})
        return {"result": f"Created Service. Service-ID: {pk}, Process-ID: {ppk}", "logos-key": {api_key}}, 200

    def get_role(self, logos_key: str):
        sql = text("""
            SELECT *
            FROM process, users
            WHERE logos_key = :logos_key
                and process.user_id = users.id
        """)
        entity = self.session.execute(sql, {"logos_key": logos_key}).fetchone() is not None
        admin = self.__check_authorization(logos_key)
        if admin:
            return {"role": "root"}
        elif entity:
            return {"role": "entity"}
        return {"error": "unknown key"}

    def connect_process_provider(self, logos_key: str, profile_id: int, api_id: int):
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        sql = text("""
                    UPDATE model_api_keys
                    SET profile_id = :profile_id
                    WHERE id = :api_id
                """)
        self.session.execute(sql, {
            "profile_id": int(profile_id),
            "api_id": int(api_id)
        })
        self.session.commit()
        return {"result": f"Added connection to api."}, 200

    def connect_process_model(self, logos_key: str, profile_id: int, model_id: int):
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("profile_model_permissions",
                         {"profile_id": int(profile_id), "model_id": int(model_id)})
        return {"result": f"Connected process to model. ID: {pk}"}, 200

    def connect_service_process(self, logos_key: str, service_id: int, process_name: str):
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        api_key = generate_logos_api_key("root")
        pk = self.insert("process", {"logos_key": api_key, "service_id": int(service_id),
                                     "name": int(process_name)})
        return {"result": f"Connected service. Process-ID: {pk}.", "api-key": api_key}, 200

    def connect_model_provider(self, logos_key: str, model_id: int, provider_id: int):
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("model_provider", {"provider_id": int(provider_id), "model_id": int(model_id)})
        return {"result": f"Connected Model to Provider. ID: {pk}."}, 200

    def connect_model_api(self, logos_key: str, model_id: int, api_id: int):
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        sql = text("""
                    UPDATE models
                    SET api_id = :api_id
                    WHERE id = :model_id
                """)
        self.session.execute(sql, {
            "model_id": int(model_id),
            "api_id": int(api_id)
        })
        self.session.commit()
        return {"result": f"Added api-connection to model."}, 200

    def get_process_id(self, logos_key: str):
        sql = text("""
                    SELECT id
                    FROM process
                    WHERE logos_key = :logos_key
        """)
        exc = self.session.execute(sql, {"logos_key": logos_key}).fetchone()
        if exc is None:
            return {"error": "Key not found"}
        return {"result": f"Process ID: {exc[0]}"}, 200

    def get_api_id(self, logos_key: str, api_key: str):
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        sql = text("""
                    SELECT id
                    FROM model_api_keys
                    WHERE api_key = :api_key
        """)
        exc = self.session.execute(sql, {"api_key": api_key}).fetchone()
        if exc is None:
            return {"error": "Key not found"}
        return {"result": f"API-ID: {exc[0]}"}, 200

    def get_model_from_api(self, logos_key: str, api_id: int) -> Union[int, None]:
        """
        Get model ID from a provided api key.
        """
        sql = text("""
                    SELECT models.id as id
                    FROM process, profiles, profile_model_permissions, models
                    WHERE process.logos_key = :logos_key
                        and process.profile_id = profiles.id
                        and profile_model_permissions.profile_id = profiles.id
                        and profile_model_permissions.model_id = models.id
                        and models.api_id = :api_id
        """)
        result = self.session.execute(sql, {"logos_key": logos_key, "api_id": int(api_id)}).fetchone()
        if result is None:
            return None
        return result.id

    def get_model_from_provider(self, logos_key: str, provider_id: int) -> Union[int, None]:
        """
        Get model ID from a provided provider ID.
        """
        sql = text("""
                    SELECT models.id as id
                    FROM process, profiles, model_api_keys, models, providers, model_provider
                    WHERE process.logos_key = :logos_key
                        and process.profile_id = profiles.id
                        and model_api_keys.profile_id = profiles.id
                        and model_api_keys.provider_id = providers.id
                        and providers.id = :provider_id
                        and model_provider.provider_id = providers.id
                        and model_provider.model_id = models.id
        """)
        result = self.session.execute(sql, {"logos_key": logos_key, "provider_id": int(provider_id)}).fetchone()
        if result is None:
            return None
        return result.id

    def get_model(self, model_id: int):
        sql = text("""
            SELECT *
            FROM models
            WHERE id = :model_id
        """)
        result = self.session.execute(sql, {"model_id": int(model_id)}).fetchone()
        return {"name": result.name, "endpoint": result.endpoint}

    def export(self, logos_key: str):
        if not self.__check_authorization(logos_key):
            return {"error": "Database exports only allowed for root user."}, 403

        data = {}
        for table in Base.metadata.sorted_tables:
            rows = self.session.execute(table.select()).fetchall()
            data[table.name] = [dict(row._mapping) for row in rows]

        return {"result": data}, 200

    def import_from_json(self, logos_key: str, json_data: dict):
        if not self.__check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        # Store table names to prevent silent errors on foreign key insertions
        table_names = [
            "users",
            "services",
            "profiles",
            "process",
            "providers",
            "model_api_keys",
            "models",
            "model_provider",
            "profile_model_permissions",
            "policies"
        ]
        for table_name in table_names:
            if table_name not in json_data:
                return {"error": f"Missing table in json: {table_name}"}, 500
            rows = json_data[table_name]
            table = Base.metadata.tables.get(table_name)
            if table is not None and rows:
                self.session.execute(table.delete())
                self.session.execute(table.insert(), rows)
        self.session.commit()
        return {"result": f"Imported data"}, 200

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
        conf = load_postgres_env_vars_from_compose()    # {conf['port']}
        db_url = f"postgresql://{conf['user']}:{conf['password']}@logos-db:5432/{conf['db']}"
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
    Logos Installation Steps:
    1. Set up database. Creates an entry in "users" with "root" user and a process entry with an initial api key.
        =>  Call "/logosdb/setup"
        =>  In the response you get the logos-API-key for the root user. This key is used to setup the database
            in the following steps.
    2. Add Provider. Add a new provider, the corresponding base url, the API key and authentication syntax.
        "auth_name" is the name used in the header for authorization (e.g. "api-key" for azure), 
        "auth_format" is used in the header to format the authentication (e.g. "Bearer {}" for OpenAI)
    3. Add models. This action is optional if you just want to use Logos as a proxy. Logos will then just take 
        the header info of your requests and forward it to your specified provider. Otherwise, define
        now what models you want to have access to over Logos. Therefore define the model endpoint 
        (without the base url) and the name of the model.
    4. Add profiles. Profiles are an intermediate step between users and services communicating with Logos and
        its underlying database structure. Users and services, in the follows just abbreviated as "processes"
        can therefore act more dynamically with providers and models. A profile itself has a name and a process
        id associated with it. A process can so have many profiles. Each profile can then be configured to have access
        to certain models or providers, as explained later. If you don't know the ID of a process, you can find it
        out via the get_process_id-Endpoint by supplying a corresponding key.
    5. Connect Profiles with Providers. Now you define which profiles can interact with which providers. Therefore
        call the connect_process_provider-Endpoint with the profile ID and the corresponding api-ID. This api-ID
        is obtained by calling the get_api_id-Endpoint for a given api-key. 
    If you just want to use Logos as a proxy, you're done here with the basics. Else proceed with the following steps:
    6. Connect Profiles with Models. Now you define which Profiles can interact with which Models. Therefore
        call the connect_process_model-Endpoint analogous as in step 5.
    7. Connect Models with Providers. Now you define which Models are connected to which Providers. Therefore
        call the connect_model_provider-Endpoint analogous as in step 6. 
    8. Connect api-key and model. If a model requires its own api-key under a certain provider, you can now
        connect a stored api-key to that model. Otherwise this is not necessary. Therefore call the 
        connect_model_api-Endpoint as in step 7.
    Congratulations! You have successfully set up Logos and can now call Logos to obtain results from your
    stored models. Keep in mind that you now provide the logos-key in the request header, not the data.
    """
    pass
