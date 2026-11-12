"""The environment src/app/handler.py reads at import, set before any test
module imports it."""

import os

os.environ.setdefault("DATA_TABLE_NAME", "bgucats-data-test")
os.environ.setdefault("SOCIAL_TABLE_NAME", "bgucats-social-test")
os.environ.setdefault("MEDIA_BUCKET", "bgucats-media-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
