"""
Central Manager for all Database-related actions for Logos
"""
import datetime
import os
import secrets
from typing import Dict, Any, Optional, Tuple, Union, List, cast

import sqlalchemy.exc
import yaml
import json
import logging
from dateutil.parser import isoparse
from sqlalchemy import Table, MetaData, create_engine
from sqlalchemy import text, func, bindparam
from sqlalchemy.orm import sessionmaker

from logos.classification.model_handler import ModelHandler
from logos.dbutils.dbmodules import *
from logos.dbutils.dbmodules import JobStatus
from logos.dbutils.types import Deployment, get_unique_models_from_deployments

# Backwards-compatible re-export (temporary; remove once all imports are migrated)
__all__ = [
    "DBManager",
    "Deployment",
    "get_unique_models_from_deployments",
]

logger = logging.getLogger(__name__)


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

    def create_job_record(
        self,
        request_payload: Dict[str, Any],
        process_id: int,
        profile_id: int,
        status: str = JobStatus.PENDING.value,
    ) -> int:
        """
        Persist a new async job with profile isolation.

        Args:
            request_payload: Job request data
            process_id: Process owning this job (for billing)
            profile_id: Profile executing this job (for authorization)
            status: Initial job status

        Returns:
            Job ID
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        return self.insert(
            "jobs",
            {
                "status": status,
                "process_id": process_id,
                "profile_id": profile_id,
                "request_payload": request_payload,
                "created_at": now,
                "updated_at": now,
            },
        )

    def update_job_status(
        self,
        job_id: int,
        status: str,
        result_payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Update job status and optional payloads.
        """
        update_data = {
            "status": status,
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
        }
        if result_payload is not None:
            update_data["result_payload"] = result_payload
        if error_message is not None:
            update_data["error_message"] = error_message
        self.update("jobs", job_id, update_data)

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch job state by id.
        """
        return self.fetch_by_id("jobs", job_id)

    def fetch_llm_key(self, logos_key: str):
        sql = text("""
                SELECT mak.api_key,
                       providers.name  as name,
                       providers.base_url as base_url,
                       providers.id    as provider_id,
                       providers.auth_name as auth_name,
                       providers.auth_format as auth_format,
                       process.id      as process_id
                FROM process
                    JOIN profiles ON profiles.process_id = process.id
                    JOIN profile_model_permissions pmp ON pmp.profile_id = profiles.id
                    JOIN models m ON m.id = pmp.model_id
                    JOIN model_provider mp ON mp.model_id = m.id
                    JOIN providers ON providers.id = mp.provider_id
                    LEFT JOIN model_api_keys mak ON mak.model_id = m.id AND mak.provider_id = providers.id
                WHERE process.logos_key = :logos_key
                LIMIT 1
            """)

        result = self.session.execute(sql, {
            "logos_key": logos_key
        }).fetchone()
        if result:
            return {
                "api_key": result.api_key,
                "provider_name": result.name,
                "base_url": result.base_url,
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
                     api_key: str, auth_name: str, auth_format: str, provider_type: str) -> Tuple[dict, int]:
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        provider_type = (provider_type or "").strip()
        if not provider_type:
            return {"error": "provider_type is required"}, 400
        pk = self.insert("providers", {"name": provider_name, "base_url": base_url,
                                       "auth_name": auth_name, "auth_format": auth_format,
                                       "provider_type": provider_type})
        return {"result": f"Created Provider.", "provider-id": pk}, 200

    def add_profile(self, logos_key: str, profile_name: str, process_id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("profiles", {"name": profile_name, "process_id": process_id})
        return {"result": f"Added profile", "profile-id": pk}, 200

    def get_profile(self, profile_id: int):
        """
        Get profile by ID.

        Returns:
            Dict with {id, name, process_id} or None if not found
        """
        sql = text("""
            SELECT id, name, process_id
            FROM profiles
            WHERE id = :profile_id
        """)
        result = self.session.execute(sql, {"profile_id": profile_id}).fetchone()
        if not result:
            return None
        return {
            "id": result.id,
            "name": result.name,
            "process_id": result.process_id
        }

    def get_profiles_for_process(self, process_id: int):
        """
        Get all profiles for a process.

        Returns:
            List of dicts with {id, name}
        """
        sql = text("""
            SELECT id, name
            FROM profiles
            WHERE process_id = :process_id
            ORDER BY id
        """)
        results = self.session.execute(sql, {"process_id": process_id}).fetchall()
        return [{"id": r.id, "name": r.name} for r in results]

    def add_model(self, logos_key: str, name: str, endpoint: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("models", {"name": name, "endpoint": endpoint})
        return {"result": f"Created Model", "model_id": pk}, 200

    def add_full_model(self, logos_key: str, name: str, endpoint: str,
                       weight_privacy: str = "LOCAL", worse_accuracy: int = None, worse_quality: int = None, worse_latency: int = None, worse_cost: int = None, tags: str = "", parallel: int = 1,
                       description: str = ""):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert("models", {"name": name, "endpoint": endpoint, "weight_privacy": weight_privacy, "tags": tags, "parallel": parallel, "description": description})
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
            mid, p, l, a, c, q = model[0], model[3], model[4], model[5], model[6], model[7]
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
            mid, p, l, a, c, q = model[0], model[3], model[4], model[5], model[6], model[7]
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
            mid, p, l, a, c, q = model[0], model[3], model[4], model[5], model[6], model[7]
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

    def get_request_event_stats(
        self,
        logos_key: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        target_buckets: int = 120
    ):
        """
        Aggregate request_events metrics for a given time range.

        Args:
            logos_key: authentication key
            start_date: ISO timestamp (inclusive). Defaults to 30 days before end_date.
            end_date: ISO timestamp (inclusive). Defaults to now (UTC).
            target_buckets: Desired number of buckets for time-series aggregation (auto-adjusted).
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        # Resolve date range
        now = datetime.datetime.now(datetime.timezone.utc)
        end_dt = isoparse(end_date).astimezone(datetime.timezone.utc) if end_date else now
        start_dt = isoparse(start_date).astimezone(datetime.timezone.utc) if start_date else end_dt - datetime.timedelta(days=30)
        if start_dt > end_dt:
            return {"error": "start_date must be before end_date"}, 400

        # Bucket sizing: tighter buckets for narrow ranges, looser for broad ranges
        duration_seconds = max((end_dt - start_dt).total_seconds(), 1)
        target_buckets = max(int(target_buckets or 120), 1)
        raw_bucket = max(duration_seconds / target_buckets, 60)  # never below 1 minute
        nice_candidates = [60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400]  # 1m .. 24h
        bucket_seconds = min(nice_candidates, key=lambda b: abs(b - raw_bucket))

        params = {
            "start_ts": start_dt,
            "end_ts": end_dt,
            "bucket_seconds": bucket_seconds
        }
        ts_expr = "COALESCE(scheduled_ts, enqueue_ts, request_complete_ts)"

        # Last event timestamp
        last_ts = self.session.execute(
            text(f"SELECT MAX({ts_expr}) AS last_ts FROM request_events WHERE {ts_expr} BETWEEN :start_ts AND :end_ts"),
            params
        ).scalar()
        last_event_ts = last_ts.isoformat() if last_ts else None

        # Totals and averages
        totals_row = self.session.execute(text(f"""
            SELECT
                COUNT(*) AS requests,
                COUNT(*) FILTER (WHERE is_cloud) AS cloud_requests,
                COUNT(*) FILTER (WHERE NOT is_cloud) AS local_requests,
                COUNT(*) FILTER (WHERE cold_start IS TRUE) AS cold_starts,
                COUNT(*) FILTER (WHERE cold_start IS NOT TRUE) AS warm_starts,
                AVG(queue_seconds) AS avg_queue_seconds,
                AVG(run_seconds) AS avg_run_seconds
            FROM (
                SELECT
                    re.cold_start,
                    CASE WHEN m.weight_privacy = 'LOCAL' THEN FALSE ELSE TRUE END AS is_cloud,
                    CASE WHEN re.enqueue_ts IS NOT NULL AND re.scheduled_ts IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (re.scheduled_ts - re.enqueue_ts)) END AS queue_seconds,
                    CASE WHEN re.scheduled_ts IS NOT NULL AND re.request_complete_ts IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (re.request_complete_ts - re.scheduled_ts)) END AS run_seconds
                FROM request_events re
                LEFT JOIN models m ON m.id = re.model_id
                WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
            ) stats
        """), params).mappings().first() or {}

        totals = {
            "requests": int(totals_row.get("requests") or 0),
            "cloudRequests": int(totals_row.get("cloud_requests") or 0),
            "localRequests": int(totals_row.get("local_requests") or 0),
            "coldStarts": int(totals_row.get("cold_starts") or 0),
            "warmStarts": int(totals_row.get("warm_starts") or 0),
            "avgQueueSeconds": float(totals_row["avg_queue_seconds"]) if totals_row.get("avg_queue_seconds") is not None else None,
            "avgRunSeconds": float(totals_row["avg_run_seconds"]) if totals_row.get("avg_run_seconds") is not None else None,
        }

        # Status counts
        status_rows = self.session.execute(text(f"""
            SELECT COALESCE(result_status::text, 'unknown') AS status, COUNT(*) AS count
            FROM request_events
            WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
            GROUP BY COALESCE(result_status::text, 'unknown')
        """), params).mappings().all()
        status_counts = {row["status"].lower(): int(row["count"]) for row in status_rows}

        # Model breakdown
        model_rows = self.session.execute(text(f"""
            SELECT
                re.model_id,
                COALESCE(m.name, CONCAT('Model ', re.model_id::text)) AS model_name,
                re.provider_id,
                COALESCE(p.name, CONCAT('Provider ', re.provider_id::text)) AS provider_name,
                COUNT(*) AS request_count,
                AVG(queue_seconds) AS avg_queue_seconds,
                AVG(run_seconds) AS avg_run_seconds,
                SUM(CASE WHEN re.cold_start IS TRUE THEN 1 ELSE 0 END) AS cold_starts,
                SUM(CASE WHEN re.cold_start IS NOT TRUE THEN 1 ELSE 0 END) AS warm_starts,
                SUM(CASE WHEN re.result_status IS DISTINCT FROM 'success' OR (re.error_message IS NOT NULL AND re.error_message != '') THEN 1 ELSE 0 END) AS error_count
            FROM (
                SELECT
                    re.*,
                    CASE WHEN re.enqueue_ts IS NOT NULL AND re.scheduled_ts IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (re.scheduled_ts - re.enqueue_ts)) END AS queue_seconds,
                    CASE WHEN re.scheduled_ts IS NOT NULL AND re.request_complete_ts IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (re.request_complete_ts - re.scheduled_ts)) END AS run_seconds
                FROM request_events re
                WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
            ) re
            LEFT JOIN models m ON m.id = re.model_id
            LEFT JOIN providers p ON p.id = re.provider_id
            GROUP BY re.model_id, model_name, re.provider_id, provider_name
            ORDER BY request_count DESC
        """), params).mappings().all()
        model_breakdown = [{
            "modelId": row["model_id"] if row["model_id"] is not None else -1,
            "modelName": row["model_name"],
            "providerName": row["provider_name"],
            "requestCount": int(row["request_count"] or 0),
            "avgQueueSeconds": float(row["avg_queue_seconds"]) if row["avg_queue_seconds"] is not None else None,
            "avgRunSeconds": float(row["avg_run_seconds"]) if row["avg_run_seconds"] is not None else None,
            "coldStarts": int(row["cold_starts"] or 0),
            "warmStarts": int(row["warm_starts"] or 0),
            "errorCount": int(row["error_count"] or 0),
        } for row in model_rows]

        # Time series bucketed by bucket_seconds, with gap filling for idle periods
        time_rows = self.session.execute(text(f"""
            WITH bucket_series AS (
                SELECT generate_series(
                    to_timestamp(FLOOR(EXTRACT(EPOCH FROM :start_ts) / :bucket_seconds) * :bucket_seconds),
                    to_timestamp(FLOOR(EXTRACT(EPOCH FROM :end_ts) / :bucket_seconds) * :bucket_seconds),
                    (:bucket_seconds || ' seconds')::interval
                ) AS bucket_ts
            ),
            agg AS (
                SELECT
                    to_timestamp(FLOOR(EXTRACT(EPOCH FROM {ts_expr}) / :bucket_seconds) * :bucket_seconds) AS bucket_ts,
                    COUNT(*) AS total,
                    SUM(CASE WHEN m.weight_privacy = 'LOCAL' OR m.weight_privacy IS NULL THEN 0 ELSE 1 END) AS cloud,
                    SUM(CASE WHEN m.weight_privacy = 'LOCAL' OR m.weight_privacy IS NULL THEN 1 ELSE 0 END) AS local,
                    AVG(CASE WHEN re.scheduled_ts IS NOT NULL AND re.request_complete_ts IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (re.request_complete_ts - re.scheduled_ts)) END) AS avg_run_seconds,
                    AVG(re.available_vram_mb) AS avg_vram
                FROM request_events re
                LEFT JOIN models m ON m.id = re.model_id
                WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
                GROUP BY 1
            )
            SELECT
                EXTRACT(EPOCH FROM bs.bucket_ts) AS bucket_ts,
                COALESCE(agg.total, 0) AS total,
                COALESCE(agg.cloud, 0) AS cloud,
                COALESCE(agg.local, 0) AS local,
                agg.avg_run_seconds,
                agg.avg_vram
            FROM bucket_series bs
            LEFT JOIN agg ON agg.bucket_ts = bs.bucket_ts
            ORDER BY bs.bucket_ts
        """), params).mappings().all()
        time_series = [{
            "timestamp": int(row["bucket_ts"]) * 1000 if row["bucket_ts"] is not None else None,
            "label": "",
            "cloud": int(row["cloud"] or 0),
            "local": int(row["local"] or 0),
            "total": int(row["total"] or 0),
            "avgRunSeconds": float(row["avg_run_seconds"]) if row["avg_run_seconds"] is not None else None,
            "avgVram": float(row["avg_vram"]) if row["avg_vram"] is not None else None,
        } for row in time_rows if row["bucket_ts"] is not None]

        # Queue depth
        queue_row = self.session.execute(text(f"""
            SELECT
                AVG(queue_depth_at_enqueue) AS avg_enqueue,
                AVG(queue_depth_at_schedule) AS avg_schedule,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY queue_depth_at_enqueue) AS p95_enqueue,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY queue_depth_at_schedule) AS p95_schedule
            FROM request_events re
            WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
              AND (queue_depth_at_enqueue IS NOT NULL OR queue_depth_at_schedule IS NOT NULL)
        """), params).mappings().first()
        queue_depth = None
        if queue_row:
            queue_depth = {
                "avgEnqueueDepth": float(queue_row["avg_enqueue"]) if queue_row.get("avg_enqueue") is not None else None,
                "avgScheduleDepth": float(queue_row["avg_schedule"]) if queue_row.get("avg_schedule") is not None else None,
                "p95EnqueueDepth": float(queue_row["p95_enqueue"]) if queue_row.get("p95_enqueue") is not None else None,
                "p95ScheduleDepth": float(queue_row["p95_schedule"]) if queue_row.get("p95_schedule") is not None else None,
            }

        # Runtime by cold/warm
        runtime_rows = self.session.execute(text(f"""
            SELECT
                CASE WHEN cold_start IS TRUE THEN 'cold' ELSE 'warm' END AS kind,
                COUNT(*) AS count,
                AVG(CASE WHEN re.scheduled_ts IS NOT NULL AND re.request_complete_ts IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (re.request_complete_ts - re.scheduled_ts)) END) AS avg_run_seconds
            FROM request_events re
            WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
            GROUP BY kind
        """), params).mappings().all()
        runtime_by_cold = [{
            "type": row["kind"],
            "avgRunSeconds": float(row["avg_run_seconds"]) if row["avg_run_seconds"] is not None else None,
            "count": int(row["count"] or 0),
        } for row in runtime_rows]

        payload = {
            "range": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
            },
            "bucketSeconds": bucket_seconds,
            "stats": {
                "lastEventTs": last_event_ts,
                "totals": totals,
                "statusCounts": status_counts,
                "modelBreakdown": model_breakdown,
                "timeSeries": time_series,
                "queueDepth": queue_depth,
                "runtimeByColdStart": runtime_by_cold,
            },
        }
        return payload, 200

    def get_latest_requests(self, logos_key: str, limit: int = 10):
        """
        Fetch the most recent request events.
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        sql = text("""
            SELECT
                re.request_id,
                COALESCE(m.name, CONCAT('Model ', re.model_id::text)) AS model_name,
                COALESCE(p.name, CONCAT('Provider ', re.provider_id::text)) AS provider_name,
                re.result_status,
                re.enqueue_ts,
                re.request_complete_ts,
                CASE WHEN re.scheduled_ts IS NOT NULL AND re.request_complete_ts IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (re.request_complete_ts - re.scheduled_ts))
                     ELSE NULL
                END AS run_seconds,
                re.cold_start
            FROM request_events re
            LEFT JOIN models m ON m.id = re.model_id
            LEFT JOIN providers p ON p.id = re.provider_id
            ORDER BY re.enqueue_ts DESC NULLS LAST
            LIMIT :limit
        """)

        rows = self.session.execute(sql, {"limit": limit}).mappings().all()

        results = []
        for row in rows:
            results.append({
                "request_id": row["request_id"],
                "model_name": row["model_name"],
                "provider_name": row["provider_name"],
                "status": row["result_status"] if row["result_status"] else "unknown",
                "timestamp": row["enqueue_ts"].isoformat() if row["enqueue_ts"] else None,
                "duration": float(row["run_seconds"]) if row["run_seconds"] is not None else None,
                "cold_start": row["cold_start"]
            })

        return {"requests": results}, 200

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

    def connect_process_provider(self, logos_key: str, profile_id: int, provider_id: int):
        """
        Grant a profile access to all models served by a provider by creating
        profile_model_permissions entries for each model tied to that provider.
        """
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        if self.get_profile(profile_id) is None:
            return {"error": f"Profile {profile_id} not found."}, 404
        if self.get_provider(provider_id) is None:
            return {"error": f"Provider {provider_id} not found."}, 404

        model_rows = self.session.execute(
            text("SELECT model_id FROM model_provider WHERE provider_id = :provider_id"),
            {"provider_id": int(provider_id)}
        ).fetchall()

        created = 0
        for row in model_rows:
            exists = self.session.execute(
                text("""
                    SELECT 1 FROM profile_model_permissions
                    WHERE profile_id = :profile_id AND model_id = :model_id
                """),
                {"profile_id": int(profile_id), "model_id": int(row.model_id)}
            ).fetchone()
            if exists:
                continue
            self.insert("profile_model_permissions", {
                "profile_id": int(profile_id),
                "model_id": int(row.model_id)
            })
            created += 1

        return {"result": f"Granted access to {created} model(s) for provider {provider_id}."}, 200

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
        # Link model to provider
        pk = self.insert("model_provider", {"provider_id": int(provider_id), "model_id": int(model_id)})

        # Ensure a model_api_keys entry exists (empty key placeholder) for this pair
        upsert_sql = text("""
            INSERT INTO model_api_keys (model_id, provider_id, api_key)
            VALUES (:model_id, :provider_id, '')
            ON CONFLICT (model_id, provider_id) DO NOTHING
            RETURNING id
        """)
        self.session.execute(upsert_sql, {"model_id": int(model_id), "provider_id": int(provider_id)})
        self.session.commit()

        return {"result": f"Connected Model to Provider. ID: {pk}."}, 200

    def add_model_provider_config(
        self,
        logos_key: str,
        model_id: int,
        provider_id: int,
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
            provider_id: Provider ID
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
            "provider_id": int(provider_id)
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
        update_columns = [col for col in columns if col not in ["model_id", "provider_id"]]
        if update_columns:
            set_expressions = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_columns)
            set_clause = f"{set_expressions}, last_updated = CURRENT_TIMESTAMP"
        else:
            # Only PKs present; still advance timestamp on conflict
            set_clause = "last_updated = CURRENT_TIMESTAMP"

        sql = text(f"""
            INSERT INTO model_provider_config ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            ON CONFLICT (model_id, provider_id)
            DO UPDATE SET {set_clause}
            RETURNING model_id, provider_id
        """)

        result = self.session.execute(sql, config)
        self.session.commit()
        row = result.fetchone()

        return {
            "result": "Created/updated SDI model-provider configuration",
            "model_id": row[0],
            "provider_id": row[1]
        }, 200

    def get_model_provider_config(
        self,
        model_id: int,
        provider_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve SDI configuration for a model-provider pair.

        Args:
            model_id: Model ID to query
            provider_id: Provider ID

        Returns:
            Dictionary with configuration fields if found, None otherwise
        """
        sql = text("""
            SELECT model_id, provider_id, cold_start_threshold_ms,
                   parallel_capacity, keep_alive_seconds,
                   observed_avg_cold_load_ms, observed_avg_warm_load_ms, last_updated
            FROM model_provider_config
            WHERE model_id = :model_id AND provider_id = :provider_id
        """)

        result = self.session.execute(sql, {
            "model_id": model_id,
            "provider_id": int(provider_id)
        }).fetchone()

        if result:
            return {
                "model_id": result[0],
                "provider_id": result[1],
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

    # TODO: Currently we support keys per provider/model pair , we dont have specific keys per provider, this is a workaround
    def get_provider_auth(self, provider_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve provider auth header formatting and any available API key.

        Returns:
            Dict with auth_name, auth_format, api_key (may be None) or None if provider not found.
        """
        sql = text("""
            SELECT providers.id,
                   providers.auth_name,
                   providers.auth_format,
                   model_api_keys.api_key
            FROM providers
            LEFT JOIN model_api_keys
                   ON model_api_keys.provider_id = providers.id
            WHERE providers.id = :provider_id
            ORDER BY model_api_keys.id
            LIMIT 1
        """)

        result = self.session.execute(sql, {"provider_id": provider_id}).fetchone()
        if not result:
            return None

        return {
            "provider_id": result[0],
            "auth_name": result[1],
            "auth_format": result[2],
            "api_key": result[3],
        }

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

    def get_ollama_providers(self) -> List[Dict[int, str]]:
        """
        Get all ollama providers IDs from providers table.

        Returns:
            List of:
            - provider ID
            - ollama_admin_url
        """
        sql = text("""
            SELECT id, ollama_admin_url
            FROM providers
            WHERE provider_type = 'ollama'
            ORDER BY id
        """)

        result = self.session.execute(sql).fetchall()
        providers: List[Dict[int, str]] = []
        for row in result:
            providers.append({
                "id": row.id,
                "ollama_admin_url": row.ollama_admin_url,
            })
        return providers

    def insert_provider_snapshot(
        self,
        ollama_admin_url: str,
        total_models_loaded: int,
        total_vram_used_bytes: int,
        loaded_models: List[Dict[str, Any]],
        poll_success: bool = True,
        error_message: Optional[str] = None
    ) -> None:
        """
        Insert Ollama provider snapshot into monitoring table.

        Args:
            ollama_admin_url: Ollama admin URL (e.g., "http://host.docker.internal:11435")
            total_models_loaded: Number of models currently loaded
            total_vram_used_bytes: Total VRAM used by all loaded models (in bytes)
            loaded_models: List of model details (name, size_vram, expires_at)
            poll_success: Whether the poll was successful
            error_message: Error message if poll failed
        """
        sql = text("""
            INSERT INTO ollama_provider_snapshots (
                ollama_admin_url,
                total_models_loaded,
                total_vram_used_bytes,
                loaded_models,
                poll_success,
                error_message
            ) VALUES (
                :ollama_admin_url,
                :total_models_loaded,
                :total_vram_used_bytes,
                :loaded_models,
                :poll_success,
                :error_message
            )
        """)

        self.session.execute(sql, {
            "ollama_admin_url": ollama_admin_url,
            "total_models_loaded": total_models_loaded,
            "total_vram_used_bytes": total_vram_used_bytes,
            "loaded_models": json.dumps(loaded_models),
            "poll_success": poll_success,
            "error_message": error_message
        })
        self.session.commit()

    def get_ollama_vram_stats(
        self,
        logos_key: str,
        day: str,
        bucket_seconds: int = 5,  # kept for signature compatibility; ignored
    ) -> Tuple[Dict[str, Any], int]:
        """
        Return per-provider VRAM snapshots for a single UTC day. No bucketing/zero-fill; raw rows only.

        `day` is required (YYYY-MM-DD or ISO date). If no rows exist for that day, an error is returned.
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        tz_utc = datetime.timezone.utc

        # Date range resolution: required day
        try:
            parsed_day = isoparse(day)
        except Exception:
            return {"error": f"Invalid day format: {day}"}, 400

        day_date = parsed_day.date()
        start_dt = datetime.datetime.combine(day_date, datetime.time.min, tzinfo=tz_utc)
        end_dt = start_dt + datetime.timedelta(days=1)

        now = datetime.datetime.now(tz_utc)
        if start_dt > now:
            return {"error": "Requested day is in the future."}, 400
        # Clamp end to "now" if requesting today
        if end_dt > now:
            end_dt = now

        params = {
            "start_ts": start_dt,
            "end_ts": end_dt,
        }

        sql = text("""
            SELECT
                ollama_admin_url,
                snapshot_ts,
                total_vram_used_bytes,
                total_models_loaded,
                loaded_models,
                MAX(total_vram_used_bytes) OVER (PARTITION BY ollama_admin_url) AS capacity_bytes
            FROM ollama_provider_snapshots
            WHERE poll_success = TRUE
              AND snapshot_ts >= :start_ts
              AND snapshot_ts < :end_ts
            ORDER BY ollama_admin_url, snapshot_ts
        """)

        try:
            rows = self.session.execute(sql, params).fetchall()
            if not rows:
                return {"error": "No VRAM data available for the requested day."}, 404

            providers_data: Dict[str, List[Dict[str, Any]]] = {}

            for url, ts, used_bytes, models_loaded, loaded_models, capacity_bytes in rows:
                used = int(used_bytes or 0)
                cap = int(capacity_bytes or 0)
                remaining_bytes = (cap - used) if cap and cap > used else None
                if url not in providers_data:
                    providers_data[url] = []
                providers_data[url].append({
                    "timestamp": ts.isoformat() if ts else None,
                    "vram_mb": used // (1024 * 1024),
                    "vram_bytes": used,
                    "used_vram_mb": used // (1024 * 1024),
                    "remaining_vram_mb": (remaining_bytes // (1024 * 1024)) if isinstance(remaining_bytes, int) else None,
                    "models_loaded": models_loaded,
                    "loaded_models": json.loads(loaded_models) if isinstance(loaded_models, str) else loaded_models,
                })

            providers_list = [
                {"url": url, "data": data_points}
                for url, data_points in providers_data.items()
            ]
            return {"providers": providers_list}, 200

        except Exception as e:
            logger.error(f"Failed to query ollama_vram_stats: {e}")
            return {"error": str(e)}, 500

    def connect_model_api(self, logos_key: str, model_id: int, provider_id: int, api_key: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        mapping_exists = self.session.execute(text("""
            SELECT 1 FROM model_provider
            WHERE model_id = :model_id AND provider_id = :provider_id
            LIMIT 1
        """), {"model_id": int(model_id), "provider_id": int(provider_id)}).fetchone()

        if mapping_exists is None:
            return {"error": "Model is not connected to the specified provider."}, 400

        sql = text("""
                    INSERT INTO model_api_keys (model_id, provider_id, api_key)
                    VALUES (:model_id, :provider_id, :api_key)
                    ON CONFLICT (model_id, provider_id)
                    DO UPDATE SET api_key = EXCLUDED.api_key
                    RETURNING id
                """)
        result = self.session.execute(sql, {
            "model_id": int(model_id),
            "provider_id": int(provider_id),
            "api_key": api_key
        }).fetchone()
        self.session.commit()
        return {"result": f"Added api-connection to model.", "api_key_id": result.id if result else None}, 200

    def add_model_provider_profile(self, logos_key: str, model_name: str, model_endpoint: str, provider_id: int, profile_id: int, api_key: str):
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
        r, c = self.connect_model_api(logos_key, model_id, provider_id, api_key)
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

    def get_auth_info_to_deployment(self, model_id: int, provider_id: int, profile_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Resolve auth + routing info for a model/provider pair, optionally scoped to a profile.
        """
        profile_join = ""
        filters = "WHERE m.id = :model_id AND p.id = :provider_id"
        params: Dict[str, Any] = {
            "model_id": int(model_id),
            "provider_id": int(provider_id),
        }

        if profile_id is not None:
            profile_join = """
                JOIN profile_model_permissions pmp ON pmp.model_id = m.id
            """
            filters += " AND pmp.profile_id = :profile_id"
            params["profile_id"] = int(profile_id)

        sql = text(f"""
            SELECT m.id          AS model_id,
                   m.name        AS model_name,
                   m.endpoint    AS endpoint,
                   p.id          AS provider_id,
                   p.name        AS provider_name,
                   p.base_url    AS base_url,
                   p.auth_name   AS auth_name,
                   p.auth_format AS auth_format,
                   mak.api_key   AS api_key
            FROM models m
            JOIN model_provider mp ON m.id = mp.model_id
            JOIN providers p ON mp.provider_id = p.id
            LEFT JOIN model_api_keys mak
                ON mak.model_id = m.id AND mak.provider_id = p.id
            {profile_join}
            {filters}
            LIMIT 1
        """)

        row = self.session.execute(sql, params).mappings().first()
        return dict(row) if row else None

    def get_deployments_by_profile(self, logos_key: str, profile_id: int) -> list[Deployment]:
        """
        Get a list of all authorized model deployments for a profile.

        Returns: List of complete deployment dicts with:
            - model_id
            - provider_id
            - type
        """
        sql = text("""
                   SELECT m.id               as model_id,
                          p.id               as provider_id,
                          p.provider_type    as type
                   FROM models m
                            JOIN model_provider mp ON m.id = mp.model_id
                            JOIN providers p ON mp.provider_id = p.id
                            JOIN model_api_keys mak ON m.id = mak.model_id AND p.id = mak.provider_id
                            JOIN profile_model_permissions pmp ON m.id = pmp.model_id
                            JOIN profiles pr ON pmp.profile_id = pr.id
                            JOIN process proc ON pr.process_id = proc.id
                   WHERE proc.logos_key = :logos_key
                     AND pr.id = :profile_id
                   ORDER BY m.id, p.id
                   """)
        rows = self.session.execute(sql, {
            "logos_key": logos_key,
            "profile_id": profile_id
        }).mappings().all()
        return [cast(Deployment, dict(row)) for row in rows]


    # ADMIN ONLY
    def get_all_deployments(self) -> list[Deployment]:
        """
        Get a list of ALL model deployments.

        Returns: List of complete deployment dicts with:
            - model_id
            - provider_id
            - type
        """
        sql = text("""
                   SELECT m.id               as model_id,
                          p.id               as provider_id,
                          p.provider_type    as type
                   FROM models m
                            JOIN model_provider mp ON m.id = mp.model_id
                            JOIN providers p ON mp.provider_id = p.id
                            JOIN model_api_keys mak ON m.id = mak.model_id AND p.id = mak.provider_id
                   ORDER BY m.id, p.id
                   """)
        rows = self.session.execute(sql, {}).mappings().all()
        return [cast(Deployment, dict(row)) for row in rows]

    def get_models_for_profile(self, profile_id: int) -> list[Dict[str, Any]]:
        """
        Get all models that a profile has access to via profile_model_permissions.

        Returns:
            List of dicts with model id, name, and description.
        """
        sql = text("""
            SELECT DISTINCT m.id, m.name, m.description
            FROM models m
                JOIN profile_model_permissions pmp ON m.id = pmp.model_id
            WHERE pmp.profile_id = :profile_id
            ORDER BY m.id
        """)
        rows = self.session.execute(sql, {"profile_id": int(profile_id)}).mappings().all()
        return [dict(row) for row in rows]

    def get_model_for_profile(self, profile_id: int, model_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a single model by name if the profile has access to it.

        Returns:
            Dict with model id, name, and description, or None if not found.
        """
        sql = text("""
            SELECT DISTINCT m.id, m.name, m.description
            FROM models m
                JOIN profile_model_permissions pmp ON m.id = pmp.model_id
            WHERE pmp.profile_id = :profile_id
              AND m.name = :name
            ORDER BY m.id LIMIT 1
        """)
        row = self.session.execute(
            sql, {"profile_id": int(profile_id), "name": model_name}
        ).mappings().first()
        return dict(row) if row else None

    # TODO: Remove these methods if not needed anymore
    # def get_models_by_profile(self, logos_key: str, profile_id: int):
    #     """
    #     Get a list of models accessible by a given profile-ID.
    #     """
    #     sql = text("""
    #                SELECT models.id
    #                FROM models,
    #                     process,
    #                     profiles,
    #                     profile_model_permissions,
    #                     model_provider,
    #                     providers
    #                WHERE process.logos_key = :logos_key
    #                     and process.id = profiles.process_id
    #                     and profiles.id = profile_model_permissions.profile_id
    #                     and profile_model_permissions.model_id = models.id
    #                     and model_provider.model_id = models.id
    #                     and providers.id = model_provider.provider_id
    #                     and profiles.id = :profile_id
    #                     and EXISTS (
    #                         SELECT 1
    #                         FROM model_api_keys
    #                         WHERE model_api_keys.profile_id = profiles.id
    #                           and model_api_keys.provider_id = providers.id
    #                     )
    #                """)
    #     result = self.session.execute(sql, {"logos_key": logos_key, "profile_id": profile_id}).fetchall()
    #     return [i.id for i in result]
    #
    # def get_models_with_key(self, logos_key: str):
    #     """
    #     Get a list of models accessible by a given key.
    #     """
    #     sql = text("""
    #         SELECT models.id
    #         FROM models, process, profiles, profile_model_permissions, model_provider, providers
    #         WHERE process.logos_key = :logos_key
    #             and process.id = profiles.process_id
    #             and profiles.id = profile_model_permissions.profile_id
    #             and profile_model_permissions.model_id = models.id
    #             and model_provider.model_id = models.id
    #             and providers.id = model_provider.provider_id
    #             and EXISTS (
    #                 SELECT 1
    #                 FROM model_api_keys
    #                 WHERE model_api_keys.profile_id = profiles.id
    #                   and model_api_keys.provider_id = providers.id
    #             )
    #     """)
    #     result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
    #     return [i.id for i in result]

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
            FROM providers
                JOIN model_provider mp ON providers.id = mp.provider_id
                JOIN models m ON mp.model_id = m.id
                JOIN profile_model_permissions pmp ON pmp.model_id = m.id
                JOIN profiles pr ON pr.id = pmp.profile_id
                JOIN process proc ON proc.id = pr.process_id
            WHERE proc.logos_key = :logos_key
        """)
        result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
        return [i.id for i in result]

    def get_provider_info(self, logos_key: str):
        """
        Get a list of providers accessible by a given key.
        """
        sql = text("""
            SELECT DISTINCT providers.id, providers.name, providers.base_url, providers.auth_name, providers.auth_format
            FROM providers
                JOIN model_provider mp ON providers.id = mp.provider_id
                JOIN models m ON mp.model_id = m.id
                JOIN profile_model_permissions pmp ON pmp.model_id = m.id
                JOIN profiles pr ON pr.id = pmp.profile_id
                JOIN process proc ON proc.id = pr.process_id
            WHERE proc.logos_key = :logos_key
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
            SELECT DISTINCT models.id, models.name, models.endpoint, models.weight_privacy, models.weight_latency, models.weight_accuracy, models.weight_cost, models.weight_quality, models.tags, models.parallel, models.description
            FROM models, profile_model_permissions, profiles, process
            WHERE process.logos_key = :logos_key
                and process.id = profiles.process_id
                and profiles.id = profile_model_permissions.profile_id
                and profile_model_permissions.model_id = models.id
        """)
        result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
        return [(i.id, i.name, i.endpoint, i.weight_privacy, i.weight_latency, i.weight_accuracy, i.weight_cost, i.weight_quality, i.tags, i.parallel, i.description) for i in result]

    def get_all_models_data(self):
        """
        Get a list of models and their data in the database. Used for rebalancing.
        """
        sql = text("""
            SELECT models.id, models.name, models.endpoint, models.weight_privacy, models.weight_latency, models.weight_accuracy, models.weight_cost, models.weight_quality, models.tags, models.parallel, models.description
            FROM models
        """)
        result = self.session.execute(sql).fetchall()
        return [(i.id, i.name, i.endpoint, i.weight_privacy, i.weight_latency, i.weight_accuracy, i.weight_cost, i.weight_quality, i.tags, i.parallel, i.description) for i in result]

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

    def get_key_to_model_provider(self, model_id: Optional[int], provider_id: int):
        if model_id is None:
            return None
        sql = text("""
                   SELECT api_key
                   FROM model_api_keys
                   WHERE model_api_keys.model_id = :model_id
                       and model_api_keys.provider_id = :provider_id
                   """)
        result = self.session.execute(
            sql,
            {"model_id": int(model_id), "provider_id": int(provider_id)}
        ).fetchone()
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
        if not isinstance(log_id, int):
            return {"error": "Invalid log_id"}, 400
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
            "token_prices",
            "jobs"
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
            "token_prices",
            "jobs"
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
        call the connect_process_provider-Endpoint with the profile ID and provider ID. This validates the connection
        but provider access is ultimately controlled by model permissions.
    If you just want to use Logos as a proxy, you're done here with the basics. Else proceed with the following steps:
    6. Connect Profiles with Models. Now you define which Profiles can interact with which Models. Therefore
        call the connect_process_model-Endpoint analogous as in step 5.
    7. Connect Models with Providers. Now you define which Models are connected to which Providers. Therefore
        call the connect_model_provider-Endpoint analogous as in step 6. 
    8. Connect api-key and model. If a model requires its own api-key under a certain provider, you can now
        connect a stored api-key to that model. Otherwise this is not necessary. Therefore call the 
        connect_model_api-Endpoint with model_id, provider_id and api_key.
    Congratulations! You have successfully set up Logos and can now call Logos to obtain results from your
    stored models. Keep in mind that you now provide the logos-key in the request header, not the data.
    """
    pass
