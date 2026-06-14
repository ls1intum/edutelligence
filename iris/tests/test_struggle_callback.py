from iris.web.status.status_update import StruggleInterventionCallback


def test_callback_builds_struggle_url_and_status():
    cb = StruggleInterventionCallback(
        run_id="job-9", base_url="http://localhost:8080", initial_stages=[]
    )
    assert cb.url == (
        "http://localhost:8080/api/iris/internal/pipelines/"
        "struggle-intervention/runs/job-9/status"
    )
    # the status object accepts the action result fields
    cb.status.action = "active"
    assert cb.status.action == "active"
