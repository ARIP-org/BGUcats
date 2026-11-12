"""The environment src/events/handler.py reads at import."""

import os

os.environ.setdefault("SOCIAL_TABLE_NAME", "bgucats-social-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
