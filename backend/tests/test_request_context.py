from app.graph.context import RequestContext


def test_request_context_scopes_checkpoint_to_user_and_trip():
    context = RequestContext.create("08ea6304-e03e-4f94-a0fc-5557709d9d7f")

    assert context.checkpoint_config["configurable"]["checkpoint_ns"] == context.user_id
    assert context.checkpoint_config["configurable"]["thread_id"] == context.trip_id
    assert context.request_id != context.trip_id
