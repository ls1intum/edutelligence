"""
Central Manager for all Database-related actions for Logos
"""
import datetime
import os
import secrets
from typing import Dict, Any, Optional, Tuple, Union
from dateutil.parser import isoparse

import sqlalchemy.exc
import yaml
import json
import logging
from sqlalchemy import Table, MetaData, create_engine
from sqlalchemy import text, func
from sqlalchemy.orm import sessionmaker

from logos.classification.model_handler import ModelHandler
from logos.dbutils.dbmodules import *


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


# noinspection PyUnresolvedReferences
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

    def upsert_request_event(self, request_id: str, **fields: Any) -> None:
        """
        Insert or update a request_events row identified by request_id.

        Only provided fields are updated; omitted fields remain unchanged.
        """
        allowed_fields = {
            "model_id",
            "provider_id",
            "initial_priority",
            "priority_when_scheduled",
            "queue_depth_at_enqueue",
            "queue_depth_at_schedule",
            "timeout_s",
            "enqueue_ts",
            "scheduled_ts",
            "request_complete_ts",
            "available_vram_mb",
            "azure_rate_remaining_requests",
            "azure_rate_remaining_tokens",
            "cold_start",
            "result_status",
            "error_message",
        }

        payload = {k: v for k, v in fields.items() if k in allowed_fields and v is not None}
        columns = ["request_id"] + list(payload.keys())
        params = {"request_id": request_id, **payload}

        if payload:
            assignments = ", ".join(f"{col}=EXCLUDED.{col}" for col in payload.keys())
            placeholders = ", ".join(f":{col}" for col in columns)
            sql = text(
                f"INSERT INTO request_events ({', '.join(columns)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT (request_id) DO UPDATE SET {assignments}"
            )
        else:
            sql = text(
                "INSERT INTO request_events (request_id) VALUES (:request_id) "
                "ON CONFLICT (request_id) DO NOTHING"
            )

        self.session.execute(sql, params)
        self.session.commit()

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
                    providers.auth_format as auth_format,
                    process.id as process_id
                FROM providers, model_api_keys, profiles, process
                WHERE process.logos_key = :logos_key
                    and profiles.process_id = process.id 
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
                "auth_format": result.auth_format,
                "process_id": result.process_id
            }
        return None

    def __exec_init(self):
        with open("./logos/db/init.sql", "r", encoding="utf-8") as file:
            sql = file.read()
            for statement in sql.split(";"):
                stmt = statement.strip()
                if stmt:
                    try:
                        self.session.execute(text(stmt))
                    except sqlalchemy.exc.ProgrammingError:
                        pass

        self.session.commit()

    @staticmethod
    def is_initialized():
        return os.path.exists("./logos/db/.env")

    def is_root_initialized(self):
        if sqlalchemy.inspect(self.engine).has_table("users"):
            sql = text("""
                       SELECT logos_key
                       FROM process
                       WHERE name = 'root'
                       """)
            exc = self.session.execute(sql).fetchone()
            if exc is not None:
                with open("./logos/db/.env", "w") as file:
                    file.write("Setup Completed")
                    file.write("\n")
                return True
        return False

    def setup(self) -> dict:
        """
        Sets up the initial database. Creates a root-user.
        :return: Initial API-Key
        """
        # Check if database already exists
        logging.info(".env exists?", os.path.exists("./logos/db/.env"))
        if os.path.exists("./logos/db/.env"):
            return {"error": "Database already initialized"}
        logging.info("Is root initialized?", self.is_root_initialized())
        if self.is_root_initialized():
            return {"error": f"Database already initialized"}
        logging.info("Setting up DB")
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
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("providers", {"name": provider_name, "base_url": base_url,
                                       "auth_name": auth_name, "auth_format": auth_format})
        pk_api = self.insert("model_api_keys", {"api_key": api_key, "provider_id": pk})
        return {"result": f"Created Provider.", "provider-id": pk, "api-id": pk_api}, 200

    def add_profile(self, logos_key: str, profile_name: str, process_id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("profiles", {"name": profile_name, "process_id": process_id})
        return {"result": f"Added profile", "profile-id": pk}, 200

    def add_model(self, logos_key: str, name: str, endpoint: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("models", {"name": name, "endpoint": endpoint})
        return {"result": f"Created Model", "model_id": pk}, 200

    def add_full_model(self, logos_key: str, name: str, endpoint: str, api_id: int = None,
                       weight_privacy: str = "LOCAL", worse_accuracy: int = None, worse_quality: int = None, worse_latency: int = None, worse_cost: int = None, tags: str = "", parallel: int = 1,
                       description: str = ""):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("models", {"name": name, "endpoint": endpoint, "api_id": api_id, "weight_privacy": weight_privacy, "tags": tags, "parallel": parallel, "description": description})
        return self.rebalance_added_model(pk, worse_accuracy, worse_quality, worse_latency, worse_cost)

    def update_model_weights(self, logos_key: str, id: int, category: str, value: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        if category not in {"latency", "accuracy", "quality", "cost", "privacy"}:
            return {"error": f"Invalid category '{category}'"}, 500
        return self.rebalance_updated_model(id, category, value)

    def delete_model(self, logos_key: str, id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        return self.rebalance_deleted_model(id)

    def rebuild_model_weights(self, accuracy: ModelHandler, quality: ModelHandler, latency: ModelHandler, cost: ModelHandler, privacy_data: list):
        models = dict()
        for model in accuracy.get_models():
            if model[1] not in models:
                models[model[1]] = {"privacy": "", "accuracy": model[0], "quality": -1, "latency": -1, "cost": -1}
            else:
                models[model[1]]["accuracy"] = model[0]
        for model in quality.get_models():
            if model[1] not in models:
                models[model[1]] = {"privacy": "", "accuracy": -1, "quality": model[0], "latency": -1, "cost": -1}
            else:
                models[model[1]]["quality"] = model[0]
        for model in latency.get_models():
            if model[1] not in models:
                models[model[1]] = {"privacy": "", "accuracy": -1, "quality": -1, "latency": model[0], "cost": -1}
            else:
                models[model[1]]["latency"] = model[0]
        for model in cost.get_models():
            if model[1] not in models:
                models[model[1]] = {"privacy": "", "accuracy": -1, "quality": -1, "latency": -1, "cost": model[0]}
            else:
                models[model[1]]["cost"] = model[0]
        for model in privacy_data:
            if model[1] not in models:
                models[model[1]] = {"privacy": model[0], "accuracy": -1, "quality": -1, "latency": -1, "cost": -1}
            else:
                models[model[1]]["privacy"] = model[0]
        for model in models:
            self.update("models", model,
                        {"weight_privacy": models[model]["privacy"], "weight_accuracy": models[model]["accuracy"],
                         "weight_quality": models[model]["quality"], "weight_latency": models[model]["latency"],
                         "weight_cost": models[model]["cost"]})

    def rebalance_updated_model(self, updated_model_id: int, category: str, feedback: Union[str, int]):
        data = self.get_all_models_data()
        accuracy_data = list()
        quality_data = list()
        latency_data = list()
        cost_data = list()
        privacy_data = list()
        for model in data:
            mid, p, l, a, c, q = model[0], model[4], model[5], model[6], model[7], model[8]
            if mid == updated_model_id and category == "privacy":
                privacy_data.append((feedback, mid))
            else:
                privacy_data.append((p, mid))
            accuracy_data.append((a, mid))
            quality_data.append((q, mid))
            latency_data.append((l, mid))
            cost_data.append((c, mid))
        accuracy_data = list(sorted(accuracy_data, key=lambda x: x[0]))
        quality_data = list(sorted(quality_data, key=lambda x: x[0]))
        latency_data = list(sorted(latency_data, key=lambda x: x[0]))
        cost_data = list(sorted(cost_data, key=lambda x: x[0]))
        privacy_data = list(sorted(privacy_data, key=lambda x: x[0]))
        accuracy = ModelHandler(accuracy_data)
        quality = ModelHandler(quality_data)
        latency = ModelHandler(latency_data)
        cost = ModelHandler(cost_data)
        if category == "accuracy":
            accuracy.give_feedback(updated_model_id, feedback)
        elif category == "quality":
            quality.give_feedback(updated_model_id, feedback)
        elif category == "latency":
            latency.give_feedback(updated_model_id, feedback)
        elif category == "cost":
            cost.give_feedback(updated_model_id, feedback)
        logging.debug(f"Accuracy-Models: {accuracy.get_models()}")
        logging.debug(f"Quality-Models: {quality.get_models()}")
        logging.debug(f"Latency-Models: {latency.get_models()}")
        logging.debug(f"Cost-Models: {cost.get_models()}")
        logging.debug(f"Privacy-Models: {privacy_data}")
        # Collect rebalanced model weights
        self.rebuild_model_weights(accuracy, quality, latency, cost, privacy_data)
        return {"result": f"Updated Model"}, 200

    def rebalance_deleted_model(self, deleted_model_id: int):
        data = self.get_all_models_data()
        accuracy_data = list()
        quality_data = list()
        latency_data = list()
        cost_data = list()
        privacy_data = list()
        for model in data:
            mid, p, l, a, c, q = model[0], model[4], model[5], model[6], model[7], model[8]
            if mid != deleted_model_id:
                privacy_data.append((p, mid))
            accuracy_data.append((a, mid))
            quality_data.append((q, mid))
            latency_data.append((l, mid))
            cost_data.append((c, mid))
        accuracy_data = list(sorted(accuracy_data, key=lambda x: x[0]))
        quality_data = list(sorted(quality_data, key=lambda x: x[0]))
        latency_data = list(sorted(latency_data, key=lambda x: x[0]))
        cost_data = list(sorted(cost_data, key=lambda x: x[0]))
        privacy_data = list(sorted(privacy_data, key=lambda x: x[0]))
        accuracy = ModelHandler(accuracy_data)
        accuracy.remove_model(deleted_model_id)
        quality = ModelHandler(quality_data)
        quality.remove_model(deleted_model_id)
        latency = ModelHandler(latency_data)
        latency.remove_model(deleted_model_id)
        cost = ModelHandler(cost_data)
        cost.remove_model(deleted_model_id)
        logging.debug(f"Accuracy-Models: {accuracy.get_models()}")
        logging.debug(f"Quality-Models: {quality.get_models()}")
        logging.debug(f"Latency-Models: {latency.get_models()}")
        logging.debug(f"Cost-Models: {cost.get_models()}")
        logging.debug(f"Privacy-Models: {privacy_data}")
        # Collect rebalanced model weights
        self.rebuild_model_weights(accuracy, quality, latency, cost, privacy_data)
        self.delete("models", deleted_model_id)
        return {"result": f"Deleted Model"}, 200

    def rebalance_added_model(self, new_model_id: int, worse_accuracy: int, worse_quality: int, worse_latency: int, worse_cost: int):
        data = self.get_all_models_data()
        accuracy_data = list()
        quality_data = list()
        latency_data = list()
        cost_data = list()
        privacy_data = list()
        for model in data:
            mid, p, l, a, c, q = model[0], model[4], model[5], model[6], model[7], model[8]
            # Add privacy data (we don't add it later as it's not handled via the model handler)
            privacy_data.append((p, mid))
            if mid == new_model_id:
                if p not in {'LOCAL', 'CLOUD_IN_EU_BY_US_PROVIDER', 'CLOUD_NOT_IN_EU_BY_US_PROVIDER', 'CLOUD_IN_EU_BY_EU_PROVIDER'}:
                    return {"error": f"Could not add model: Unknown Privacy Level"}, 500
                continue
            accuracy_data.append((a, mid))
            quality_data.append((q, mid))
            latency_data.append((l, mid))
            cost_data.append((c, mid))
        accuracy_data = list(sorted(accuracy_data, key=lambda x: x[0]))
        quality_data = list(sorted(quality_data, key=lambda x: x[0]))
        latency_data = list(sorted(latency_data, key=lambda x: x[0]))
        cost_data = list(sorted(cost_data, key=lambda x: x[0]))
        privacy_data = list(sorted(privacy_data, key=lambda x: x[0]))
        accuracy = ModelHandler(accuracy_data)
        accuracy.add_model(worse_accuracy, new_model_id)
        quality = ModelHandler(quality_data)
        quality.add_model(worse_quality, new_model_id)
        latency = ModelHandler(latency_data)
        latency.add_model(worse_latency, new_model_id)
        cost = ModelHandler(cost_data)
        cost.add_model(worse_cost, new_model_id)
        logging.debug(f"Accuracy-Models: {accuracy.get_models()}")
        logging.debug(f"Quality-Models: {quality.get_models()}")
        logging.debug(f"Latency-Models: {latency.get_models()}")
        logging.debug(f"Cost-Models: {cost.get_models()}")
        logging.debug(f"Privacy-Models: {privacy_data}")
        # Collect rebalanced model weights
        self.rebuild_model_weights(accuracy, quality, latency, cost, privacy_data)
        return {"result": f"Created Model", "model_id": new_model_id}, 200

    def add_policy(self, logos_key: str, entity_id: int, name: str, description: str, threshold_privacy: str,
                   threshold_latency: int, threshold_accuracy: int, threshold_cost: int, threshold_quality: int,
                   priority: int, topic: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("policies", {"entity_id": entity_id, "name": name, "description": description,
                                      "threshold_privacy": threshold_privacy, "threshold_latency": threshold_latency,
                                      "threshold_accuracy": threshold_accuracy, "threshold_cost": threshold_cost,
                                      "threshold_quality": threshold_quality, "priority": priority, "topic": topic})
        return {"result": f"Created Policy", "policy-id": pk}, 200

    def update_policy(self, logos_key: str, id: int, entity_id: int, name: str, description: str, threshold_privacy: str,
                   threshold_latency: int, threshold_accuracy: int, threshold_cost: int, threshold_quality: int,
                   priority: int, topic: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        self.update("policies", id, {"entity_id": entity_id, "name": name, "description": description,
                                      "threshold_privacy": threshold_privacy, "threshold_latency": threshold_latency,
                                      "threshold_accuracy": threshold_accuracy, "threshold_cost": threshold_cost,
                                      "threshold_quality": threshold_quality, "priority": priority, "topic": topic})
        return {"result": f"Created Policy"}, 200

    def delete_policy(self, logos_key: str, id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        self.delete("policies", id)
        return {"result": f"Deleted Policy"}, 200

    def get_policy(self, logos_key: str, policy_id: int):
        sql = text("""
                   SELECT policies.id, policies.name, policies.entity_id, policies.description, policies.threshold_privacy, 
                          policies.threshold_latency, policies.threshold_accuracy, policies.threshold_cost, 
                          policies.threshold_quality, policies.priority, policies.topic
                   FROM process, policies
                   WHERE process.logos_key = :logos_key
                       and process.id = policies.entity_id
                       and policies.id = :policy_id
                   """)
        result = self.session.execute(sql, {"logos_key": logos_key, "policy_id": int(policy_id)}).fetchone()
        if result is None:
            return {"error": "Not Found"}
        return {
            "id": result.id,
            "name": result.name,
            "entity_id": result.entity_id,
            "description": result.description,
            "threshold_privacy": result.threshold_privacy,
            "threshold_latency": result.threshold_latency,
            "threshold_accuracy": result.threshold_accuracy,
            "threshold_cost": result.threshold_cost,
            "threshold_quality": result.threshold_quality,
            "priority": result.priority,
            "topic": result.topic,
        }


    def add_service(self, logos_key: str, name: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("services", {"name": name})
        api_key = generate_logos_api_key(name)
        ppk = self.insert("process", {"logos_key": api_key, "service_id": pk, "name": name})
        return {"result": f"Created Service.", "service-id": pk, "process-id": ppk, "logos-key": api_key}, 200

    def add_token_type(self, name: str, description: str = "", exist_ok = True):
        if token_id := self.get_token_name(name):
            if not exist_ok:
                return {"error": "Token name already exists"}, 500
            else:
                return {"result": f"Created Token Type.", "token-type-id": token_id}, 200
        pk = self.insert("token_types", {"name": name, "description": description})
        return {"result": f"Created Token Type.", "token-type-id": pk}, 200

    def add_billing(self, logos_key: str, type_name: str, type_cost: float, valid_from: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        if (token_id := self.get_token_name(type_name)) is None:
            return {"error": "Token name not found"}, 500
        try:
            timestamp_clean = valid_from.rstrip("Z")
            timestamp = isoparse(timestamp_clean)
        except ValueError as e:
            return {"error": f"Invalid timestamp format: {str(e)}"}, 500

        billing_id = self.insert("token_prices", {"type_id": token_id, "valid_from": timestamp, "price_per_k_token": type_cost})
        return {"result": "Successfully added billing", "billing-id": billing_id}, 200

    def generalstats(self, logos_key: str):
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500
        model_count = self.session.query(func.count(Model.id)).scalar()
        process_count = self.session.query(func.count(Process.id)).scalar()
        request_count = self.session.query(func.count(LogEntry.id)).scalar()

        return {
            "models": model_count,
            "users": process_count,
            "requests": request_count
        }, 200

    def get_token_name(self, name):
        sql = text("""
                   SELECT *
                   FROM token_types
                   WHERE name = :name
                   """)
        entity = self.session.execute(sql, {"name": name}).fetchone()
        if entity is not None:
            return entity.id
        return None

    def get_role(self, logos_key: str):
        sql = text("""
            SELECT *
            FROM process, users
            WHERE logos_key = :logos_key
                and process.user_id = users.id
        """)
        entity = self.session.execute(sql, {"logos_key": logos_key}).fetchone() is not None
        admin = self.check_authorization(logos_key)
        if admin:
            return {"role": "root"}, 200
        elif entity:
            return {"role": "entity"}, 200
        return {"error": "unknown key"}, 500

    def connect_process_provider(self, logos_key: str, profile_id: int, api_id: int):
        if not self.check_authorization(logos_key):
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
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("profile_model_permissions",
                         {"profile_id": int(profile_id), "model_id": int(model_id)})
        return {"result": f"Connected process to model. ID: {pk}"}, 200

    def connect_profile_model(self, logos_key: str, model_id: int, profile_id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("profile_model_permissions", {"model_id": model_id, "profile_id": profile_id})
        return {"result": f"Created Permission. ID: {pk}"}, 200

    def connect_service_process(self, logos_key: str, service_id: int, process_name: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        api_key = generate_logos_api_key("root")
        pk = self.insert("process", {"logos_key": api_key, "service_id": int(service_id),
                                     "name": str(process_name)})
        return {"result": f"Connected service. Process-ID: {pk}.", "api-key": api_key}, 200

    def connect_model_provider(self, logos_key: str, model_id: int, provider_id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("model_provider", {"provider_id": int(provider_id), "model_id": int(model_id)})
        return {"result": f"Connected Model to Provider. ID: {pk}."}, 200

    def add_model_provider_config(
        self,
        logos_key: str,
        model_id: int,
        provider_name: str,
        cold_start_threshold_ms: float = None,
        parallel_capacity: int = None,
        keep_alive_seconds: int = None,
        observed_avg_cold_load_ms: float = None,
        observed_avg_warm_load_ms: float = None
    ) -> Tuple[dict, int]:
        """
        Add or update SDI configuration for a model-provider pair.

        This configures the Scheduling Data Interface (SDI) parameters for how
        a specific model behaves when served by a specific provider.

        Args:
            logos_key: Authorization key (root user only)
            model_id: Model ID to configure
            provider_name: Provider name (e.g., "openwebui", "azure", "openai")
            cold_start_threshold_ms: Threshold for detecting cold starts (ms)
            parallel_capacity: Max concurrent requests this model can handle
            keep_alive_seconds: How long model stays loaded when idle
            observed_avg_cold_load_ms: Observed average cold start time (ms)
            observed_avg_warm_load_ms: Observed average warm start time (ms)

        Returns:
            Tuple of (result dict, status code)
        """
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        # Build config dict with only provided values
        config = {
            "model_id": int(model_id),
            "provider_name": provider_name
        }

        if cold_start_threshold_ms is not None:
            config["cold_start_threshold_ms"] = float(cold_start_threshold_ms)
        if parallel_capacity is not None:
            config["parallel_capacity"] = int(parallel_capacity)
        if keep_alive_seconds is not None:
            config["keep_alive_seconds"] = int(keep_alive_seconds)
        if observed_avg_cold_load_ms is not None:
            config["observed_avg_cold_load_ms"] = float(observed_avg_cold_load_ms)
        if observed_avg_warm_load_ms is not None:
            config["observed_avg_warm_load_ms"] = float(observed_avg_warm_load_ms)

        # Use INSERT ... ON CONFLICT UPDATE pattern for upsert
        from sqlalchemy import text

        # Build column lists dynamically
        columns = list(config.keys())
        placeholders = [f":{col}" for col in columns]

        # Build UPDATE clause for conflict resolution (exclude PK columns)
        update_columns = [col for col in columns if col not in ["model_id", "provider_name"]]
        if update_columns:
            set_expressions = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_columns)
            set_clause = f"{set_expressions}, last_updated = CURRENT_TIMESTAMP"
        else:
            # Only PKs present; still advance timestamp on conflict
            set_clause = "last_updated = CURRENT_TIMESTAMP"

        sql = text(f"""
            INSERT INTO model_provider_config ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            ON CONFLICT (model_id, provider_name)
            DO UPDATE SET {set_clause}
            RETURNING model_id, provider_name
        """)

        result = self.session.execute(sql, config)
        self.session.commit()
        row = result.fetchone()

        return {
            "result": "Created/updated SDI model-provider configuration",
            "model_id": row[0],
            "provider_name": row[1]
        }, 200

    def get_model_provider_config(
        self,
        model_id: int,
        provider_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve SDI configuration for a model-provider pair.

        Args:
            model_id: Model ID to query
            provider_name: Provider name (e.g., "openwebui", "azure", "openai")

        Returns:
            Dictionary with configuration fields if found, None otherwise
        """
        sql = text("""
            SELECT model_id, provider_name, cold_start_threshold_ms,
                   parallel_capacity, keep_alive_seconds,
                   observed_avg_cold_load_ms, observed_avg_warm_load_ms, last_updated
            FROM model_provider_config
            WHERE model_id = :model_id AND provider_name = :provider_name
        """)

        result = self.session.execute(sql, {
            "model_id": model_id,
            "provider_name": provider_name
        }).fetchone()

        if result:
            return {
                "model_id": result[0],
                "provider_name": result[1],
                "cold_start_threshold_ms": result[2],
                "parallel_capacity": result[3],
                "keep_alive_seconds": result[4],
                "observed_avg_cold_load_ms": result[5],
                "observed_avg_warm_load_ms": result[6],
                "last_updated": result[7]
            }
        return None

    def get_provider_config(
        self,
        provider_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve SDI provider-level configuration from providers table.

        Args:
            provider_id: Provider ID to query

        Returns:
            Dictionary with configuration fields if found, None otherwise
        """
        sql = text("""
            SELECT id, ollama_admin_url, total_vram_mb, parallel_capacity,
                   keep_alive_seconds, max_loaded_models, updated_at
            FROM providers
            WHERE id = :provider_id
        """)

        result = self.session.execute(sql, {
            "provider_id": provider_id
        }).fetchone()

        if result:
            return {
                "provider_id": result[0],
                "ollama_admin_url": result[1],
                "total_vram_mb": result[2],
                "parallel_capacity": result[3],
                "keep_alive_seconds": result[4],
                "max_loaded_models": result[5],
                "updated_at": result[6],
            }
        return None

    def update_provider_sdi_config(
        self,
        logos_key: str,
        provider_id: int,
        ollama_admin_url: str = None,
        total_vram_mb: int = None,
        parallel_capacity: int = None,
        keep_alive_seconds: int = None,
        max_loaded_models: int = None,
    ) -> Tuple[dict, int]:
        """
        Update SDI configuration fields in providers table.

        Args:
            logos_key: Authorization key (root user only)
            provider_id: Provider ID to configure
            ollama_admin_url: Internal admin endpoint for Ollama (e.g., http://gpu-vm-1:11434)
            total_vram_mb: Total VRAM capacity in MB (e.g., 49152 for 48GB)
            parallel_capacity: Max concurrent requests per model
            keep_alive_seconds: How long models stay loaded when idle
            max_loaded_models: Max models that can be loaded simultaneously

        Returns:
            Tuple of (result dict, status code)
        """
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        # Build UPDATE SET clauses for non-None fields
        updates = []
        params = {"provider_id": int(provider_id)}

        if ollama_admin_url is not None:
            updates.append("ollama_admin_url = :ollama_admin_url")
            params["ollama_admin_url"] = ollama_admin_url
        if total_vram_mb is not None:
            updates.append("total_vram_mb = :total_vram_mb")
            params["total_vram_mb"] = int(total_vram_mb)
        if parallel_capacity is not None:
            updates.append("parallel_capacity = :parallel_capacity")
            params["parallel_capacity"] = int(parallel_capacity)
        if keep_alive_seconds is not None:
            updates.append("keep_alive_seconds = :keep_alive_seconds")
            params["keep_alive_seconds"] = int(keep_alive_seconds)
        if max_loaded_models is not None:
            updates.append("max_loaded_models = :max_loaded_models")
            params["max_loaded_models"] = int(max_loaded_models)


        if not updates:
            return {"error": "No fields to update"}, 400

        updates.append("updated_at = CURRENT_TIMESTAMP")
        update_clause = ", ".join(updates)

        sql = text(f"""
            UPDATE providers
            SET {update_clause}
            WHERE id = :provider_id
            RETURNING id
        """)

        result = self.session.execute(sql, params)
        self.session.commit()
        row = result.fetchone()

        if not row:
            return {"error": "Provider not found"}, 404

        return {
            "result": "Updated provider SDI configuration",
            "provider_id": row[0]
        }, 200

    def connect_model_api(self, logos_key: str, model_id: int, api_id: int):
        if not self.check_authorization(logos_key):
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

    def add_model_provider_profile(self, logos_key: str, model_name: str, model_endpoint: str, provider_id: int, profile_id: int, api_id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        r, c = self.add_model(logos_key, model_name, model_endpoint)
        if c != 200:
            return r, c
        model_id = r["model_id"]
        r, c = self.connect_model_provider(logos_key, model_id, provider_id)
        if c != 200:
            return r, c
        r, c = self.connect_profile_model(logos_key, model_id, profile_id)
        if c != 200:
            return r, c
        r, c = self.connect_model_api(logos_key, model_id, api_id)
        if c != 200:
            return r, c
        return {"result": f"Successfully added model and connected to profile {profile_id}"}, 200

    def set_process_log(self, process_id: int, log_level: str):
        if log_level not in {"BILLING", "FULL"}:
            return {"error": "Invalid logging level. Choose between 'BILLING' and 'FULL'"}, 400

        sql = text("""
                   UPDATE process
                   SET log = :log_level
                   WHERE id = :process_id
                   """)
        self.session.execute(sql, {
            "log_level": log_level,
            "process_id": int(process_id)
        })
        self.session.commit()
        return {"result": f"Updated log level to {log_level}"}, 200

    def get_process_id(self, logos_key: str):
        sql = text("""
                    SELECT id
                    FROM process
                    WHERE logos_key = :logos_key
        """)
        exc = self.session.execute(sql, {"logos_key": logos_key}).fetchone()
        if exc is None:
            return {"error": "Key not found"}, 500
        return {"result": exc[0]}, 200

    def get_api_id(self, logos_key: str, api_key: str):
        if not self.check_authorization(logos_key):
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

    def get_models_by_profile(self, logos_key: str, profile_id: int):
        """
        Get a list of models accessible by a given profile-ID.
        """
        sql = text("""
                   SELECT models.id
                   FROM models,
                        process,
                        profiles,
                        profile_model_permissions,
                        model_provider,
                        model_api_keys,
                        providers
                   WHERE process.logos_key = :logos_key
                        and process.id = profiles.process_id
                        and profiles.id = profile_model_permissions.profile_id
                        and profile_model_permissions.model_id = model_provider.model_id
                        and model_api_keys.id = models.api_id
                        and model_api_keys.profile_id = profiles.id
                        and model_api_keys.provider_id = providers.id
                        and providers.id = model_provider.provider_id
                        and profiles.id = :profile_id
                   """)
        result = self.session.execute(sql, {"logos_key": logos_key, "profile_id": profile_id}).fetchall()
        return [i.id for i in result]

    def get_models_with_key(self, logos_key: str):
        """
        Get a list of models accessible by a given key.
        """
        sql = text("""
            SELECT models.id
            FROM models, process, profiles, profile_model_permissions, model_provider, model_api_keys, providers
            WHERE process.logos_key = :logos_key
                and process.id = profiles.process_id
                and profiles.id = profile_model_permissions.profile_id
                and profile_model_permissions.model_id = models.id
                and model_api_keys.id = models.api_id
                and model_api_keys.profile_id = profiles.id
                and model_api_keys.provider_id = providers.id
                and providers.id = model_provider.provider_id
        """)
        result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
        return [i.id for i in result]

    def get_all_models(self):
        """
        Get a list of all models. ONLY FOR INTERNAL USE.
        """
        sql = text("""
            SELECT models.id
            FROM models
        """)
        result = self.session.execute(sql).fetchall()
        return [i.id for i in result]

    def get_providers(self, logos_key: str):
        """
        Get a list of providers accessible by a given key.
        """
        sql = text("""
            SELECT DISTINCT providers.id
            FROM providers, model_api_keys, profiles, process
            WHERE process.logos_key = :logos_key
                and process.id = profiles.process_id
                and profiles.id = model_api_keys.profile_id
                and model_api_keys.provider_id = providers.id
        """)
        result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
        return [i.id for i in result]

    def get_provider_info(self, logos_key: str):
        """
        Get a list of providers accessible by a given key.
        """
        sql = text("""
            SELECT DISTINCT providers.id, providers.name, providers.base_url, providers.auth_name, providers.auth_format
            FROM providers, model_api_keys, profiles, process
            WHERE process.logos_key = :logos_key
                and process.id = profiles.process_id
                and profiles.id = model_api_keys.profile_id
                and model_api_keys.provider_id = providers.id
        """)
        result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
        return [(i.id, i.name, i.base_url, i.auth_name, i.auth_format) for i in result]

    def get_general_provider_stats(self, logos_key: str):
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500
        provider_count = self.session.query(func.count(Provider.id)).scalar()
        return {
            "totalProviders": provider_count,
        }, 200

    def get_models_info(self, logos_key: str):
        """
        Get a list of models accessible by a given key.
        """
        sql = text("""
            SELECT DISTINCT models.id, models.name, models.endpoint, models.api_id, models.weight_privacy, models.weight_latency, models.weight_accuracy, models.weight_cost, models.weight_quality, models.tags, models.parallel, models.description
            FROM models, profile_model_permissions, profiles, process
            WHERE process.logos_key = :logos_key
                and process.id = profiles.process_id
                and profiles.id = profile_model_permissions.profile_id
                and profile_model_permissions.model_id = models.id
        """)
        result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
        return [(i.id, i.name, i.endpoint, i.api_id, i.weight_privacy, i.weight_latency, i.weight_accuracy, i.weight_cost, i.weight_quality, i.tags, i.parallel, i.description) for i in result]

    def get_all_models_data(self):
        """
        Get a list of models and their data in the database. Used for rebalancing.
        """
        sql = text("""
            SELECT models.id, models.name, models.endpoint, models.api_id, models.weight_privacy, models.weight_latency, models.weight_accuracy, models.weight_cost, models.weight_quality, models.tags, models.parallel, models.description
            FROM models
        """)
        result = self.session.execute(sql).fetchall()
        return [(i.id, i.name, i.endpoint, i.api_id, i.weight_privacy, i.weight_latency, i.weight_accuracy, i.weight_cost, i.weight_quality, i.tags, i.parallel, i.description) for i in result]

    def get_policy_info(self, logos_key: str):
        """
        Get a list of policies accessible by a given key.
        """
        sql = text("""
            SELECT DISTINCT policies.id, policies.entity_id, policies.name, policies.description, policies.threshold_privacy, policies.threshold_latency, policies.threshold_accuracy, policies.threshold_cost, policies.threshold_quality, policies.priority, policies.topic
            FROM policies, process, profiles, profile_model_permissions, models
            WHERE process.logos_key = :logos_key
                and process.id = policies.entity_id
                and profiles.id = profile_model_permissions.profile_id
                and profile_model_permissions.model_id = models.id
        """)
        result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
        return [(i.id, i.entity_id, i.name, i.description, i.threshold_privacy, i.threshold_latency, i.threshold_accuracy, i.threshold_cost, i.threshold_quality, i.priority, i.topic) for i in result]


    def get_general_model_stats(self, logos_key: str):
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500
        model_count = self.session.query(func.count(Model.id)).scalar()
        return {
            "totalModels": model_count,
        }, 200


    def get_model(self, model_id: int):
        sql = text("""
            SELECT *
            FROM models
            WHERE id = :model_id
        """)
        result = self.session.execute(sql, {"model_id": int(model_id)}).fetchone()
        if result is None:
            return None
        return {
            "id": result.id,
            "name": result.name,
            "endpoint": result.endpoint,
            "api_id": result.api_id,
            "weight_privacy": result.weight_privacy,
            "weight_latency": result.weight_latency,
            "weight_accuracy": result.weight_accuracy,
            "weight_cost": result.weight_cost,
            "weight_quality": result.weight_quality,
            "tags": result.tags,
            "parallel": result.parallel,
            "description": result.description
        }

    def get_provider(self, provider_id: int):
        sql = text("""
            SELECT *
            FROM providers
            WHERE id = :provider_id
        """)
        result = self.session.execute(sql, {"provider_id": int(provider_id)}).fetchone()
        if result is None:
            return None
        return {
            "id": result.id,
            "name": result.name,
            "base_url": result.base_url,
            "auth_name": result.auth_name,
            "auth_format": result.auth_format,
        }

    def get_provider_to_model(self, model_id: int):
        sql = text("""
                   SELECT provider_id
                   FROM model_provider
                   WHERE model_id = :model_id
                   """)
        result = self.session.execute(sql, {"model_id": int(model_id)}).fetchone()
        if result is None:
            return None
        return self.get_provider(result.provider_id)

    def get_key_to_model_provider(self, model_id: int, provider_id: int):
        sql = text("""
                   SELECT api_key
                   FROM model_api_keys, models, model_provider, providers
                   WHERE models.api_id = model_api_keys.id
                       and providers.id = model_provider.provider_id
                       and model_provider.model_id = models.id
                       and model_api_keys.provider_id = providers.id
                       and models.id = :model_id
                       and providers.id = :provider_id
                   """)
        result = self.session.execute(sql, {"model_id": int(model_id), "provider_id": int(provider_id)}).fetchone()
        if result is None:
            return None
        return result.api_key

    def log(self, process_id: int):
        sql = text("""
                   SELECT log
                   FROM process
                   WHERE id = :process_id
                   """)
        result = self.session.execute(sql, {"process_id": int(process_id)}).fetchone()
        if result is None:
            return False
        return result.log

    def log_usage(self, process_id: int, client_ip: str = None, input_payload=None, headers=None):
        # Hole log_level für den Prozess
        log_level_result = self.session.execute(
            text("SELECT log FROM process WHERE id = :pid"),
            {"pid": process_id}
        ).fetchone()

        if log_level_result is None:
            return {"error": "Invalid process ID"}, 404

        log_level = log_level_result[0]  # 'BILLING' oder 'FULL'

        sql = text("""
                   INSERT INTO log_entry (timestamp_request, process_id, client_ip, input_payload, headers,
                                          privacy_level)
                   VALUES (:timestamp_request, :process_id, :client_ip, :input_payload, :headers,
                           :privacy_level) RETURNING id
                   """)
        result = self.session.execute(sql, {
            "timestamp_request": datetime.datetime.now(datetime.timezone.utc),
            "process_id": process_id,
            "client_ip": client_ip if log_level == "FULL" else None,
            "input_payload": json.dumps(input_payload) if log_level == "FULL" else None,
            "headers": json.dumps(headers) if log_level == "FULL" else None,
            "privacy_level": log_level
        })

        log_id = result.scalar()
        self.session.commit()
        return {"result": f"Created log entry.", "log-id": log_id}, 200

    def set_time_at_first_token(self, log_id: int):
        sql = text("""
                   UPDATE log_entry
                   SET time_at_first_token = :timestamp
                   WHERE id = :log_id
                   """)
        self.session.execute(sql, {
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "log_id": log_id
        })
        self.session.commit()
        return {"result": "time_at_first_token set"}, 200

    def set_forward_timestamp(self, log_id: int):
        sql = text("""
                   UPDATE log_entry
                   SET timestamp_forwarding = :timestamp
                   WHERE id = :log_id
                   """)
        self.session.execute(sql, {
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "log_id": log_id
        })
        self.session.commit()
        return {"result": "time_timestamp_forwarding set"}, 200

    def set_response_timestamp(self, log_id: int):
        sql = text("""
                   UPDATE log_entry
                   SET timestamp_response = :timestamp
                   WHERE id = :log_id
                   """)
        self.session.execute(sql, {
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "log_id": log_id
        })
        self.session.commit()
        return {"result": "timestamp_response set"}, 200

    def set_response_payload(self, log_id: int, payload: dict, provider_id=None, model_id=None, usage=None, policy_id=-1,
                             classified=None, **kwargs):
        # Hole Privacy-Level
        if classified is None:
            classified = dict()
        if usage is None:
            usage = dict()
        result = self.session.execute(
            text("SELECT privacy_level FROM log_entry WHERE id = :log_id"),
            {"log_id": log_id}
        ).fetchone()

        if result is None:
            return {"error": "Log entry not found"}, 404

        if result[0] != "FULL":
            payload = None

        type_ids = dict()
        for token_type, token_count in usage.items() if usage is not None else dict().items():
            r, c = self.add_token_type(token_type, "")
            if "error" in r:
                return r, c
            type_ids[token_type] = r["token-type-id"]

        for token_type in type_ids:
            if usage[token_type]:
                _ = self.insert("usage_tokens",
                                {"log_entry_id": log_id, "type_id": type_ids[token_type], "token_count": usage[token_type]})

        sql = text("""
                   UPDATE log_entry
                   SET response_payload = :payload,
                       provider_id      = COALESCE(:provider_id, provider_id),
                       model_id         = COALESCE(:model_id, model_id),
                       timestamp_response = :timestamp,
                       policy_id        = COALESCE(:policy_id, policy_id),
                       classification_statistics = :classification_statistics,
                       queue_depth_at_arrival = COALESCE(:queue_depth, queue_depth_at_arrival),
                       utilization_at_arrival = COALESCE(:utilization, utilization_at_arrival)
                   WHERE id = :log_id
                   """)
        self.session.execute(sql, {
            "payload": json.dumps(payload) if payload else None,
            "provider_id": provider_id,
            "model_id": model_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "log_id": log_id,
            "policy_id": policy_id if policy_id != -1 else None,
            "classification_statistics": json.dumps(classified),
            "queue_depth": kwargs.get("queue_depth_at_arrival"),
            "utilization": kwargs.get("utilization_at_arrival")
        })
        self.session.commit()
        return {"result": "response_payload set"}, 200

    def export(self, logos_key: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database exports only allowed for root user."}, 403

        data = {}
        for table in Base.metadata.sorted_tables:
            rows = self.session.execute(table.select()).fetchall()
            data[table.name] = [dict(row._mapping) for row in rows]

        return {"result": data}, 200

    def reset_sequences(self):
        # Adjust ID's after importing data
        for table_name in [
            "users",
            "services",
            "process",
            "profiles",
            "providers",
            "model_api_keys",
            "models",
            "model_provider",
            "profile_model_permissions",
            "policies",
            "log_entry",
            "token_types",
            "usage_tokens",
            "token_prices"
        ]:
            # Check if table exists
            table = Base.metadata.tables.get(table_name)
            if table is None:
                continue

            # Check if column 'id' exists
            if 'id' in table.c:
                # Get name of related sequence (PostgreSQL-Name-convention)
                sequence_name = f"{table_name}_id_seq"

                # Max ID of Table
                result = self.session.execute(text(f"SELECT MAX(id) FROM {table_name}"))
                max_id = result.scalar()

                if max_id is not None:
                    # Data → next ID = max_id + 1
                    self.session.execute(
                        text("SELECT setval(:sequence_name, :new_value, true)"),
                        {"sequence_name": sequence_name, "new_value": max_id + 1}
                    )
                else:
                    # Empty Table
                    self.session.execute(
                        text("SELECT setval(:sequence_name, 1, false)"),
                        {"sequence_name": sequence_name}
                    )
        self.session.commit()

    def import_from_json(self, logos_key: str, json_data: dict):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        # Store table names to prevent silent errors on foreign key insertions
        table_names = [
            "users",
            "services",
            "process",
            "profiles",
            "providers",
            "model_api_keys",
            "models",
            "model_provider",
            "profile_model_permissions",
            "policies",
            "log_entry",
            "token_types",
            "usage_tokens",
            "token_prices"
        ]
        for table_name in table_names:
            if table_name not in json_data:
                return {"error": f"Missing table in json: {table_name}"}, 500
            rows = json_data[table_name]
            table = Base.metadata.tables.get(table_name)
            if table is not None:
                if rows:
                    self.session.execute(table.delete())
                    self.session.execute(table.insert(), rows)
                else:
                    self.session.execute(table.delete())
            if table_name == "process":
                found = False
                for row in rows:
                    if row["name"] == "root":
                        found = True
                        break
                if not found:
                    return {"error": "Try to delete root user detected. Aborting"}, 500
        self.session.commit()
        self.reset_sequences()
        return {"result": f"Imported data"}, 200

    def check_authorization(self, logos_key: str):
        sql = text("""
                                SELECT *
                                FROM process, users
                                WHERE logos_key = :logos_key
                                    and process.user_id = users.id
                                    and users.name = 'root'
                            """)
        return self.session.execute(sql, {"logos_key": logos_key}).fetchone() is not None

    def user_authorization(self, logos_key: str):
        sql = text("""
                                SELECT *
                                FROM process
                                WHERE logos_key = :logos_key
                            """)
        return self.session.execute(sql, {"logos_key": logos_key}).fetchone() is not None

    def __enter__(self):
        # conf = load_postgres_env_vars_from_compose()    # {conf['port']}
        db_url = f"postgresql://postgres:root@logos-db:5432/logosdb"
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
