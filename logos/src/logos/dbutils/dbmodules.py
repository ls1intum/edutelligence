import datetime
from sqlalchemy import Column, Integer, String, Enum, Text, ForeignKey, JSON, TIMESTAMP, \
    Numeric, CheckConstraint, Boolean, BigInteger, Date
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()


# Enum definition
class ThresholdLevel(enum.Enum):
    LOCAL = 'LOCAL'
    CLOUD_IN_EU_BY_US_PROVIDER = 'CLOUD_IN_EU_BY_US_PROVIDER'
    CLOUD_NOT_IN_EU_BY_US_PROVIDER = 'CLOUD_NOT_IN_EU_BY_US_PROVIDER'
    CLOUD_IN_EU_BY_EU_PROVIDER = 'CLOUD_IN_EU_BY_EU_PROVIDER'


class LoggingLevel(enum.Enum):
    BILLING = 'BILLING'
    FULL = 'FULL'


class ResultStatus(enum.Enum):
    SUCCESS = 'success'
    ERROR = 'error'
    TIMEOUT = 'timeout'


class ApiKeyType(enum.Enum):
    DEVELOPER = 'developer'
    APPLICATION = 'application'


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    prename = Column(String)
    name = Column(String)
    email = Column(String, unique=True)
    role = Column(String, default='app_developer')


class Team(Base):
    __tablename__ = 'teams'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    default_cloud_rpm_limit = Column(Integer, nullable=True, default=5)
    default_cloud_tpm_limit = Column(Integer, nullable=True, default=10000)
    default_local_rpm_limit = Column(Integer, nullable=True, default=5)
    default_local_tpm_limit = Column(Integer, nullable=True, default=10000)
    default_monthly_budget_micro_cents = Column(BigInteger, nullable=True, default=100000000)
    team_monthly_budget_micro_cents = Column(BigInteger, nullable=True, default=500000000)


class ApiKey(Base):
    __tablename__ = 'api_keys'
    id = Column(Integer, primary_key=True)
    key_value = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    key_type = Column(Enum(ApiKeyType, name='api_key_type_enum'), nullable=False, default=ApiKeyType.DEVELOPER)
    team_id = Column(Integer, ForeignKey('teams.id', ondelete='CASCADE'))
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    environment = Column(Text)
    log = Column(Enum(LoggingLevel), default=LoggingLevel.BILLING)
    settings = Column(JSON)
    default_priority = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)

    team = relationship("Team")
    user = relationship("User")


class Model(Base):
    __tablename__ = 'models'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    weight_privacy = Column(Enum(ThresholdLevel))
    weight_latency = Column(Integer)
    weight_accuracy = Column(Integer)
    weight_cost = Column(Integer)
    weight_quality = Column(Integer)
    tags = Column(Text)
    parallel = Column(Integer, default=1)
    description = Column(Text)
    __table_args__ = (
        CheckConstraint('parallel BETWEEN 1 AND 256'),
    )


class Provider(Base):
    __tablename__ = 'providers'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    base_url = Column(Text, nullable=False)
    auth_name = Column(String, nullable=False)
    auth_format = Column(String, nullable=False)
    api_key = Column(Text, nullable=True)


class ModelProvider(Base):
    __tablename__ = 'model_provider'
    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey('providers.id', ondelete="CASCADE"), nullable=False)
    model_id = Column(Integer, ForeignKey('models.id', ondelete="CASCADE"), nullable=False)

    provider = relationship("Provider")
    model = relationship("Model")


class ModelApiKey(Base):
    __tablename__ = 'model_api_keys'
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey('models.id', ondelete="CASCADE"), nullable=False)
    provider_id = Column(Integer, ForeignKey('providers.id', ondelete="CASCADE"), nullable=False)
    api_key = Column(Text, nullable=False)
    endpoint = Column(Text, nullable=False, default='')

    model = relationship("Model")
    provider = relationship("Provider")


class Policy(Base):
    __tablename__ = 'policies'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    threshold_privacy = Column(Enum(ThresholdLevel))
    threshold_latency = Column(Integer)
    threshold_accuracy = Column(Integer)
    threshold_cost = Column(Integer)
    threshold_quality = Column(Integer)
    priority = Column(Integer)
    topic = Column(Text)
    api_key_id = Column(Integer, ForeignKey('api_keys.id', ondelete="CASCADE"))
    team_id = Column(Integer, ForeignKey('teams.id', ondelete="CASCADE"))


