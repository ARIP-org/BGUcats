"""Code shared by the Lambdas behind the API (docs/app-plan/, milestone F2).

Copied into a function's package by its `make build-<name>` target, and
only into the functions that import it, so a change here redeploys exactly
those (tests/common/test_packaging.py holds the Makefile to that).

Nothing here holds a boto3 client or reads the environment at import: a
helper that needs a table is given one. The handlers keep their own
clients, and the tests replace those, so the helpers stay testable on
their own and a handler's tests do not change when a helper moves here.

    api      the request and the response: errors, the body, the caller,
             parameters, routing
    tables   reading DynamoDB the way this project must
    text     cleaning what a person typed before it is stored
    limits   how often a person may do something
    ids      new ULIDs (needs python-ulid in the function's requirements)
"""
