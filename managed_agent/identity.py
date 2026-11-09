"""Who may call this deployment: callers present a LangSmith workspace API key as `x-api-key`."""

from managed_deepagents import auth, define_identity

identity = define_identity(auth=auth.langsmith_api_key())
