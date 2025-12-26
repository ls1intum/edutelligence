class FakeVectorDatabase:
    def __init__(self, snapshot_data):
        self.client = None
        self.snapshot = snapshot_data

        self.lectures = snapshot_data.get("lectures", [])
        self.transcriptions = snapshot_data.get("transcriptions", [])
        self.lecture_segments = snapshot_data.get("lecture_segments", [])
        self.lecture_units = snapshot_data.get("lecture_units", [])
        self.faqs = snapshot_data.get("faqs", [])

    def delete_collection(self, *args, **kwargs):
        pass

    def delete_object(self, *args, **kwargs):
        pass

    def get_client(self):
        return None
