"""
Dummy Policy for Logos Proxy Usage
"""


class ProxyPolicy(dict):
    def __init__(self):
        super().__init__()
        self["id"] = -1
        self["threshold_privacy"] = "CLOUD_NOT_IN_EU_BY_US_PROVIDER"
        self["threshold_latency"] = 0
        self["threshold_accuracy"] = 0
        self["threshold_cost"] = -1024
        self["threshold_quality"] = 0
        self["priority"] = 0
