import datetime
import enum

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    BigInteger,
    Boolean,
    Column,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


# Enum definition
class ThresholdLevel(enum.Enum):
    """Privacy levels — the single ordered definition, most trusted first.

    The declaration order IS the trust ordering (index 0 = strictest);
    pipeline.py derives PRIVACY_ORDER from it and dbmanager.py derives the
    validation set, so a new level added here is known to router and
    registration at once. Mirrors the Postgres enum threshold_enum
    (liquibase 000 + 024) and the webservice Java enum of the same name —
    keep those in sync.

    The axis is "how much do we trust this deployment with our data".
    THIRD_PARTY_HARDWARE covers hardware outside operator control (e.g. a
    personal Mac running the MLX worker, see logos-workernode/MACOS.md):
    its owner can inspect the running processes, so it orders below every
    cloud tier and LOCAL keeps meaning "our datacentre".
    """

    LOCAL = "LOCAL"
    CLOUD_IN_EU_BY_EU_PROVIDER = "CLOUD_IN_EU_BY_EU_PROVIDER"
    CLOUD_IN_EU_BY_US_PROVIDER = "CLOUD_IN_EU_BY_US_PROVIDER"
    CLOUD_NOT_IN_EU_BY_US_PROVIDER = "CLOUD_NOT_IN_EU_BY_US_PROVIDER"
    THIRD_PARTY_HARDWARE = "THIRD_PARTY_HARDWARE"


class LoggingLevel(enum.Enum):
    BILLING = "BILLING"
    FULL = "FULL"


class ResultStatus(enum.Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class ApiKeyType(enum.Enum):
    DEVELOPER = "developer"
    APPLICATION = "application"


class ProviderType(enum.Enum):
    LOGOSNODE = "logosnode"
    AZURE = "azure"
    CLOUD = "cloud"


class CloudProviderType(enum.Enum):
    AZURE = "azure"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    BEDROCK = "bedrock"
    DEEPSEEK = "deepseek"
    GROQ = "groq"
    # Another Logos instance used as an upstream. It serves every surface this
    # one does, including the Anthropic Messages API, so requests reach it
    # unchanged instead of being translated into an OpenAI dialect.
    LOGOS = "logos"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    prename = Column(String)
    name = Column(String)
    email = Column(String, unique=True)
    role = Column(String, default="app_developer")


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    default_cloud_rpm_limit = Column(Integer, nullable=True, default=5)
    default_cloud_tpm_limit = Column(Integer, nullable=True, default=10000)
    default_local_rpm_limit = Column(Integer, nullable=True, default=5)
    default_local_tpm_limit = Column(Integer, nullable=True, default=10000)
    default_monthly_budget_micro_cents = Column(BigInteger, nullable=True, default=100000000)
    team_monthly_budget_micro_cents = Column(BigInteger, nullable=True, default=500000000)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    key_value = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    key_type = Column(
        Enum(ApiKeyType, name="api_key_type_enum"),
        nullable=False,
        default=ApiKeyType.DEVELOPER,
    )
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    environment = Column(Text)
    log = Column(Enum(LoggingLevel), default=LoggingLevel.BILLING)
    settings = Column(JSON)
    default_priority = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)

    use_custom_permissions = Column(Boolean, nullable=False, default=False)

    team = relationship("Team")
    user = relationship("User")


class Model(Base):
    __tablename__ = "models"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    weight_latency = Column(Integer)
    weight_accuracy = Column(Integer)
    weight_cost = Column(Integer)
    weight_quality = Column(Integer)
    tags = Column(Text)
    description = Column(Text)


class Provider(Base):
    __tablename__ = "providers"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    base_url = Column(Text, nullable=True)
    provider_type = Column(
        Enum(ProviderType, name="provider_type_enum"),
        nullable=False,
        default=ProviderType.CLOUD,
    )
    cloud_provider_type = Column(Enum(CloudProviderType, name="cloud_provider_type_enum"), nullable=True)
    privacy_level = Column(Enum(ThresholdLevel, name="threshold_enum"), nullable=False)
    auth_name = Column(String, nullable=False)
    auth_format = Column(String, nullable=False)
    api_key = Column(Text, nullable=True)
    ollama_admin_url = Column(Text, default="")
    total_vram_mb = Column(Integer, nullable=True)
    parallel_capacity = Column(Integer, default=20)
    keep_alive_seconds = Column(Integer, default=300)
    max_loaded_models = Column(Integer, default=3)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )


class ModelProvider(Base):
    __tablename__ = "model_provider"
    id = Column(Integer, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=False)

    api_key = Column(Text, nullable=True, default=None)
    endpoint = Column(Text, nullable=True, default=None)
    __table_args__ = (UniqueConstraint("model_id", "provider_id", name="uq_model_provider_mapping"),)

    provider = relationship("Provider")
    model = relationship("Model")


class Policy(Base):
    __tablename__ = "policies"
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
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="CASCADE"))
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"))


