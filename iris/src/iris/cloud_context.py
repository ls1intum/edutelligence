from contextvars import ContextVar

isCloudEnabled = ContextVar("isCloudEnabled", default=False)
localModelString = "logos-v0.0.4__policy_default=false_privacy=LOCAL"