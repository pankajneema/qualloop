#!/bin/sh
# DEV/CI ONLY. Renders the Redis ACL file from the template using QL_REDIS_PASSWORD (placeholder default from
# compose / CI secrets), then starts redis-server with it. The ACL file holds only a SHA-256 hash.
set -eu
: "${QL_REDIS_PASSWORD:?QL_REDIS_PASSWORD must be set}"
hash=$(printf '%s' "$QL_REDIS_PASSWORD" | sha256sum | cut -d' ' -f1)
mkdir -p /etc/redis
# ACL files do not allow comments or blank lines, so strip them from the template.
grep -Ev '^[[:space:]]*(#|$)' /acl/users.acl.tmpl | sed "s/@APP_HASH@/${hash}/" > /etc/redis/users.acl
chown redis:redis /etc/redis/users.acl
chmod 600 /etc/redis/users.acl
# DEBUG stays disabled (Redis default): it is refused before the ACL check, and no ACL user has it (-@dangerous).
exec docker-entrypoint.sh redis-server --aclfile /etc/redis/users.acl