class LogEntry(Base):
    __tablename__ = "log_entry"

    id = Column(Integer, primary_key=True)
    timestamp_request = Column(TIMESTAMP(timezone=True))
    timestamp_forwarding = Column(TIMESTAMP(timezone=True))
    timestamp_response = Column(TIMESTAMP(timezone=True))
    time_at_first_token = Column(TIMESTAMP(timezone=True))

    privacy_level = Column(Enum(LoggingLevel))
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="SET NULL"))
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    environment = Column(Text)
    client_ip = Column(Text)
    input_payload = Column(JSON)
    headers = Column(JSON)
    response_payload = Column(JSON)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="SET NULL"))
    model_id = Column(Integer, ForeignKey("models.id", ondelete="SET NULL"))
    policy_id = Column(Integer, ForeignKey("policies.id", ondelete="SET NULL"))

    classification_statistics = Column(JSON)
    request_id = Column(Text)
    priority = Column(String(10), default="medium")
    initial_priority = Column(Text)
    priority_when_scheduled = Column(Text)
    queue_depth_at_enqueue = Column(Integer)
    queue_depth_at_schedule = Column(Integer)
    timeout_s = Column(Integer)
    queue_depth_at_arrival = Column(Integer)
    utilization_at_arrival = Column(Numeric)
    queue_wait_ms = Column(Numeric)
    # Whether the key's rate limiter admitted the request. NULL when no limit
    # is configured (the request was never checked) or for pre-migration
    # rows; FALSE for a request the limiter rejected after scheduling. The
    # usage window counts everything except explicit FALSE.
    rate_limit_admitted = Column(Boolean, nullable=True)
    was_cold_start = Column(Boolean, default=False)
    load_duration_ms = Column(Numeric)
    available_vram_mb = Column(Integer)
    azure_rate_remaining_requests = Column(Integer)
    azure_rate_remaining_tokens = Column(Integer)
    result_status = Column(Enum(ResultStatus, name="result_status_enum"))
    error_message = Column(Text)
    settled_cost_micro_cents = Column(BigInteger)
    cost_finalized = Column(Boolean, nullable=False, default=False)

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
    __tablename__ = "token_prices"

    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, ForeignKey("token_types.id", ondelete="CASCADE"), nullable=False)
    valid_from = Column(TIMESTAMP(timezone=True), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=True)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), nullable=True)
    price_per_k_unit = Column(BigInteger, nullable=False)
    unit = Column(Text, nullable=False, server_default="token")
    min_context_tokens = Column(BigInteger, nullable=False, server_default="0")
    service_tier = Column(Text, nullable=False, server_default="default")

    token_type = relationship("TokenTypes")


class TeamModelPermission(Base):
    __tablename__ = "team_model_permissions"
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), primary_key=True)


class ApiKeyModelPermission(Base):
    __tablename__ = "api_key_model_permissions"
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="CASCADE"), primary_key=True)
    model_id = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), primary_key=True)


class TeamProviderPermission(Base):
    __tablename__ = "team_provider_permissions"
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), primary_key=True)


class ApiKeyProviderPermission(Base):
    __tablename__ = "api_key_provider_permissions"
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="CASCADE"), primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), primary_key=True)


class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.PENDING)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="SET NULL"))
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    environment = Column(Text)
    request_payload = Column(JSON, nullable=False)
    result_payload = Column(JSON)
    error_message = Column(Text)
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )

    api_key = relationship("ApiKey")


class LatencyObservation(Base):
    """Persistent EWMA state for the dynamic scheduler's LatencyStore.

    Each row stores one EWMA keyed by (model_name, provider_id, tier).
    ``tier`` is one of the ReadinessTier string values for load/wake overhead,
    or the literal strings ``"ttft"``, ``"e2e"``, ``"prefill_per_token"``
    for the per-model latency metrics.  The real provider_id is always stored.
    """

    __tablename__ = "latency_observations"
    __table_args__ = (UniqueConstraint("model_name", "provider_id", "tier"),)

    id = Column(Integer, primary_key=True)
    model_name = Column(String, nullable=False)
    provider_id = Column(Integer, nullable=False)
    tier = Column(String, nullable=False)
    ewma_value = Column(Float, nullable=False)
    n = Column(Integer, nullable=False, default=1)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )


class BatchObject(Base):
    """A file or batch that lives at the provider, and the team that owns it.

    The Batch API hands the client an upstream id it uses for hours after the
    request that created it. Logos forwards those calls with a provider
    credential shared by every key allowed to use that provider, so ownership
    has to be recorded here — otherwise any such key could poll, cancel or
    delete another team's batch and download its output file.

    ``settled_at`` is the billing latch: a terminal batch is metered exactly
    once, when its output rows are read.
    """

    __tablename__ = "batch_objects"
    __table_args__ = (UniqueConstraint("provider_id", "kind", "upstream_id", name="uq_batch_objects_upstream"),)

    id = Column(BigInteger, primary_key=True)
    kind = Column(Text, nullable=False)  # "file" | "batch"
    upstream_id = Column(Text, nullable=False)
    # NULL for a batch Logos runs itself: each of its lines picks its own
    # provider, so the batch as a whole belongs to none.
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"))
    execution = Column(Text, nullable=False, server_default="provider")  # "provider" | "logos"
    api_key_id = Column(Integer, ForeignKey("api_keys.id"))
    team_id = Column(Integer, ForeignKey("teams.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    input_file_id = Column(Text)
    status = Column(Text)
    settled_at = Column(TIMESTAMP(timezone=True))
    filename = Column(Text)
    size_bytes = Column(BigInteger)
    endpoint = Column(Text)
    completion_window = Column(Text)
    request_metadata = Column(JSON)
    output_file_id = Column(Text)
    error_file_id = Column(Text)
    total_requests = Column(Integer, nullable=False, default=0)
    completed_requests = Column(Integer, nullable=False, default=0)
    failed_requests = Column(Integer, nullable=False, default=0)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    # The Logos model names a batch input file asks for, as uploaded. When a
    # forwarded batch turns out that the provider cannot batch one of them,
    # this is what gets marked as not batch-eligible on that provider.
    models = Column(JSON)
    # Lease of the runner currently executing a Logos-run batch: which process
    # holds it, and until when. A row whose lease is expired (or empty) is
    # recoverable, so a batch whose runner died is picked up again — but a
    # batch another live process is running is not.
    runner_id = Column(Text)
    lease_expires_at = Column(TIMESTAMP(timezone=True))
    started_at = Column(TIMESTAMP(timezone=True))
    finished_at = Column(TIMESTAMP(timezone=True))
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )


class BatchFileContent(Base):
    """The bytes of a file Logos holds itself.

    A forwarded batch keeps its files at the provider; a Logos-run one has
    nowhere else to put them. Separate from ``batch_objects`` so a listing does
    not drag megabytes of JSONL with it.
    """

    __tablename__ = "batch_file_contents"

    batch_object_id = Column(BigInteger, ForeignKey("batch_objects.id", ondelete="CASCADE"), primary_key=True)
    content = Column(LargeBinary, nullable=False)


class ProviderBatchCapability(Base):
    """Whether a provider's Batch API answers, as last probed.

    A cloud provider is not automatically a batch target: an OpenAI-shaped
    resource can be a self-hosted inference endpoint that serves chat and
    nothing else. The answer is a property of the upstream, so it is probed
    and cached rather than configured — a hand-set flag would go stale.
    """

    __tablename__ = "provider_batch_capability"

    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), primary_key=True)
    supports_batch = Column(Boolean, nullable=False, default=False)
    detail = Column(Text)
    checked_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )


class ProviderModelBatchEligibility(Base):
    """Per-model Batch eligibility on one provider, as learned from the provider.

    Serving a model and serving it *for batch* are two different things: an
    Azure resource answers its Batch API with a Global-Batch deployment for
    each model it offers for that, and a model that only exists as a Standard
    deployment cannot be batched there no matter how capable the resource
    looks. The Batch API does not publish a model list for its batch endpoint,
    so the knowledge is learned from the provider's own refusals (a batch
    creation or a failed batch naming the unsupported model) and tracked here —
    one row per model, with the detail of what the provider said.

    Absence means "unknown", which routes to the provider as before (its error
    is then passed through and can teach this table); an ``eligible = false``
    row is what moves the batch to Logos execution. Rows expire after a TTL so
    a model the provider adds to Batch later is picked up automatically, at the
    price of one more failed batch.
    """

    __tablename__ = "provider_model_batch_eligibility"
    __table_args__ = (UniqueConstraint("provider_id", "model_id", name="uq_provider_model_batch_eligibility"),)

    id = Column(BigInteger, primary_key=True)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), nullable=False)
    model_id = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    eligible = Column(Boolean, nullable=False, default=False)
    detail = Column(Text)
    checked_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )


class BatchLineResult(Base):
    """One finished request line of a Logos-run batch, keyed by its custom_id.

    The runner persists each line's result as it completes, so a batch whose
    runner died (or was redeployed) is resumed from the checkpoint rather than
    replayed from line zero — the finished lines were already sent through the
    pipeline and already billed, and running them again would bill them twice.
    The result file itself is only written when the batch finishes; this table
    is what makes "finished" resumable.
    """

    __tablename__ = "batch_line_results"
    __table_args__ = (UniqueConstraint("batch_object_id", "custom_id", name="uq_batch_line_results"),)

    batch_object_id = Column(BigInteger, ForeignKey("batch_objects.id", ondelete="CASCADE"), primary_key=True)
    custom_id = Column(Text, primary_key=True)
    row = Column(JSON, nullable=False)
    finished_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
