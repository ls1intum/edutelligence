from sqlalchemy import create_engine, Column, Integer, String, Boolean, Enum, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()


# Enum definition
class ThresholdLevel(enum.Enum):
    LOCAL = 'LOCAL'
    CLOUD_IN_EU_BY_US_PROVIDER = 'CLOUD_IN_EU_BY_US_PROVIDER'
    CLOUD_NOT_IN_EU_BY_US_PROVIDER = 'CLOUD_NOT_IN_EU_BY_US_PROVIDER'
    CLOUD_IN_EU_BY_EU_PROVIDER = 'CLOUD_IN_EU_BY_EU_PROVIDER'


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


class Process(Base):
    __tablename__ = 'process'
    id = Column(Integer, primary_key=True)
    logos_key = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    service_id = Column(Integer, ForeignKey('services.id'), nullable=False)
    profile_id = Column(Integer, ForeignKey('profiles.id'), nullable=False)
    log = Column(Boolean, default=False)

    user = relationship("User")
    service = relationship("Service")
    profile = relationship("Profile")


class Model(Base):
    __tablename__ = 'models'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    endpoint = Column(Text)
    api_id = Column(Integer, ForeignKey("model_api_keys.id", ondelete="SET NULL"))
    weight_privacy = Column(Integer)
    weight_latency = Column(Integer)
    weight_accuracy = Column(Integer)
    weight_cost = Column(Integer)
    weight_quality = Column(Integer)


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
    provider_id = Column(Integer, ForeignKey('providers.id'), nullable=False)
    model_id = Column(Integer, ForeignKey('models.id'), nullable=False)

    provider = relationship("Provider")
    model = relationship("Model")


class ModelApiKey(Base):
    __tablename__ = 'model_api_keys'
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey('profiles.id'), nullable=False)
    provider_id = Column(Integer, ForeignKey('providers.id'), nullable=False)
    api_key = Column(Text, nullable=False)

    profile = relationship("Profile")
    provider = relationship("Provider")


class Policy(Base):
    __tablename__ = 'policies'
    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey('process.id'), nullable=False)
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
    profile_id = Column(Integer, ForeignKey('profiles.id'), nullable=False)
    model_id = Column(Integer, ForeignKey('models.id'), nullable=False)

    profile = relationship("Profile")
    model = relationship("Model")
