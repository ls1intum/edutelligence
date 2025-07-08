from sqlalchemy import create_engine, Column, Integer, String, Boolean, Enum, Text, ForeignKey, JSON, TIMESTAMP, \
    Numeric, CheckConstraint
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
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


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    prename = Column(String)
    name = Column(String)


class Service(Base):
    __tablename__ = 'services'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class Profile(Base):
    __tablename__ = 'profiles'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    process_id = Column(Integer, ForeignKey('process.id', ondelete="CASCADE"), nullable=False)
    process = relationship("Process")


class Process(Base):
    __tablename__ = 'process'
    id = Column(Integer, primary_key=True)
    logos_key = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete="SET NULL"))
    service_id = Column(Integer, ForeignKey('services.id', ondelete="SET NULL"))
    log = Column(Enum(LoggingLevel))
    settings = Column(JSON)

    user = relationship("User")
    service = relationship("Service")


class Model(Base):
    __tablename__ = 'models'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    endpoint = Column(Text)
    api_id = Column(Integer, ForeignKey("model_api_keys.id", ondelete="SET NULL"))
    weight_privacy = Column(Enum(ThresholdLevel))
    weight_latency = Column(Integer)
    weight_accuracy = Column(Integer)
    weight_cost = Column(Integer)
    weight_quality = Column(Integer)
    tags = Column(Text)
    parallel = Column(Integer, default=1)
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
    profile_id = Column(Integer, ForeignKey('profiles.id', ondelete="SET NULL"))
    provider_id = Column(Integer, ForeignKey('providers.id', ondelete="CASCADE"), nullable=False)
    api_key = Column(Text, nullable=False)

    profile = relationship("Profile")
    provider = relationship("Provider")


class Policy(Base):
    __tablename__ = 'policies'
    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey('process.id', ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    threshold_privacy = Column(Enum(ThresholdLevel))
    threshold_latency = Column(Integer)
    threshold_accuracy = Column(Integer)
    threshold_cost = Column(Integer)
    threshold_quality = Column(Integer)
    priority = Column(Integer)
    topic = Column(Text)

    entity = relationship("Process")


class ProfileModelPermission(Base):
    __tablename__ = 'profile_model_permissions'
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey('profiles.id', ondelete="CASCADE"), nullable=False)
    model_id = Column(Integer, ForeignKey('models.id', ondelete="CASCADE"), nullable=False)

    profile = relationship("Profile")
    model = relationship("Model")


class LogEntry(Base):
    __tablename__ = 'log_entry'

    id = Column(Integer, primary_key=True)
    timestamp_request = Column(TIMESTAMP(timezone=True))
    timestamp_forwarding = Column(TIMESTAMP(timezone=True))
    timestamp_response = Column(TIMESTAMP(timezone=True))
    time_at_first_token = Column(TIMESTAMP(timezone=True))

    privacy_level = Column(Enum(LoggingLevel))

    process_id = Column(Integer, ForeignKey("process.id", ondelete="SET NULL"))
    client_ip = Column(Text)
    input_payload = Column(JSON)
    headers = Column(JSON)
    response_payload = Column(JSON)
    provider_id = Column(Integer)
    model_id = Column(Integer)

    usage_tokens = relationship("UsageTokens")


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
