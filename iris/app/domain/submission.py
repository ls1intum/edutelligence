class BuildLogEntry:
    def __init__(self, time: str, message: str):
        self.time = time
        self.message = message


class ProgrammingSubmission:
    def __init__(
        self, commit_hash: str, build_failed: bool, build_log_entries: [BuildLogEntry]
    ):
        self.commit_hash = commit_hash
        self.build_failed = build_failed
        self.build_log_entries = build_log_entries