class LogEntry(Base):
    __tablename__ = 'log_entry'

    id = Column(Integer, primary_key=True)
    timestamp_request = Column(TIMESTAMP(timezone=True))
    timestamp_forwarding = Column(TIMESTAMP(timezone=True))
    timestamp_response = Column(TIMESTAMP(timezone=True))
    time_at_first_token = Column(TIMESTAMP(timezone=True))

    privacy_level = Column(Enum(LoggingLevel))
    api_key_id = Column(Integer, ForeignKey('api_keys.id', ondelete="SET NULL"))
    team_id = Column(Integer, ForeignKey('teams.id', ondelete="SET NULL"))
    user_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"))
    environment = Column(Text)
    client_ip = Column(Text)
    input_payload = Column(JSON)
    headers = Column(JSON)
    response_payload = Column(JSON)
    provider_id = Column(Integer, ForeignKey('providers.id', ondelete="SET NULL"))
    model_id = Column(Integer, ForeignKey('models.id', ondelete="SET NULL"))
    policy_id = Column(Integer, ForeignKey('policies.id', ondelete="SET NULL"))

    classification_statistics = Column(JSON)
    request_id = Column(Text)
    priority = Column(String(10), default='medium')
    initial_priority = Column(Text)
    priority_when_scheduled = Column(Text)
    queue_depth_at_enqueue = Column(Integer)
    queue_depth_at_schedule = Column(Integer)
    timeout_s = Column(Integer)
    queue_depth_at_arrival = Column(Integer)
    utilization_at_arrival = Column(Numeric)
    queue_wait_ms = Column(Numeric)
    was_cold_start = Column(Boolean, default=False)
    load_duration_ms = Column(Numeric)
    available_vram_mb = Column(Integer)
    azure_rate_remaining_requests = Column(Integer)
    azure_rate_remaining_tokens = Column(Integer)
    result_status = Column(Enum(ResultStatus, name="result_status_enum"))
    error_message = Column(Text)

    usage_tokens = relationship("UsageTokens")
    api_key = relationship("ApiKey")


class TokenTypes(Base):
    __tablename__ = "token_types"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text)


class UsageTokens(Base):
    __tablename__ = "usage_tokens"

    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, ForeignKey("token_types.id", ondelete="CASCADE"), nullable=False)
    log_entry_id = Column(Integer, ForeignKey("log_entry.id", ondelete="CASCADE"), nullable=False)
    token_count = Column(Integer, default=0)


class TokenPrice(Base):
    __tablename__ = 'token_prices'

    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, ForeignKey("token_types.id", ondelete="CASCADE"), nullable=False)
    valid_from = Column(TIMESTAMP(timezone=True), nullable=False)
    price_per_k_token = Column(Numeric(10, 6), nullable=False)

    token_type = relationship("TokenTypes")


class TeamModelPermission(Base):
    __tablename__ = 'team_model_permissions'
    team_id = Column(Integer, ForeignKey('teams.id', ondelete='CASCADE'), primary_key=True)
    model_id = Column(Integer, ForeignKey('models.id', ondelete='CASCADE'), primary_key=True)


class ApiKeyModelPermission(Base):
    __tablename__ = 'api_key_model_permissions'
    api_key_id = Column(Integer, ForeignKey('api_keys.id', ondelete='CASCADE'), primary_key=True)
    model_id = Column(Integer, ForeignKey('models.id', ondelete='CASCADE'), primary_key=True)


class BudgetUsage(Base):
    __tablename__ = 'budget_usage'
    api_key_id = Column(Integer, ForeignKey('api_keys.id', ondelete='CASCADE'), primary_key=True)
    month = Column(Date, primary_key=True)
    cost_micro_cents = Column(BigInteger, nullable=False, default=0)


class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Job(Base):
    __tablename__ = 'jobs'

    id = Column(Integer, primary_key=True)
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.PENDING)
    api_key_id = Column(Integer, ForeignKey('api_keys.id', ondelete="SET NULL"))
    team_id = Column(Integer, ForeignKey('teams.id', ondelete="SET NULL"))
    user_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"))
    environment = Column(Text)
    request_payload = Column(JSON, nullable=False)
    result_payload = Column(JSON)
    error_message = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False,
                        default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False,
                        default=lambda: datetime.datetime.now(datetime.timezone.utc),
                        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))

    api_key = relationship("ApiKey")