# OAuth callback and pending-code schedule removed in SDK 5.9.1 migration.
# The unified platform gateway (/v1/ext/mail/oauth/{provider}/callback)
# now handles code exchange, email lookup, and account storage.
# See ext.oauth() declarations in app.py.
